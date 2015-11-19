# Copyright 2015 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import io
import json
import logging
import tarfile

import netaddr
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import excutils
from oslo_utils import units
import requests
import stevedore

from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import utils


LOG = logging.getLogger(__name__)
CONF = cfg.CONF
DEFAULT_COLLECTOR = 'default'
_COLLECTOR_NS = 'ironic_python_agent.inspector.collectors'


def extension_manager(names):
    try:
        return stevedore.NamedExtensionManager(_COLLECTOR_NS,
                                               names=names,
                                               name_order=True)
    except KeyError as exc:
        raise errors.InspectionError('Failed to load collector %s' % exc)


def inspect():
    """Optionally run inspection on the current node.

    If ``inspection_callback_url`` is set in the configuration, get
    the hardware inventory from the node and post it back to the inspector.

    :return: node UUID if inspection was successful, None if associated node
             was not found in inspector cache. None is also returned if
             inspector support is not enabled.
    """
    if not CONF.inspection_callback_url:
        LOG.info('Inspection is disabled, skipping')
        return
    collector_names = [x.strip() for x in CONF.inspection_collectors.split(',')
                       if x.strip()]
    LOG.info('inspection is enabled with collectors %s', collector_names)

    # NOTE(dtantsur): inspection process tries to delay raising any exceptions
    # until after we posted some data back to inspector. This is because
    # inspection is run automatically on (mostly) unknown nodes, so if it
    # fails, we don't have much information for debugging.
    failures = utils.AccumulatedFailures(exc_class=errors.InspectionError)
    data = {}

    try:
        ext_mgr = extension_manager(collector_names)
        collectors = [(ext.name, ext.plugin) for ext in ext_mgr]
    except Exception as exc:
        with excutils.save_and_reraise_exception():
            failures.add(exc)
            call_inspector(data, failures)

    for name, collector in collectors:
        try:
            collector(data, failures)
        except Exception as exc:
            # No reraise here, try to keep going
            failures.add('collector %s failed: %s', name, exc)

    resp = call_inspector(data, failures)

    # Now raise everything we were delaying
    failures.raise_if_needed()

    if resp is None:
        LOG.info('stopping inspection, as inspector returned an error')
        return

    # Optionally update IPMI credentials
    setup_ipmi_credentials(resp)

    LOG.info('inspection finished successfully')
    return resp.get('uuid')


def call_inspector(data, failures):
    """Post data to inspector."""
    data['error'] = failures.get_error()

    LOG.info('posting collected data to %s', CONF.inspection_callback_url)
    LOG.debug('collected data: %s', data)

    encoder = encoding.RESTJSONEncoder()
    data = encoder.encode(data)

    resp = requests.post(CONF.inspection_callback_url, data=data)
    if resp.status_code >= 400:
        LOG.error('inspector error %d: %s, proceeding with lookup',
                  resp.status_code, resp.content.decode('utf-8'))
        return

    return resp.json()


def setup_ipmi_credentials(resp):
    """Setup IPMI credentials, if requested.

    :param resp: JSON response from inspector.
    """
    if not resp.get('ipmi_setup_credentials'):
        LOG.info('setting IPMI credentials was not requested')
        return

    user, password = resp['ipmi_username'], resp['ipmi_password']
    LOG.debug('setting IPMI credentials: user %s', user)

    commands = [
        ('user', 'set', 'name', '2', user),
        ('user', 'set', 'password', '2', password),
        ('user', 'enable', '2'),
        ('channel', 'setaccess', '1', '2',
         'link=on', 'ipmi=on', 'callin=on', 'privilege=4'),
    ]

    for cmd in commands:
        try:
            utils.execute('ipmitool', *cmd)
        except processutils.ProcessExecutionError:
            LOG.exception('failed to update IPMI credentials')
            raise errors.InspectionError('failed to update IPMI credentials')

    LOG.info('successfully set IPMI credentials: user %s', user)


def discover_network_properties(inventory, data, failures):
    """Discover network and BMC related properties.

    This logic should eventually move to inspector itself.

    :param inventory: hardware inventory from a hardware manager
    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    data.setdefault('interfaces', {})
    for iface in inventory['interfaces']:
        is_loopback = (iface.ipv4_address and
                       netaddr.IPAddress(iface.ipv4_address).is_loopback())
        if iface.name == 'lo' or is_loopback:
            LOG.debug('ignoring local network interface %s', iface.name)
            continue

        LOG.debug('found network interface %s', iface.name)

        if not iface.mac_address:
            LOG.debug('no link information for interface %s', iface.name)
            continue

        if not iface.ipv4_address:
            LOG.debug('no IP address for interface %s', iface.name)

        data['interfaces'][iface.name] = {'mac': iface.mac_address,
                                          'ip': iface.ipv4_address}

    if data['interfaces']:
        LOG.info('network interfaces: %s', data['interfaces'])
    else:
        failures.add('no network interfaces found')


def discover_scheduling_properties(inventory, data, root_disk=None):
    """Discover properties required for nova scheduler.

    This logic should eventually move to inspector itself.

    :param inventory: hardware inventory from a hardware manager
    :param data: mutable data that we'll send to inspector
    :param root_disk: root device (if it can be detected)
    """
    data['cpus'] = inventory['cpu'].count
    data['cpu_arch'] = inventory['cpu'].architecture
    data['memory_mb'] = inventory['memory'].physical_mb
    if root_disk is not None:
        # -1 is required to give Ironic some spacing for partitioning
        data['local_gb'] = root_disk.size / units.Gi - 1

    for key in ('cpus', 'local_gb', 'memory_mb'):
        try:
            data[key] = int(data[key])
        except (KeyError, ValueError, TypeError):
            LOG.warn('value for %s is missing or malformed: %s',
                     key, data.get(key))
        else:
            LOG.info('value for %s is %s', key, data[key])


def collect_default(data, failures):
    """The default inspection collector.

    This is the only collector that is called by default. It is designed to be
    both backward and future compatible:
        1. it collects exactly the same data as the old bash-based ramdisk
        2. it also posts the whole inventory which we'll eventually use.

    In both cases it tries to get BMC address, PXE boot device and the expected
    root device.

    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    inventory = hardware.dispatch_to_managers('list_hardware_info')

    # In the future we will only need the current version of inventory,
    # a guessed root disk, PXE boot interface and IPMI address.
    # Everything else will be done by inspector itself and its plugins.
    data['inventory'] = inventory
    # Replicate the same logic as in deploy. We need to make sure that when
    # root device hints are not set, inspector will use the same root disk as
    # will be used for deploy.
    try:
        root_disk = utils.guess_root_disk(inventory['disks'][:])
    except errors.DeviceNotFound:
        root_disk = None
        LOG.warn('no suitable root device detected')
    else:
        data['root_disk'] = root_disk
        LOG.debug('default root device is %s', root_disk.name)
    # Both boot interface and IPMI address might not be present,
    # we don't count it as failure
    data['boot_interface'] = utils.get_agent_params().get('BOOTIF')
    LOG.debug('boot devices was %s', data['boot_interface'])
    data['ipmi_address'] = inventory.get('bmc_address')
    LOG.debug('BMC IP address: %s', data['ipmi_address'])

    # These 2 calls are required for backward compatibility and should be
    # dropped after inspector is ready (probably in Mitaka cycle).
    discover_network_properties(inventory, data, failures)
    discover_scheduling_properties(inventory, data, root_disk)


def collect_logs(data, failures):
    """Collect journald logs from the ramdisk.

    As inspection runs before any nodes details are known, it's handy to have
    logs returned with data. This collector sends logs to inspector in format
    expected by the 'ramdisk_error' plugin: base64 encoded tar.gz.

    This collector should be installed last in the collector chain, otherwise
    it won't collect enough logs.

    This collector does not report failures.

    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    try:
        out, _e = utils.execute('journalctl', '--full', '--no-pager', '-b',
                                '-n', '10000', binary=True)
    except (processutils.ProcessExecutionError, OSError):
        LOG.warn('failed to get system journal')
        return

    journal = io.BytesIO(bytes(out))
    with io.BytesIO() as fp:
        with tarfile.open(fileobj=fp, mode='w:gz') as tar:
            tarinfo = tarfile.TarInfo('journal')
            tarinfo.size = len(out)
            tar.addfile(tarinfo, journal)

        fp.seek(0)
        data['logs'] = base64.b64encode(fp.getvalue())


def collect_extra_hardware(data, failures):
    """Collect detailed inventory using 'hardware-detect' utility.

    Recognizes ipa-inspection-benchmarks with list of benchmarks (possible
    values are cpu, disk, mem) to run. No benchmarks are run by default, as
    they're pretty time-consuming.

    Puts collected data as JSON under 'data' key.
    Requires 'hardware' python package to be installed on the ramdisk in
    addition to the packages in requirements.txt.

    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    benchmarks = utils.get_agent_params().get('ipa-inspection-benchmarks', [])
    if benchmarks:
        benchmarks = ['--benchmark'] + benchmarks.split(',')

    try:
        out, err = utils.execute('hardware-detect', *benchmarks)
    except (processutils.ProcessExecutionError, OSError) as exc:
        failures.add('failed to run hardware-detect utility: %s', exc)
        return

    try:
        data['data'] = json.loads(out)
    except ValueError as exc:
        msg = 'JSON returned from hardware-detect cannot be decoded: %s'
        failures.add(msg, exc)

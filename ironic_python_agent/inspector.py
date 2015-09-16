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

import logging

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

    Populates 'boot_interface', 'ipmi_address' and 'interfaces' keys.

    :param inventory: hardware inventory from a hardware manager
    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    # Both boot interface and IPMI address might not be present,
    # we don't count it as failure
    data['boot_interface'] = utils.get_agent_params().get('BOOTIF')
    LOG.info('boot devices was %s', data['boot_interface'])
    data['ipmi_address'] = inventory.get('bmc_address')
    LOG.info('BMC IP address: %s', data['ipmi_address'])

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


def discover_scheduling_properties(inventory, data):
    """Discover properties required for nova scheduler.

    This logic should eventually move to inspector itself.

    :param inventory: hardware inventory from a hardware manager
    :param data: mutable data that we'll send to inspector
    """
    data['cpus'] = inventory['cpu'].count
    data['cpu_arch'] = inventory['cpu'].architecture
    data['memory_mb'] = inventory['memory'].physical_mb

    # Replicate the same logic as in deploy. This logic will be moved to
    # inspector itself, but we need it for backward compatibility.
    try:
        disk = utils.guess_root_disk(inventory['disks'])
    except errors.DeviceNotFound:
        LOG.warn('no suitable root device detected')
    else:
        # -1 is required to give Ironic some spacing for partitioning
        data['local_gb'] = disk.size / units.Gi - 1

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

    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    inventory = hardware.dispatch_to_managers('list_hardware_info')
    # These 2 calls are required for backward compatibility and should be
    # dropped after inspector is ready (probably in Mitaka cycle).
    discover_network_properties(inventory, data, failures)
    discover_scheduling_properties(inventory, data)
    # In the future we will only need the current version of inventory,
    # everything else will be done by inspector itself and its plugins
    data['inventory'] = inventory

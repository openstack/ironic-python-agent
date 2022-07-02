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

import json
import os
import time

from ironic_lib import mdns
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
import requests
import stevedore
import tenacity

from ironic_python_agent import config
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import utils


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

_DHCP_RETRY_INTERVAL = 2
_COLLECTOR_NS = 'ironic_python_agent.inspector.collectors'
_NO_LOGGING_FIELDS = ('logs',)


def _extension_manager_err_callback(names):
    raise errors.InspectionError('Failed to load collector %s' % names)


def extension_manager(names):
    return stevedore.NamedExtensionManager(
        _COLLECTOR_NS, names=names, name_order=True,
        on_missing_entrypoints_callback=_extension_manager_err_callback)


def _get_collector_names():
    return [x.strip() for x in CONF.inspection_collectors.split(',')
            if x.strip()]


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

    if CONF.inspection_callback_url == 'mdns':
        LOG.debug('Fetching the inspection URL from mDNS')
        url, params = mdns.get_endpoint('baremetal-introspection')
        # We expect a proper catalog URL, which doesn't include any path.
        CONF.set_override('inspection_callback_url',
                          url.rstrip('/') + '/v1/continue')
        config.override(params)

    collector_names = _get_collector_names()
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
        raise errors.InspectionError('stopping inspection, as inspector '
                                     'returned an error')

    LOG.info('inspection finished successfully')
    return resp.get('uuid')


_RETRY_WAIT = 5
_RETRY_ATTEMPTS = 5


def call_inspector(data, failures):
    """Post data to inspector."""
    data['error'] = failures.get_error()

    LOG.info('posting collected data to %s', CONF.inspection_callback_url)
    LOG.debug('collected data: %s',
              {k: v for k, v in data.items() if k not in _NO_LOGGING_FIELDS})

    encoder = encoding.RESTJSONEncoder()
    data = encoder.encode(data)
    verify, cert = utils.get_ssl_client_options(CONF)

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            requests.exceptions.ConnectionError),
        stop=tenacity.stop_after_attempt(_RETRY_ATTEMPTS),
        wait=tenacity.wait_fixed(_RETRY_WAIT),
        reraise=True)
    def _post_to_inspector():
        return requests.post(CONF.inspection_callback_url, data=data,
                             verify=verify, cert=cert)

    resp = _post_to_inspector()
    if resp.status_code >= 400:
        LOG.error('inspector %s error %d: %s, proceeding with lookup',
                  CONF.inspection_callback_url,
                  resp.status_code, resp.content.decode('utf-8'))
        return

    return resp.json()


def _normalize_mac(mac):
    """Convert MAC to a well-known format aa:bb:cc:dd:ee:ff."""
    if '-' in mac:
        # pxelinux format is 01-aa-bb-cc-dd-ee-ff
        mac = mac.split('-', 1)[1]
        mac = mac.replace('-', ':')
    return mac.lower()


def wait_for_dhcp():
    """Wait until NIC's get their IP addresses via DHCP or timeout happens.

    Depending on the value of inspection_dhcp_all_interfaces configuration
    option will wait for either all or only PXE booting NIC.

    Note: only supports IPv4 addresses for now.

    :return: True if all NIC's got IP addresses, False if timeout happened.
             Also returns True if waiting is disabled via configuration.
    """
    if not CONF.inspection_dhcp_wait_timeout:
        return True

    pxe_mac = utils.get_agent_params().get('BOOTIF')
    if pxe_mac:
        pxe_mac = _normalize_mac(pxe_mac)
    elif not CONF.inspection_dhcp_all_interfaces:
        LOG.warning('No PXE boot interface known - not waiting for it '
                    'to get the IP address')
        return False

    threshold = time.time() + CONF.inspection_dhcp_wait_timeout
    while time.time() <= threshold:
        interfaces = hardware.dispatch_to_managers('list_network_interfaces')
        interfaces = [iface for iface in interfaces
                      if CONF.inspection_dhcp_all_interfaces
                      or iface.mac_address.lower() == pxe_mac]
        missing = [iface.name for iface in interfaces
                   if not iface.ipv4_address]
        if not missing:
            return True

        LOG.debug('Still waiting for interfaces %s to get IP addresses',
                  missing)
        time.sleep(_DHCP_RETRY_INTERVAL)

    LOG.warning('Not all network interfaces received IP addresses in '
                '%(timeout)d seconds: %(missing)s',
                {'timeout': CONF.inspection_dhcp_wait_timeout,
                 'missing': missing})
    return False


def collect_default(data, failures):
    """The default inspection collector.

    This is the only collector that is called by default. It collects
    the whole inventory as returned by the hardware manager(s).

    It also tries to get BMC address, PXE boot device and the expected
    root device.

    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    wait_for_dhcp()
    inventory = hardware.list_hardware_info()

    data['inventory'] = inventory
    # Replicate the same logic as in deploy. We need to make sure that when
    # root device hints are not set, inspector will use the same root disk as
    # will be used for deploy.
    try:
        root_disk = utils.guess_root_disk(inventory['disks'][:])
    except errors.DeviceNotFound:
        root_disk = None
        LOG.warning('no suitable root device detected')
    else:
        data['root_disk'] = root_disk
        LOG.debug('default root device is %s', root_disk.name)
    # The boot interface might not be present, we don't count it as failure.
    # TODO(dtantsur): stop using the boot_interface field.
    data['boot_interface'] = inventory['boot'].pxe_interface
    LOG.debug('boot devices was %s', data['boot_interface'])
    LOG.debug('BMC IP address: %s', inventory.get('bmc_address'))
    data['configuration'] = {
        'collectors': _get_collector_names(),
        'managers': [mgr.get_version() for mgr in hardware.get_managers()],
    }


def collect_logs(data, failures):
    """Collect system logs from the ramdisk.

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
        data['logs'] = utils.collect_system_logs(journald_max_lines=10000)
    except errors.CommandExecutionError:
        LOG.warning('failed to get system journal')
        return


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
    except json.decoder.JSONDecodeError as ex:
        msg = 'JSON returned from hardware-detect cannot be decoded: %s'
        failures.add(msg, ex)


def collect_pci_devices_info(data, failures):
    """Collect a list of PCI devices.

    Each PCI device entry in list is a dictionary containing vendor_id and
    product_id keys, which will be then used by the ironic inspector to
    distinguish various PCI devices.

    The data is gathered from /sys/bus/pci/devices directory.

    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    pci_devices_path = '/sys/bus/pci/devices'
    pci_devices_info = []
    try:
        subdirs = os.listdir(pci_devices_path)
    except OSError as exc:
        msg = 'Failed to get list of PCI devices: %s'
        failures.add(msg, exc)
        return
    for subdir in subdirs:
        if not os.path.isdir(os.path.join(pci_devices_path, subdir)):
            continue
        try:
            # note(sborkows): ids located in files inside PCI devices
            # directory are stored in hex format (0x1234 for example) and
            # we only need that part after 'x' delimiter
            with open(os.path.join(pci_devices_path, subdir,
                                   'vendor')) as vendor_file:
                vendor = vendor_file.read().strip().split('x')[1]
            with open(os.path.join(pci_devices_path, subdir,
                                   'device')) as vendor_device:
                device = vendor_device.read().strip().split('x')[1]
            with open(os.path.join(pci_devices_path, subdir,
                                   'class')) as vendor_device:
                pci_class = vendor_device.read().strip().split('x')[1]
        except IOError as exc:
            LOG.warning('Failed to gather vendor id, product id or pci class '
                        'from PCI device %s: %s', subdir, exc)
            continue
        except IndexError as exc:
            LOG.warning('Wrong format of vendor id, product id or pci class '
                        'in PCI device %s: %s', subdir, exc)
            continue

        pci_revision = None
        pci_revision_path = os.path.join(pci_devices_path, subdir,
                                         'revision')
        if os.path.isfile(pci_revision_path):
            try:
                with open(pci_revision_path) as revision_file:
                    pci_revision = revision_file.read().strip().split('x')[1]
            except IOError as exc:
                LOG.warning('Failed to gather PCI revision from PCI '
                            'device %s: %s', subdir, exc)
            except IndexError as exc:
                LOG.warning('Wrong format of PCI revision in PCI '
                            'device %s: %s', subdir, exc)

        LOG.debug(
            'Found a PCI device with vendor id %s, product id %s, class %s '
            'and revision %s', vendor, device, pci_class, pci_revision)
        pci_devices_info.append({'vendor_id': vendor,
                                 'product_id': device,
                                 'class': pci_class,
                                 'revision': pci_revision,
                                 'bus': subdir})
    data['pci_devices'] = pci_devices_info

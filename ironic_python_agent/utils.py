# Copyright 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import abc
import contextlib
import copy
import errno
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

from ironic_lib import disk_utils
from ironic_lib import utils as ironic_utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_utils import units
import requests
import tenacity

from ironic_python_agent import errors

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

# Agent parameters can be passed by kernel command-line arguments and/or
# by virtual media. Virtual media parameters passed would be available
# when the agent is started, but might not be available for re-reading
# later on because:
# * Virtual media might be exposed from Swift and swift temp url might
#   expire.
# * Ironic might have removed the floppy image from Swift after starting
#   the deploy.
#
# Even if it's available, there is no need to re-read from the device and
# /proc/cmdline again, because it is never going to change.  So we cache the
# agent parameters that was passed (by proc/cmdline and/or virtual media)
# when we read it for the first time, and then use this cache.
AGENT_PARAMS_CACHED = dict()


LSBLK_COLUMNS = ['KNAME', 'MODEL', 'SIZE', 'ROTA', 'TYPE', 'UUID', 'PARTUUID']


COLLECT_LOGS_COMMANDS = {
    'ps': ['ps', 'au'],
    'df': ['df', '-a'],
    'iptables': ['iptables', '-L'],
    'ip_addr': ['ip', 'addr'],
    'lshw': ['lshw', '-quiet', '-json'],
    'lsblk': ['lsblk', '--all', '-o%s' % ','.join(LSBLK_COLUMNS)],
    'mdstat': ['cat', '/proc/mdstat'],
}


DEVICE_EXTRACTOR = re.compile(r'^(?:(.*\d)p|(.*\D))(?:\d+)$')

PARTED_TABLE_TYPE_REGEX = re.compile(r'^.*partition\s+table\s*:\s*(gpt|msdos)',
                                     re.IGNORECASE)

_EARLY_LOG_BUFFER = []


def execute(*cmd, **kwargs):
    """Convenience wrapper around ironic_lib's execute() method.

    Executes and logs results from a system command.
    """
    return ironic_utils.execute(*cmd, **kwargs)


def _read_params_from_file(filepath):
    """Extract key=value pairs from a file.

    :param filepath: path to a file containing key=value pairs separated by
                     whitespace or newlines.
    :returns: a dictionary representing the content of the file
    """
    with open(filepath) as f:
        cmdline = f.read()

    options = cmdline.split()
    params = {}
    for option in options:
        if '=' not in option:
            continue
        k, v = option.split('=', 1)
        params[k] = v

    return params


def _get_vmedia_device():
    """Finds the device filename of the virtual media device using sysfs.

    :returns: a string containing the filename of the virtual media device
    """
    sysfs_device_models = glob.glob("/sys/class/block/*/device/model")
    vmedia_device_model = "virtual media"
    for model_file in sysfs_device_models:
        try:
            with open(model_file) as model_file_fobj:
                if vmedia_device_model in model_file_fobj.read().lower():
                    vmedia_device = model_file.split('/')[4]
                    return vmedia_device
        except Exception:
            pass


def _find_vmedia_device_by_labels(labels):
    """Find device matching any of the provided labels for virtual media"""
    candidates = []
    try:
        lsblk_output, _e = execute('lsblk', '-p', '-P', '-oKNAME,LABEL')
    except processutils.ProcessExecutionError as e:
        _early_log('Was unable to execute the lsblk command. %s', e)
        return

    for device in ironic_utils.parse_device_tags(lsblk_output):
        for label in labels:
            if label.upper() == device['LABEL'].upper():
                candidates.append(device['KNAME'])

    for candidate in candidates:
        # We explicitly take the device and run it past _check_vmedia_device
        # as there *can* be candidate entries, and we only want to return
        # one that seems most likely to be the actual device, and the vmedia
        # check code also evaluates the device overall, instead of just the
        # block device with a label of some sort.
        if _check_vmedia_device(candidate):
            return candidate
        else:
            _early_log('Found possible vmedia candidate %s, however '
                       'the device failed vmedia validity checking.',
                       candidate)
    _early_log('Did not identify any virtual media candidates devices.')


def _get_vmedia_params():
    """This method returns the parameters passed through virtual media floppy.

    :returns: a partial dict of potential agent configuration parameters
    :raises: VirtualMediaBootError when it cannot find the virtual media device
    """
    parameters_file = "parameters.txt"
    vmedia_device_file = _find_vmedia_device_by_labels(['ir-vfd-dev'])
    if not vmedia_device_file:
        # This falls back to trying to find a matching device by name/type.
        # if not found, it is likely okay to just fail out and treat it as
        # No device found as there are multiple ways to launch IPA, and all
        # vmedia styles should be treated consistently.
        vmedia_device = _get_vmedia_device()
        if not vmedia_device:
            return {}

        vmedia_device_file = os.path.join("/dev", vmedia_device)

        if not _check_vmedia_device(vmedia_device_file):
            # If the device is not valid, return an empty dictionary.
            return {}

    with ironic_utils.mounted(vmedia_device_file) as vmedia_mount_point:
        parameters_file_path = os.path.join(vmedia_mount_point,
                                            parameters_file)
        params = _read_params_from_file(parameters_file_path)

    return params


def _early_log(msg, *args):
    """Log via printing (before oslo.log is configured)."""
    log_entry = msg % args
    _EARLY_LOG_BUFFER.append(log_entry)
    print('ironic-python-agent:', log_entry, file=sys.stderr)


def log_early_log_to_logger():
    """Logs early logging events to the configured logger."""

    for entry in _EARLY_LOG_BUFFER:
        LOG.info("Early logging: %s", entry)


def _copy_config_from(path):
    for ext in ('', '.d'):
        src = os.path.join(path, 'etc', 'ironic-python-agent%s' % ext)
        if not os.path.isdir(src):
            _early_log('%s not found', src)
            continue

        dest = '/etc/ironic-python-agent%s' % ext
        _early_log('Copying configuration from %s to %s', src, dest)
        try:
            os.makedirs(dest, exist_ok=True)

            # TODO(dtantsur): use shutil.copytree(.., dirs_exist_ok=True)
            # when the minimum supported Python is 3.8.
            for name in os.listdir(src):
                src_file = os.path.join(src, name)
                dst_file = os.path.join(dest, name)
                shutil.copy(src_file, dst_file)
        except Exception as exc:
            msg = ("Unable to copy vmedia configuration %s to %s: %s"
                   % (src, dest, exc))
            raise errors.VirtualMediaBootError(msg)


def _find_mount_point(device):
    try:
        path, _e = execute('findmnt', '-n', '-oTARGET', device)
    except processutils.ProcessExecutionError:
        return
    else:
        return path.strip()


def _check_vmedia_device(vmedia_device_file):
    """Check if a virtual media device appears valid.

    Explicitly ignores partitions, actual disks, and other itmes that
    seem unlikely to be virtual media based items being provided
    into the running operating system via a BMC.

    :param vmedia_device_file: Path to the device to examine.
    :returns: False by default, True if the device appears to be
              valid.
    """
    try:
        output, _e = execute('lsblk', '-n', '-s', '-P', '-b',
                             '-oKNAME,TRAN,TYPE,SIZE',
                             vmedia_device_file)
    except processutils.ProcessExecutionError as e:
        _early_log('Failed to execute lsblk. lsblk is required for '
                   'virtual media identification. %s', e)
        return False
    try:
        for device in ironic_utils.parse_device_tags(output):
            if device['TYPE'] == 'part':
                _early_log('Excluding device %s from virtual media'
                           'consideration as it is a partition.',
                           device['KNAME'])
                return False
            if device['TYPE'] == 'rom':
                # Media is a something like /dev/sr0, a Read only media type.
                # The kernel decides this by consulting the underlying type
                # registered for the scsi transport and thus type used.
                # This will most likely be a qemu driven testing VM,
                # or an older machine where SCSI transport is directly
                # used to convey in a virtual
                return True
            if device['TYPE'] == 'disk' and device['TRAN'] == 'usb':
                # We know from experience on HPE machines, with ilo4/5, we see
                # and redfish with edgeline gear, return attachment from
                # pci device 0c-03.
                # https://linux-hardware.org/?probe=4d2526e9f4
                # https://linux-hardware.org/?id=pci:103c-22f6-1590-00e4
                #
                # Dell hardware takes a similar approach, using an Aten usb hub
                # which provides the standing connection for the BMC attached
                # virtual kvm.
                # https://linux-hardware.org/?id=usb:0557-8021
                #
                # Supermicro also uses Aten on X11, X10, X8
                # https://linux-hardware.org/?probe=4d0ed95e02
                #
                # Lenovo appears in some hardware to use an Emulux Pilot4
                # integrated hub to proivide device access on some hardware.
                # https://linux-hardware.org/index.php?id=usb:2a4b-0400
                #
                # ??? but the virtual devices appear to be American Megatrends
                # https://linux-hardware.org/?probe=076bcef32e
                #
                # Fujitsu hardware is more uncertian, but appears to be similar
                # in use of a USB pass-through
                # http://linux-hardware.org/index.php?probe=cca9eab7fe&log=dmesg
                if device['SIZE'] != "" and int(device['SIZE']) < 4294967296:
                    # Device is a usb backed block device which is smaller
                    # than 4 GiB
                    return True
                else:
                    _early_log('Device %s appears to not qualify as virtual '
                               'due to the device size. Size: %s',
                               device['KNAME'], device['SIZE'])
            _early_log('Device %s was disqualified as virtual media. '
                       'Type: %s, Transport: %s',
                       device['KNAME'], device['TYPE'], device['TRAN'])
        return False
    except KeyError:
        return False


def _booted_from_vmedia():
    """Indicates if the machine was booted via vmedia."""
    params = _read_params_from_file('/proc/cmdline')
    return params.get('boot_method') == 'vmedia'


def copy_config_from_vmedia():
    """Copies any configuration from a virtual media device.

    Copies files under /etc/ironic-python-agent and /etc/ironic-python-agent.d.
    """
    vmedia_device_file = _find_vmedia_device_by_labels(
        ['config-2', 'vmedia_boot_iso'])
    if not vmedia_device_file:
        _early_log('No virtual media device detected')
        return
    if not _booted_from_vmedia():
        _early_log('Cannot use configuration from virtual media as the '
                   'agent was not booted from virtual media.')
        return
    # Determine the device
    mounted = _find_mount_point(vmedia_device_file)
    if mounted:
        _copy_config_from(mounted)
    else:
        with ironic_utils.mounted(vmedia_device_file) as vmedia_mount_point:
            _copy_config_from(vmedia_mount_point)


def _get_cached_params():
    """Helper method to get cached params to ease unit testing."""
    return AGENT_PARAMS_CACHED


def _set_cached_params(params):
    """Helper method to set cached params to ease unit testing."""
    global AGENT_PARAMS_CACHED
    AGENT_PARAMS_CACHED = params


def get_agent_params():
    """Gets parameters passed to the agent via kernel cmdline or vmedia.

    Parameters can be passed using either the kernel commandline or through
    virtual media. If boot_method is vmedia, merge params provided via vmedia
    with those read from the kernel command line.

    Although it should never happen, if a variable is both set by vmedia and
    kernel command line, the setting in vmedia will take precedence.

    :returns: a dict of potential configuration parameters for the agent
    """

    # Check if we have the parameters cached
    params = _get_cached_params()
    if not params:
        params = _read_params_from_file('/proc/cmdline')

        # If the node booted over virtual media, the parameters are passed
        # in a text file within the virtual media floppy.
        if params.get('boot_method') == 'vmedia':
            vmedia_params = _get_vmedia_params()
            params.update(vmedia_params)

        # Cache the parameters so that it can be used later on.
        _set_cached_params(params)

    return copy.deepcopy(params)


class AccumulatedFailures(object):
    """Object to accumulate failures without raising exception."""

    def __init__(self, exc_class=RuntimeError):
        self._failures = []
        self._exc_class = exc_class

    def add(self, fail, *fmt):
        """Add failure with optional formatting.

        :param fail: exception or error string
        :param fmt: formatting arguments (only if fail is a string)
        """
        if fmt:
            fail = fail % fmt
        LOG.error('%s', fail)
        self._failures.append(fail)

    def get_error(self):
        """Get error string or None."""
        if not self._failures:
            return

        msg = ('The following errors were encountered:\n%s'
               % '\n'.join('* %s' % item for item in self._failures))
        return msg

    def raise_if_needed(self):
        """Raise exception if error list is not empty.

        :raises: RuntimeError
        """
        if self._failures:
            raise self._exc_class(self.get_error())

    def __nonzero__(self):
        return bool(self._failures)

    __bool__ = __nonzero__

    def __repr__(self):  # pragma: no cover
        # This is for tests
        if self:
            return '<%s: %s>' % (self.__class__.__name__,
                                 ', '.join(self._failures))
        else:
            return '<%s: success>' % self.__class__.__name__


def guess_root_disk(block_devices, min_size_required=4 * units.Gi):
    """Find suitable disk provided that root device hints are not given.

    If no hints are passed, order the devices by size (primary key) and
    name (secondary key), and return the first device larger than
    min_size_required as the root disk.
    """
    # NOTE(arne_wiebalck): Order devices by size and name. Secondary
    # ordering by name is done to increase chances of successful
    # booting for BIOSes which try only one (the "first") disk.
    block_devices.sort(key=lambda device: (device.size, device.name))

    if not block_devices or block_devices[-1].size < min_size_required:
        raise errors.DeviceNotFound(
            "No suitable device was found "
            "for deployment - root device hints were not provided "
            "and all found block devices are smaller than %iB."
            % min_size_required)
    for device in block_devices:
        if device.size >= min_size_required:
            return device


def is_journalctl_present():
    """Check if the journalctl command is present.

    :returns: True if journalctl is present, False if not.
    """
    try:
        devnull = open(os.devnull, 'w')
        subprocess.check_call(['journalctl', '--version'], stdout=devnull,
                              stderr=devnull)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return False
    return True


def get_command_output(command):
    """Return the output of a given command.

    :param command: The command to be executed.
    :raises: CommandExecutionError if the execution of the command fails.
    :returns: A BytesIO string with the output.
    """
    try:
        out, _ = execute(*command, binary=True, log_stdout=False)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = ('Failed to get the output of the command "%(command)s". '
                     'Error: %(error)s' % {'command': command, 'error': e})
        raise errors.CommandExecutionError(error_msg)
    return io.BytesIO(out)


def get_journalctl_output(lines=None, units=None):
    """Query the contents of the systemd journal.

    :param lines: Maximum number of lines to retrieve from the
                  logs. If None, return everything.
    :param units: A list with the names of the units we should
                  retrieve the logs from. If None retrieve the logs
                  for everything.
    :returns: A log string.
    """
    cmd = ['journalctl', '--full', '--no-pager', '-b']
    if lines is not None:
        cmd.extend(['-n', str(lines)])
    if units is not None:
        [cmd.extend(['-u', u]) for u in units]

    return get_command_output(cmd)


def gzip_and_b64encode(io_dict=None, file_list=None):
    """Gzip and base64 encode files and BytesIO buffers.

    :param io_dict: A dictionary containing whose the keys are the file
        names and the value a BytesIO object.
    :param file_list: A list of file path.
    :returns: A gzipped and base64 encoded string.
    """
    io_dict = io_dict or {}
    file_list = file_list or []

    with io.BytesIO() as fp:
        with tarfile.open(fileobj=fp, mode='w:gz') as tar:
            for fname in io_dict:
                ioobj = io_dict[fname]
                tarinfo = tarfile.TarInfo(name=fname)
                tarinfo.size = ioobj.seek(0, 2)
                tarinfo.mtime = time.time()
                ioobj.seek(0)
                tar.addfile(tarinfo, ioobj)

            for f in file_list:
                tar.add(f)

        fp.seek(0)
        return base64.encode_as_text(fp.getvalue())


def collect_system_logs(journald_max_lines=None):
    """Collect system logs.

    Collect system logs, for distributions using systemd the logs will
    come from journald. On other distributions the logs will come from
    the /var/log directory and dmesg output.

    :param journald_max_lines: Maximum number of lines to retrieve from
                               the journald. if None, return everything.
    :returns: A tar, gzip base64 encoded string with the logs.
    """
    LOG.info('Collecting system logs and debugging information')

    def try_get_command_output(io_dict, file_name, command):
        try:
            io_dict[file_name] = get_command_output(command)
        except errors.CommandExecutionError:
            LOG.debug('Collecting logs from command %s has failed', command)

    io_dict = {}
    file_list = []
    if is_journalctl_present():
        io_dict['journal'] = get_journalctl_output(lines=journald_max_lines)
    else:
        try_get_command_output(io_dict, 'dmesg', ['dmesg'])
        file_list.append('/var/log')

    for name, cmd in COLLECT_LOGS_COMMANDS.items():
        try_get_command_output(io_dict, name, cmd)

    return gzip_and_b64encode(io_dict=io_dict, file_list=file_list)


def get_ssl_client_options(conf):
    """Format SSL-related requests options.

    :param conf: oslo_config CONF object
    :returns: tuple of 'verify' and 'cert' values to pass to requests
    """
    if conf.insecure:
        verify = False
    else:
        verify = conf.cafile or True
    if conf.certfile and conf.keyfile:
        cert = (conf.certfile, conf.keyfile)
    else:
        cert = None
    return verify, cert


def extract_device(part):
    """Extract the device from a partition name or path.

    :param part: the partition
    :return: a device if success, None otherwise
    """

    m = DEVICE_EXTRACTOR.match(part)
    if not m:
        return None
    return (m.group(1) or m.group(2))


# See ironic.drivers.utils.get_node_capability
def _parse_capabilities_str(cap_str):
    """Extract capabilities from string.

    :param cap_str: string meant to meet key1:value1,key2:value2 format
    :return: a dictionnary
    """
    LOG.debug("Parsing capability string %s", cap_str)
    capabilities = {}

    for node_capability in cap_str.split(','):
        parts = node_capability.split(':')
        if len(parts) == 2 and parts[0] and parts[1]:
            capabilities[parts[0]] = parts[1]
        else:
            LOG.warning("Ignoring malformed capability '%s'. "
                        "Format should be 'key:val'.", node_capability)

    LOG.debug("Parsed capabilities %s", capabilities)

    return capabilities


# See ironic.common.utils.parse_instance_info_capabilities. Same except that
# we do not handle node.properties.capabilities and
# node.instance_info.capabilities differently
def parse_capabilities(root):
    """Extract capabilities from provided root dictionary-behaving object.

    root.get('capabilities', {}) value can either be a dict, or a json str, or
    a key1:value1,key2:value2 formatted string.

    :param root: Anything behaving like a dict and containing capabilities
                 formatted as expected. Can be node.get('properties', {}),
                 node.get('instance_info', {}).
    :returns: A dictionary with the capabilities if found and well formatted,
              otherwise an empty dictionary.
    """

    capabilities = root.get('capabilities', {})
    if isinstance(capabilities, str):
        try:
            capabilities = jsonutils.loads(capabilities)
        except (ValueError, TypeError):
            capabilities = _parse_capabilities_str(capabilities)

    if not isinstance(capabilities, dict):
        LOG.warning("Invalid capabilities %s", capabilities)
        return {}

    return capabilities


def _is_secure_boot(instance_info_caps, node_caps):
    """Extract node secure boot property"""
    return 'true' == str(instance_info_caps.get(
        'secure_boot', node_caps.get('secure_boot', 'false'))).lower()


# TODO(rg): This method should be mutualized with the one found in
# ironic.drivers.modules.boot_mode_utils.
# The only difference here:
# 1. node is a dict, not an ironic.objects.node
# 2. implicit bios boot mode when using trusted boot capability is removed:
# there is no reason why trusted_boot should imply bios boot mode.
def get_node_boot_mode(node):
    """Returns the node boot mode.

    It returns 'uefi' if 'secure_boot' is set to 'true' in
    'instance_info/capabilities' of node. Otherwise it directly look for boot
    mode hints into

    :param node: dictionnary.
    :returns: 'bios' or 'uefi'
    """
    instance_info = node.get('instance_info', {})
    instance_info_caps = parse_capabilities(instance_info)
    node_caps = parse_capabilities(node.get('properties', {}))

    if _is_secure_boot(instance_info_caps, node_caps):
        LOG.debug('Deploy boot mode is implicitely uefi for because secure '
                  'boot is activated.')
        return 'uefi'

    ramdisk_boot_mode = 'uefi' if os.path.isdir('/sys/firmware/efi') \
        else 'bios'

    # Priority order implemented in ironic
    boot_mode = instance_info.get(
        'deploy_boot_mode',
        node_caps.get(
            'boot_mode',
            node.get('driver_internal_info', {}).get('deploy_boot_mode',
                                                     ramdisk_boot_mode))
    )

    boot_mode = str(boot_mode).lower()
    if boot_mode not in ['uefi', 'bios']:
        boot_mode = ramdisk_boot_mode

    LOG.debug('Deploy boot mode: %s', boot_mode)

    return boot_mode


def get_partition_table_type_from_specs(node):
    """Returns the node partition label, gpt or msdos.

    If boot mode is uefi, return gpt. Else, choice is open, look for
    disk_label capabilities (instance_info has priority over properties).

    :param node:
    :return: gpt or msdos
    """
    instance_info_caps = parse_capabilities(node.get('instance_info', {}))
    node_caps = parse_capabilities(node.get('properties', {}))

    # Let's not make things more complicated than they already are.
    # We currently just ignore the specified disk label in case of uefi,
    # and force gpt, even if msdos is possible. Small amends needed if ever
    # needed (doubt that)

    boot_mode = get_node_boot_mode(node)
    if boot_mode == 'uefi':
        return 'gpt'

    disk_label = instance_info_caps.get(
        'disk_label',
        node_caps.get('disk_label', 'msdos')
    )
    return 'gpt' if disk_label == 'gpt' else 'msdos'


def scan_partition_table_type(device):
    """Get partition table type, msdos or gpt.

    :param device_name: the name of the device
    :return: msdos, gpt or unknown
    """
    out, _u = execute('parted', '-s', device, '--', 'print')
    out = out.splitlines()

    for line in out:
        m = PARTED_TABLE_TYPE_REGEX.match(line)
        if m:
            return m.group(1)

    LOG.warning("Unable to get partition table type for device %s.",
                device)

    return 'unknown'


def get_efi_part_on_device(device):
    """Looks for the efi partition on a given device.

    A boot partition on a GPT disk is assumed to be an EFI partition as well.

    :param device: lock device upon which to check for the efi partition
    :return: the efi partition or None
    """
    is_gpt = scan_partition_table_type(device) == 'gpt'
    for part in disk_utils.list_partitions(device):
        flags = {x.strip() for x in part['flags'].split(',')}
        if 'esp' in flags or ('boot' in flags and is_gpt):
            LOG.debug("Found EFI partition %s on device %s.", part, device)
            return part['number']
    else:
        LOG.debug("No efi partition found on device %s", device)


_LARGE_KEYS = frozenset(['configdrive', 'system_logs'])


def remove_large_keys(var):
    """Remove specific keys from the var, recursing into dicts and lists."""
    if isinstance(var, abc.Mapping):
        return {key: (remove_large_keys(value)
                      if key not in _LARGE_KEYS else '<...>')
                for key, value in var.items()}
    elif isinstance(var, abc.Sequence) and not isinstance(var, str):
        return var.__class__(map(remove_large_keys, var))
    else:
        return var


def determine_time_method():
    """Helper method to determine what time utility is present.

    :returns: "ntpdate" if ntpdate has been found, "chrony" if chrony
              was located, and None if neither are located. If both tools
              are present, "chrony" will supercede "ntpdate".
    """
    try:
        execute('chronyd', '-h')
        return 'chronyd'
    except OSError:
        LOG.debug('Command \'chronyd\' not found for time sync.')
    try:
        execute('ntpdate', '-v', check_exit_code=[0, 1])
        return 'ntpdate'
    except OSError:
        LOG.debug('Command \'ntpdate\' not found for time sync.')
    return None


def sync_clock(ignore_errors=False):
    """Syncs the software clock of the system.

    This method syncs the system software clock if a NTP server
    was defined in the "[DEFAULT]ntp_server" configuration
    parameter. This method does NOT attempt to sync the hardware
    clock.

    It will try to use either ntpdate or chrony to sync the software
    clock of the system. If neither is found, an exception is raised.

    :param ignore_errors: Boolean value default False that allows for
                          the method to be called and ultimately not
                          raise an exception. This may be useful for
                          opportunistically attempting to sync the
                          system software clock.
    :raises: CommandExecutionError if an error is encountered while
             attempting to sync the software clock.
    """

    if not CONF.ntp_server:
        return

    method = determine_time_method()

    if method == 'ntpdate':
        try:
            execute('ntpdate', CONF.ntp_server)
            LOG.debug('Set software clock using ntpdate')
        except processutils.ProcessExecutionError as e:
            msg = ('Failed to sync with ntp server: '
                   '%s: %s' % (CONF.ntp_server, e))
            LOG.error(msg)
            if CONF.fail_if_clock_not_set or not ignore_errors:
                raise errors.CommandExecutionError(msg)
    elif method == 'chronyd':
        try:
            # stop chronyd, ignore if it ran before or not
            execute('chronyc', 'shutdown', check_exit_code=[0, 1])
            # force a time sync now
            query = "server " + CONF.ntp_server + " iburst"
            execute("chronyd -q \'%s\'" % query, shell=True)
            LOG.debug('Set software clock using chrony')
        except (processutils.ProcessExecutionError,
                errors.CommandExecutionError) as e:
            msg = ('Failed to sync time using chrony to ntp server: '
                   '%s: %s' % (CONF.ntp_server, e))
            LOG.error(msg)
            if CONF.fail_if_clock_not_set or not ignore_errors:
                raise errors.CommandExecutionError(msg)
    else:
        msg = ('Unable to sync clock, available methods of '
               '\'ntpdate\' or \'chrony\' not found.')
        LOG.error(msg)
        if CONF.fail_if_clock_not_set or not ignore_errors:
            raise errors.CommandExecutionError(msg)


def create_partition_table(dev_name, partition_table_type):
    """Create a partition table on a disk using parted.

    :param dev_name: the disk where we want to create the partition table.
    :param partition_table_type: the type of partition table we want to
        create, for example gpt or msdos.
    :raises: CommandExecutionError if an error is encountered while
             attempting to create the partition table.
    """
    LOG.info("Creating partition table on {}".format(
        dev_name))
    try:
        execute('parted', dev_name, '-s', '--',
                'mklabel', partition_table_type)
    except processutils.ProcessExecutionError as e:
        msg = "Failed to create partition table on {}: {}".format(
            dev_name, e)
        raise errors.CommandExecutionError(msg)


class StreamingClient:
    """A wrapper around HTTP client with TLS, streaming and error handling."""

    _CHUNK_SIZE = 1 * units.Mi

    def __init__(self, verify_ca=True):
        if verify_ca:
            self.verify, self.cert = get_ssl_client_options(CONF)
        else:
            self.verify, self.cert = False, None

    @contextlib.contextmanager
    def __call__(self, url):
        """Execute a GET request and start streaming.

        :param url: Target URL.
        :return: A generator yielding chunks of data.
        """
        @tenacity.retry(
            retry=tenacity.retry_if_exception_type(requests.ConnectionError),
            stop=tenacity.stop_after_attempt(
                CONF.image_download_connection_retries + 1),
            wait=tenacity.wait_fixed(
                CONF.image_download_connection_retry_interval),
            reraise=True)
        def _get_with_retries():
            return requests.get(url, verify=self.verify, cert=self.cert,
                                stream=True,
                                timeout=CONF.image_download_connection_timeout)

        try:
            with _get_with_retries() as resp:
                resp.raise_for_status()
                yield resp.iter_content(self._CHUNK_SIZE)
        except requests.RequestException as exc:
            raise errors.CommandExecutionError(
                "Unable to read data from %s: %s" % (url, exc))

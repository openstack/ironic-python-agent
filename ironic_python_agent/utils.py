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
import copy
import errno
import glob
import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time

from ironic_lib import disk_utils
from ironic_lib import utils as ironic_utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_utils import units

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


def execute(*cmd, **kwargs):
    """Convenience wrapper around ironic_lib's execute() method.

    Executes and logs results from a system command.
    """
    return ironic_utils.execute(*cmd, **kwargs)


def try_execute(*cmd, **kwargs):
    """The same as execute but returns None on error.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    Instead of raising an exception on failure, this method simply
    returns None in case of failure.

    :param cmd: positional arguments to pass to processutils.execute()
    :param kwargs: keyword arguments to pass to processutils.execute()
    :raises: UnknownArgumentError on receiving unknown arguments
    :returns: tuple of (stdout, stderr) or None in some error cases
    """
    try:
        return execute(*cmd, **kwargs)
    except (processutils.ProcessExecutionError, OSError) as e:
        LOG.debug('Command failed: %s', e)


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


def _get_vmedia_params():
    """This method returns the parameters passed through virtual media floppy.

    :returns: a partial dict of potential agent configuration parameters
    :raises: VirtualMediaBootError when it cannot find the virtual media device
    """
    parameters_file = "parameters.txt"

    vmedia_device_file_lower_case = "/dev/disk/by-label/ir-vfd-dev"
    vmedia_device_file_upper_case = "/dev/disk/by-label/IR-VFD-DEV"
    if os.path.exists(vmedia_device_file_lower_case):
        vmedia_device_file = vmedia_device_file_lower_case
    elif os.path.exists(vmedia_device_file_upper_case):
        vmedia_device_file = vmedia_device_file_upper_case
    else:

        # TODO(rameshg87): This block of code is there only for compatibility
        # reasons (so that newer agent can work with older Ironic). Remove
        # this after Liberty release.
        vmedia_device = _get_vmedia_device()
        if not vmedia_device:
            msg = "Unable to find virtual media device"
            raise errors.VirtualMediaBootError(msg)

        vmedia_device_file = os.path.join("/dev", vmedia_device)

    vmedia_mount_point = tempfile.mkdtemp()
    try:
        try:
            stdout, stderr = execute("mount", vmedia_device_file,
                                     vmedia_mount_point)
        except processutils.ProcessExecutionError as e:
            msg = ("Unable to mount virtual media device %(device)s: "
                   "%(error)s" % {'device': vmedia_device_file, 'error': e})
            raise errors.VirtualMediaBootError(msg)

        parameters_file_path = os.path.join(vmedia_mount_point,
                                            parameters_file)
        params = _read_params_from_file(parameters_file_path)

        try:
            stdout, stderr = execute("umount", vmedia_mount_point)
        except processutils.ProcessExecutionError:
            pass
    finally:
        try:
            shutil.rmtree(vmedia_mount_point)
        except Exception:
            pass

    return params


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

        # Check to see if any deprecated parameters have been used
        deprecated_params = {'lldp-timeout': 'ipa-lldp-timeout'}
        for old_param, new_param in deprecated_params.items():
            if params.get(old_param) is not None:
                LOG.warning("The parameter '%s' has been deprecated. Please "
                            "use %s instead.", old_param, new_param)

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
        LOG.error(error_msg)
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
            pass

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
            # 0 should be if chronyd started
            # 1 if already running
            execute('chronyd', check_exit_code=[0, 1])
            # NOTE(TheJulia): Once started, chronyd forks and stays in the
            # background as a server service, it will continue to keep the
            # clock in sync.
            try:
                execute('chronyc', 'add', 'server', CONF.ntp_server)
            except processutils.ProcessExecutionError as e:
                if 'Source already present' not in str(e):
                    msg = 'Error occured adding ntp server: %s' % e
                    LOG.error(msg)
                    raise errors.CommandExecutionError(msg)
            # Force the clock to sync now.
            execute('chronyc', 'makestep')
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

#  Copyright 2013 Rackspace, Inc.
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

import abc
import binascii
import collections
import contextlib
import functools
import glob
import io
import ipaddress
import json
from multiprocessing.pool import ThreadPool
import os
import re
import shlex
import shutil
import stat
import string
import time
from typing import List

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
import pint
import psutil
import pyudev
import stevedore
import yaml

from ironic_python_agent import burnin
from ironic_python_agent import device_hints
from ironic_python_agent import disk_utils
from ironic_python_agent import efi_utils
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent.extensions import base as ext_base
from ironic_python_agent import inject_files
from ironic_python_agent import netutils
from ironic_python_agent import raid_utils
from ironic_python_agent import tls_utils
from ironic_python_agent import utils

_global_managers = None
LOG = log.getLogger()
CONF = cfg.CONF

WARN_BIOSDEVNAME_NOT_FOUND = False

UNIT_CONVERTER = pint.UnitRegistry(filename=None)
UNIT_CONVERTER.define('bytes = []')
UNIT_CONVERTER.define('MB = 1048576 bytes')
UNIT_CONVERTER.define('bit_s = []')
UNIT_CONVERTER.define('Mbit_s = 1000000 * bit_s')
UNIT_CONVERTER.define('Gbit_s = 1000 * Mbit_s')
_MEMORY_ID_RE = re.compile(r'^memory(:\d+)?$')
NODE = None
API_CLIENT = None
API_LOOKUP_TIMEOUT = None
API_LOOKUP_INTERVAL = None
SUPPORTED_SOFTWARE_RAID_LEVELS = frozenset(['0', '1', '1+0', '5', '6'])
NVME_CLI_FORMAT_SUPPORTED_FLAG = 0b10
NVME_CLI_CRYPTO_FORMAT_SUPPORTED_FLAG = 0b100

RAID_APPLY_CONFIGURATION_ARGSINFO = {
    "raid_config": {
        "description": "The RAID configuration to apply.",
        "required": True,
    },
    "delete_existing": {
        "description": (
            "Setting this to 'True' indicates to delete existing RAID "
            "configuration prior to creating the new configuration. "
            "Default value is 'True'."
        ),
        "required": False,
    }
}

DEFAULT_CLEAN_UEFI_NVRAM_MATCH_PATTERNS = [
    r'^HD\(',
    r'shim.*\.efi',
    r'grub.*\.efi'
]
DEPLOY_CLEAN_UEFI_NVRAM_ARGSINFO = {
    "match_patterns": {
        "description": (
            "Json blob contains a list of regex patterns where any UEFI "
            "NVRAM entry matching that pattern will be deleted. "
            "Default value is "
            "'[\"{}\"]'".format('", "'.join(
                DEFAULT_CLEAN_UEFI_NVRAM_MATCH_PATTERNS))
        ),
        "required": False,
    }
}

MULTIPATH_ENABLED = None


def _get_device_info(dev, devclass, field):
    """Get the device info according to device class and field."""
    try:
        devname = os.path.basename(dev)
        with open('/sys/class/%s/%s/device/%s' % (devclass, devname, field),
                  'r') as f:
            return f.read().strip()
    except IOError:
        LOG.warning("Can't find field %(field)s for "
                    "device %(dev)s in device class %(class)s",
                    {'field': field, 'dev': dev, 'class': devclass})


def _load_ipmi_modules():
    """Load kernel modules required for IPMI interaction.

    This is required to be called at least once before attempting to use
    ipmitool or related tools.
    """

    ipmi_drivers = ['ipmi_msghandler', 'ipmi_devintf', 'ipmi_si']
    for ipmi_driver in ipmi_drivers:
        try:
            processutils.execute('modprobe', ipmi_driver)
        except (processutils.ProcessExecutionError, OSError):
            LOG.debug("IPMI driver %s not supported or not present",
                      ipmi_driver)


def _load_multipath_modules():
    """Load multipath modules

    This is required to be able to collect multipath information.

    Two separate paths exist, one with a helper utility for Centos/RHEL
    and another which is just load the modules, and trust multipathd
    will do the needful.
    """
    if (os.path.isfile('/usr/sbin/mpathconf')
        and not os.path.isfile('/etc/multipath.conf')):
        # For Centos/Rhel/Etc which uses mpathconf, this does
        # a couple different things, including configuration generation...
        # which is not *really* required.. at least *shouldn't* be.
        # WARNING(TheJulia): This command explicitly replaces local
        # configuration.
        utils.try_execute('/usr/sbin/mpathconf', '--enable',
                          '--find_multipaths', 'yes',
                          '--with_module', 'y',
                          '--with_multipathd', 'y')
    else:
        # Ensure modules are loaded. Configuration is not required
        # and implied based upon compiled in defaults.
        # NOTE(TheJulia): Debian/Ubuntu specifically just document
        # using `multipath -t` output to start a new configuration
        # file, if needed.
        utils.try_execute('modprobe', 'dm_multipath')
        utils.try_execute('modprobe', 'multipath')


def _check_for_iscsi():
    """Connect iSCSI shared connected via iBFT or OF.

    iscsistart -f will print the iBFT or OF info.
    In case such connection exists, we would like to issue
    iscsistart -b to create a session to the target.
    - If no connection is detected we simply return.
    """
    try:
        utils.execute('iscsistart', '-f')
    except (processutils.ProcessExecutionError, EnvironmentError) as e:
        LOG.debug("No iscsi connection detected. Skipping iscsi. "
                  "Error: %s", e)
        return
    try:
        utils.execute('iscsistart', '-b')
    except processutils.ProcessExecutionError as e:
        LOG.warning("Something went wrong executing 'iscsistart -b' "
                    "Error: %s", e)


def _get_md_uuid(raid_device):
    """Get the md UUID of a Software RAID device.

    :param raid_device: A Software RAID block device name.
    :returns: A string containing the UUID of an md device.
    """
    try:
        out, _ = utils.execute('mdadm', '--detail', raid_device,
                               use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        LOG.warning('Could not get the details of %(dev)s: %(err)s',
                    {'dev': raid_device, 'err': e})
        return

    lines = out.splitlines()
    # the first line contains the md device itself
    for line in lines[1:]:
        match = re.search(r'UUID : ([a-f0-9:]+)', line)
        if match:
            return match.group(1)


def _enable_multipath():
    """Initialize multipath IO if possible.

    :returns: True if the multipathd daemon and multipath command to enumerate
              devices was scucessfully able to be called.
    """
    try:
        _load_multipath_modules()
        # This might not work, ideally it *should* already be running...
        # NOTE(TheJulia): Testing locally, a prior running multipathd, the
        # explicit multipathd start just appears to silently exit with a
        # result code of 0.
        # NOTE(rozzix): This could cause an OS error:
        # "process is already running failed to create pid file" depending on
        # the multipathd version in case multipathd is already running.
        # The safest way to start multipathd is to expect OS error in addition
        # to the execution error and handle both as inconsequential.
        utils.try_execute('multipathd')
        # This is mainly to get the system to actually do the needful and
        # identify/enumerate paths by combining what it can detect and what
        # it already knows. This may be useful, and in theory this should be
        # logged in the IPA log should it be needed.
        utils.execute('multipath', '-ll')
    except FileNotFoundError as e:
        LOG.warning('Attempted to determine if multipath tools were present. '
                    'Not detected. Error recorded: %s', e)
        return False
    except (processutils.ProcessExecutionError, OSError) as e:
        LOG.warning('Attempted to invoke multipath utilities, but we '
                    'encountered an error: %s', e)
        return False
    return True


def _get_multipath_parent_device(device):
    """Check and return a multipath device."""
    if not device:
        # if lsblk provides invalid output, this can be None.
        return
    check_device = os.path.join('/dev', str(device))
    try:
        # Explicitly run the check as regardless of if the device is mpath or
        # not, multipath tools when using list always exits with a return
        # code of 0.
        utils.execute('multipath', '-c', check_device)
        # path check with return an exit code of 1 if you send it a multipath
        # device mapper device, like dm-0.
        # NOTE(TheJulia): -ll is supposed to load from all available
        # information, but may not force a rescan. It may be -f if we need
        # that. That being said, it has been about a decade since I was
        # running multipath tools on SAN connected gear, so my memory is
        # definitely fuzzy.
        out, _ = utils.execute('multipath', '-ll', check_device)
    except processutils.ProcessExecutionError as e:
        # FileNotFoundError if the utility does not exist.
        # -1 return code if the device is not valid.
        LOG.debug('Checked device %(dev)s and determined it was '
                  'not a multipath device. %(error)s',
                  {'dev': check_device,
                   'error': e})
        return
    except FileNotFoundError:
        # This should never happen, as MULTIPATH_ENABLED would be False
        # before this occurs.
        LOG.warning('Attempted to check multipathing status, however '
                    'the \'multipath\' binary is missing or not in the '
                    'execution PATH.')
        return
    # Data format:
    # MPATHDEVICENAME dm-0 TYPE,HUMANNAME
    # size=56G features='1 retain_attached_hw_handler' hwhandler='0' wp=rw
    # `-+- policy='service-time 0' prio=1 status=active
    #   `- 0:0:0:0 sda 8:0  active ready running
    # Other format:
    # mpathat (wwid/alias) device_name vendor,product
    try:
        lines = out.splitlines()
        mpath_device_out = lines[0].split(' ')
        for mpath_device in mpath_device_out:
            if mpath_device.startswith("dm"):
                # give back something like dm-0 so we can log it.
                return mpath_device
    except IndexError:
        # We didn't get any command output, so Nope.
        pass


def get_component_devices(raid_device):
    """Get the component devices of a Software RAID device.

    Get the UUID of the md device and scan all other devices
    for the same md UUID.

    :param raid_device: A Software RAID block device name.
    :returns: A list of the component devices.
    """
    if not raid_device:
        return []

    md_uuid = _get_md_uuid(raid_device)
    if not md_uuid:
        return []
    LOG.debug('%(device)s has UUID %(uuid)s',
              {'device': raid_device, 'uuid': md_uuid})

    component_devices = []
    block_devices = list_all_block_devices()
    block_devices.extend(list_all_block_devices(block_type='part',
                                                ignore_raid=True))
    for bdev in block_devices:
        try:
            out, _ = utils.execute('mdadm', '--examine', bdev.name,
                                   use_standard_locale=True)
        except processutils.ProcessExecutionError as e:
            if "No md superblock detected" in str(e):
                # actually not a component device
                LOG.debug('Not a component device %s', bdev.name)
                continue
            else:
                LOG.warning("Failed to examine device %(name)s: %(err)s",
                            {'name': bdev.name, 'err': e})
                continue
        lines = out.splitlines()
        for line in lines:
            if md_uuid in line:
                component_devices.append(bdev.name)

    LOG.info('Found component devices for %s: %s',
             raid_device, component_devices)
    return component_devices


def _calc_memory(sys_dict):
    physical = 0
    core_dict = next(utils.find_in_lshw(sys_dict, 'core'), {})
    for core_child in utils.find_in_lshw(core_dict, _MEMORY_ID_RE):
        if core_child.get('size'):
            value = ("%(size)s %(units)s" % core_child)
            physical += int(UNIT_CONVERTER(value).to('MB').magnitude)
        else:
            for bank in core_child.get('children', ()):
                if bank.get('size'):
                    value = ("%(size)s %(units)s" % bank)
                    physical += int(UNIT_CONVERTER(value).to('MB').magnitude)
    return physical


def get_holder_disks(raid_device):
    """Get the holder disks of a Software RAID device.

    Examine an md device and return its underlying disks.

    :param raid_device: A Software RAID block device name.
    :returns: A list of the holder disks.
    """
    if not raid_device:
        return []

    try:
        out, _ = utils.execute('mdadm', '--detail', raid_device,
                               use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        LOG.warning('Could not get holder disks of %(dev)s: %(err)s',
                    {'dev': raid_device, 'err': e})
        return []

    holder_disks = []
    lines = out.splitlines()
    # the first line contains the md device itself

    holder_parts = []
    for line in lines[1:]:
        if 'Events' in line or 'Name' in line:
            continue
        device = re.findall(r'/dev/\w+', line)
        holder_parts += device
    for part in holder_parts:
        # NOTE(mnaser): If the last character is not a digit and it is a valid
        #               device, this means that instead of a partition, it's a
        #               entire device which is part of this RAID array.
        if (not part[-1].isdigit() and os.path.exists(part)
                and stat.S_ISBLK(os.stat(part).st_mode)):
            holder_disks.append(part)
            continue

        device = utils.extract_device(part)
        if not device:
            raise errors.SoftwareRAIDError(
                'Could not get holder disks of %s: unexpected pattern '
                'for partition %s' % (raid_device, part))
        holder_disks.append(device)

    return holder_disks


def is_md_device(raid_device):
    """Check if a device is an md device

    Check if a device is a Software RAID (md) device.

    :param raid_device: A Software RAID block device name.
    :returns: True if the device is an md device, False otherwise.
    """
    try:
        utils.execute('mdadm', '--detail', raid_device)
        LOG.debug("%s is an md device", raid_device)
        return True
    except FileNotFoundError:
        LOG.debug('mdadm has not been found, assuming %s is not an md device',
                  raid_device)
        return False
    except processutils.ProcessExecutionError:
        LOG.debug("%s is not an md device", raid_device)
        return False


def md_restart(raid_device):
    """Restart an md device

    Stop and re-assemble a Software RAID (md) device.

    :param raid_device: A Software RAID block device name.
    :raises: CommandExecutionError in case the restart fails.
    """
    try:
        LOG.debug('Restarting software RAID device %s', raid_device)
        component_devices = get_component_devices(raid_device)
        utils.execute('mdadm', '--stop', raid_device)
        utils.execute('mdadm', '--assemble', raid_device,
                      *component_devices)
    except processutils.ProcessExecutionError as e:
        error_msg = ('Could not restart md device %(dev)s: %(err)s' %
                     {'dev': raid_device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def md_get_raid_devices():
    """Get all discovered Software RAID (md) devices

    :returns: A python dict containing details about the discovered RAID
      devices
    """
    # Note(Boushra): mdadm output is similar to lsblk, but not
    # identical; do not use utils.parse_device_tags
    report = utils.execute('mdadm', '--examine', '--scan')[0]
    lines = report.splitlines()
    result = {}
    for line in lines:
        vals = shlex.split(line)
        device = vals[1]
        result[device] = {}
        for key, val in (v.split('=', 1) for v in vals[2:]):
            result[device][key] = val.strip()
    return result


def _md_scan_and_assemble():
    """Scan all md devices and assemble RAID arrays from them.

    This call does not fail if no md devices are present.
    """
    try:
        utils.execute('mdadm', '--assemble', '--scan', '--verbose')
    except FileNotFoundError:
        LOG.warning('mdadm has not been found, RAID devices will not be '
                    'supported')
    except processutils.ProcessExecutionError:
        LOG.info('No new RAID devices assembled during start-up')


def list_all_block_devices(block_type='disk',
                           ignore_raid=False,
                           ignore_floppy=True,
                           ignore_empty=True,
                           ignore_multipath=False,
                           all_serial_and_wwn=False):
    """List all physical block devices

    The switches we use for lsblk: P for KEY="value" output, b for size output
    in bytes, i to ensure ascii characters only, and o to specify the
    fields/columns we need.

    Broken out as its own function to facilitate custom hardware managers that
    don't need to subclass GenericHardwareManager.

    :param block_type: Type of block device to find
    :param ignore_raid: Ignore auto-identified raid devices, example: md0
                        Defaults to false as these are generally disk
                        devices and should be treated as such if encountered.
    :param ignore_floppy: Ignore floppy disk devices in the block device
                          list. By default, these devices are filtered out.
    :param ignore_empty: Whether to ignore disks with size equal 0.
    :param ignore_multipath: Whether to ignore devices backing multipath
                             devices. Default is to consider multipath
                             devices, if possible.
    :param all_serial_and_wwn: Don't collect serial and wwn numbers based
                               on a priority order, instead collect wwn
                               numbers from both udevadm and lsblk. When
                               enabled this option will also collect both
                               the short and the long serial from udevadm if
                               possible.

    :returns: A list of BlockDevices
    """

    def _is_known_device(existing, new_device_name):
        """Return true if device name is already known."""
        for known_dev in existing:
            if os.path.join('/dev', new_device_name) == known_dev.name:
                return True
        return False

    check_multipath = not ignore_multipath and get_multipath_status()

    disk_utils.udev_settle()

    # map device names to /dev/disk/by-path symbolic links that points to it

    by_path_mapping = {}

    disk_by_path_dir = '/dev/disk/by-path'

    try:
        paths = os.listdir(disk_by_path_dir)

        for path in paths:
            path = os.path.join(disk_by_path_dir, path)
            # Turn possibly relative symbolic link into absolute
            devname = os.path.join(disk_by_path_dir, os.readlink(path))
            devname = os.path.abspath(devname)
            by_path_mapping[devname] = path

    except OSError as e:
        # NOTE(TheJulia): This is for multipath detection, and will raise
        # some warning logs with unrelated tests.
        LOG.warning("Path %(path)s is inaccessible, /dev/disk/by-path/* "
                    "version of block device name is unavailable "
                    "Cause: %(error)s", {'path': disk_by_path_dir, 'error': e})

    columns = utils.LSBLK_COLUMNS
    report = utils.execute('lsblk', '-bia', '--json',
                           '-o{}'.format(','.join(columns)),
                           check_exit_code=[0])[0]

    try:
        report_json = json.loads(report)
    except json.decoder.JSONDecodeError as ex:
        LOG.error("Unable to decode lsblk output, invalid JSON: %s", ex)

    context = pyudev.Context()
    devices_raw = report_json['blockdevices']
    # Convert raw json output to something useful for us
    devices = []
    for device_raw in devices_raw:
        # Ignore block types not specified
        devtype = device_raw.get('type')

        # We already have devices, we should ensure we don't store duplicates.
        if _is_known_device(devices, device_raw.get('kname')):
            LOG.debug('Ignoring already known device %s', device_raw)
            continue

        # If we collected the RM column, we could consult it for removable
        # media, however USB devices are also flagged as removable media.
        # we have to explicitly do this as floppy disks are type disk.
        if ignore_floppy and str(device_raw.get('kname')).startswith('fd'):
            LOG.debug('Ignoring floppy disk device %s', device_raw)
            continue

        dev_kname = device_raw.get('kname')
        if check_multipath:
            # Net effect is we ignore base devices, and their base devices
            # to what would be the mapped device name which would not pass the
            # validation, but would otherwise be match-able.
            mpath_parent_dev = _get_multipath_parent_device(dev_kname)
            if mpath_parent_dev:
                LOG.warning(
                    "We have identified a multipath device %(device)s, this "
                    "is being ignored in favor of %(mpath_device)s and its "
                    "related child devices.",
                    {'device': dev_kname,
                     'mpath_device': mpath_parent_dev})
                continue
        # Search for raid in the reply type, as RAID is a
        # disk device, and we should honor it if is present.
        # Other possible type values, which we skip recording:
        #   lvm, part, rom, loop

        if devtype != block_type:
            if devtype is None or ignore_raid:
                LOG.debug(
                    "TYPE did not match. Wanted: %(block_type)s but found: "
                    "%(devtype)s (RAID devices are ignored)",
                    {'block_type': block_type, 'devtype': devtype})
                continue
            elif ('raid' in devtype
                  and block_type in ['raid', 'disk', 'mpath']):
                LOG.debug(
                    "TYPE detected to contain 'raid', signifying a "
                    "RAID volume. Found: %(device_raw)s",
                    {'device_raw': device_raw})
            elif (devtype == 'md'
                  and (block_type == 'part'
                       or block_type == 'md')):
                # NOTE(dszumski): Partitions on software RAID devices have type
                # 'md'. This may also contain RAID devices in a broken state in
                # rare occasions. See https://review.opendev.org/#/c/670807 for
                # more detail.
                LOG.debug(
                    "TYPE detected to contain 'md', signifying a "
                    "RAID partition. Found: %(device_raw)s",
                    {'device_raw': device_raw})
            elif devtype == 'mpath' and block_type == 'disk':
                LOG.debug(
                    "TYPE detected to contain 'mpath', "
                    "signifing a device mapper multipath device. "
                    "Found: %(device_raw)s",
                    {'device_raw': device_raw})
            else:
                LOG.debug(
                    "TYPE did not match. Wanted: %(block_type)s but found: "
                    "%(device_raw)s (RAID devices are ignored)",
                    {'block_type': block_type, 'device_raw': device_raw})
                continue

        # Ensure all required columns are at least present, even if blank
        missing = set(map(str.lower, columns)) - set(device_raw)
        if missing:
            raise errors.BlockDeviceError(
                '%s must be returned by lsblk.' % ', '.join(sorted(missing)))

        # NOTE(dtantsur): RAM disks and zRAM devices appear in the output of
        # lsblk as disks, but we cannot do anything useful with them.
        if (device_raw['kname'].startswith('ram')
                or device_raw['kname'].startswith('zram')):
            LOG.debug('Skipping RAM device %s', device_raw)
            continue

        # NOTE(dtantsur): some hardware represents virtual floppy devices as
        # normal block devices with size 0. Filter them out.
        if ignore_empty and not int(device_raw['size'] or 0):
            LOG.debug('Skipping device %s with zero size', device_raw)
            continue

        name = os.path.join('/dev', device_raw['kname'])

        extra = {}
        lsblk_serial = device_raw.get('serial')
        lsblk_wwn = device_raw.get('wwn')
        if all_serial_and_wwn:
            extra['serial'] = [lsblk_serial]
            extra['wwn'] = [lsblk_wwn]
        else:
            if lsblk_serial:
                extra['serial'] = lsblk_serial
            if lsblk_wwn:
                extra['wwn'] = lsblk_wwn
        try:
            udev = pyudev.Devices.from_device_file(context, name)
        except pyudev.DeviceNotFoundByFileError as e:
            LOG.warning("Device %(dev)s is inaccessible, skipping... "
                        "Error: %(error)s", {'dev': name, 'error': e})
        except pyudev.DeviceNotFoundByNumberError as e:
            LOG.warning("Device %(dev)s is not supported by pyudev, "
                        "skipping... Error: %(error)s",
                        {'dev': name, 'error': e})
        else:
            # lsblk serial information is prioritized over
            # udev serial information
            udev_property_mappings = [
                ('wwn', 'WWN'),
                ('wwn_with_extension', 'WWN_WITH_EXTENSION'),
                ('wwn_vendor_extension', 'WWN_VENDOR_EXTENSION')
            ]
            # Only check device serial information from udev
            # when lsblk returned None
            if all_serial_and_wwn or not lsblk_serial:
                udev_property_mappings += [
                    ('serial', 'SERIAL_SHORT'),
                    ('serial', 'SERIAL')
                ]
            for key, udev_key in udev_property_mappings:
                if all_serial_and_wwn and (key == 'wwn' or key == 'serial'):
                    value = (udev.get(f'ID_{udev_key}')
                             or udev.get(f'DM_{udev_key}'))  # devicemapper
                    extra[key].append(value)
                else:
                    if key in extra:
                        continue
                    value = (udev.get(f'ID_{udev_key}')
                             or udev.get(f'DM_{udev_key}'))  # devicemapper
                    if value:
                        extra[key] = value

        # NOTE(lucasagomes): Newer versions of the lsblk tool supports
        # HCTL as a parameter but let's get it from sysfs to avoid breaking
        # old distros.
        try:
            extra['hctl'] = os.listdir(
                '/sys/block/%s/device/scsi_device' % device_raw['kname'])[0]
        except (OSError, IndexError):
            LOG.warning('Could not find the SCSI address (HCTL) for '
                        'device %s. Skipping', name)

        # Not all /dev entries are pointed to from /dev/disk/by-path
        by_path_name = by_path_mapping.get(name)

        devices.append(BlockDevice(name=name,
                                   model=device_raw['model'],
                                   size=int(device_raw['size'] or 0),
                                   rotational=bool(int(device_raw['rota'])),
                                   vendor=_get_device_info(device_raw['kname'],
                                                           'block', 'vendor'),
                                   by_path=by_path_name,
                                   uuid=device_raw['uuid'],
                                   partuuid=device_raw['partuuid'],
                                   logical_sectors=device_raw['log-sec'],
                                   physical_sectors=device_raw['phy-sec'],
                                   **extra))
    return devices


def save_api_client(client=None, timeout=None, interval=None):
    """Preserves access to the API client for potential later reuse."""
    global API_CLIENT, API_LOOKUP_TIMEOUT, API_LOOKUP_INTERVAL

    if client and timeout and interval and not API_CLIENT:
        API_CLIENT = client
        API_LOOKUP_TIMEOUT = timeout
        API_LOOKUP_INTERVAL = interval


def update_cached_node():
    """Attempts to update the node cache via the API"""
    cached_node = get_cached_node()
    if API_CLIENT:
        LOG.info('Agent is requesting to perform an explicit node cache '
                 'update. This is to pickup any changes in the cache '
                 'before deployment.')
        try:
            if cached_node is None:
                uuid = None
            else:
                uuid = cached_node['uuid']
            content = API_CLIENT.lookup_node(
                hardware_info=list_hardware_info(use_cache=True),
                timeout=API_LOOKUP_TIMEOUT,
                starting_interval=API_LOOKUP_INTERVAL,
                node_uuid=uuid)
            cache_node(content['node'])
            return content['node']
        except Exception as exc:
            LOG.warning('Failed to update node cache. Error %s', exc)
    return cached_node


class HardwareSupport(object):
    """Example priorities for hardware managers.

    Priorities for HardwareManagers are integers, where largest means most
    specific and smallest means most generic. These values are guidelines
    that suggest values that might be returned by calls to
    `evaluate_hardware_support()`. No HardwareManager in mainline IPA will
    ever return a value greater than MAINLINE. Third party hardware managers
    should feel free to return values of SERVICE_PROVIDER or greater to
    distinguish between additional levels of hardware support.
    """
    NONE = 0
    GENERIC = 1
    MAINLINE = 2
    SERVICE_PROVIDER = 3


class HardwareType(object):
    MAC_ADDRESS = 'mac_address'


class BlockDevice(encoding.SerializableComparable):
    serializable_fields = ('name', 'model', 'size', 'rotational',
                           'wwn', 'serial', 'vendor', 'wwn_with_extension',
                           'wwn_vendor_extension', 'hctl', 'by_path',
                           'logical_sectors', 'physical_sectors')

    def __init__(self, name, model, size, rotational, wwn=None, serial=None,
                 vendor=None, wwn_with_extension=None,
                 wwn_vendor_extension=None, hctl=None, by_path=None,
                 uuid=None, partuuid=None,
                 logical_sectors=None, physical_sectors=None):
        self.name = name
        self.model = model
        self.size = size
        self.rotational = rotational
        self.uuid = uuid
        self.wwn = wwn
        self.serial = serial
        self.vendor = vendor
        self.wwn_with_extension = wwn_with_extension
        self.wwn_vendor_extension = wwn_vendor_extension
        self.hctl = hctl
        self.by_path = by_path
        self.partuuid = partuuid
        self.logical_sectors = logical_sectors
        self.physical_sectors = physical_sectors


class NetworkInterface(encoding.SerializableComparable):
    serializable_fields = ('name', 'mac_address', 'ipv4_address',
                           'ipv6_address', 'has_carrier', 'lldp',
                           'vendor', 'product', 'client_id',
                           'biosdevname', 'speed_mbps', 'pci_address',
                           'driver')

    def __init__(self, name, mac_addr, ipv4_address=None, ipv6_address=None,
                 has_carrier=True, lldp=None, vendor=None, product=None,
                 client_id=None, biosdevname=None, speed_mbps=None,
                 pci_address=None, driver=None):
        self.name = name
        self.mac_address = mac_addr
        self.ipv4_address = ipv4_address
        self.ipv6_address = ipv6_address
        self.has_carrier = has_carrier
        self.lldp = lldp
        self.vendor = vendor
        self.product = product
        self.biosdevname = biosdevname
        self.speed_mbps = speed_mbps
        self.pci_address = pci_address
        self.driver = driver
        # client_id is used for InfiniBand only. we calculate the DHCP
        # client identifier Option to allow DHCP to work over InfiniBand.
        # see https://tools.ietf.org/html/rfc4390
        self.client_id = client_id


class CPUCore(encoding.SerializableComparable):
    serializable_fields = ('model_name', 'frequency', 'count', 'architecture',
                           'flags', 'core_id')

    def __init__(self, model_name, frequency, architecture,
                 core_id, flags=None):
        self.model_name = model_name
        self.frequency = frequency
        self.architecture = architecture
        self.core_id = core_id

        self.flags = flags or []


class CPU(encoding.SerializableComparable):
    serializable_fields = ('model_name', 'frequency', 'count', 'architecture',
                           'flags', 'socket_count')

    def __init__(self, model_name, frequency, count, architecture,
                 flags=None, socket_count=None, cpus: List[CPUCore] = None):
        self.model_name = model_name
        self.frequency = frequency
        self.count = count
        self.socket_count = socket_count
        self.architecture = architecture
        self.flags = flags or []

        self.cpus = cpus or []


class Memory(encoding.SerializableComparable):
    serializable_fields = ('total', 'physical_mb')
    # physical = total + kernel binary + reserved space

    def __init__(self, total, physical_mb=None):
        self.total = total
        self.physical_mb = physical_mb


class SystemFirmware(encoding.SerializableComparable):
    serializable_fields = ('vendor', 'version', 'build_date')

    def __init__(self, vendor, version, build_date):
        self.version = version
        self.build_date = build_date
        self.vendor = vendor


class SystemVendorInfo(encoding.SerializableComparable):
    serializable_fields = ('product_name', 'serial_number', 'manufacturer',
                           'firmware')

    def __init__(self, product_name, serial_number, manufacturer, firmware):
        self.product_name = product_name
        self.serial_number = serial_number
        self.manufacturer = manufacturer
        self.firmware = firmware


class USBInfo(encoding.SerializableComparable):
    serializable_fields = ('product', 'vendor', 'handle')

    def __init__(self, product, vendor, handle):
        self.product = product
        self.vendor = vendor
        self.handle = handle


class BootInfo(encoding.SerializableComparable):
    serializable_fields = ('current_boot_mode', 'pxe_interface')

    def __init__(self, current_boot_mode, pxe_interface=None):
        self.current_boot_mode = current_boot_mode
        self.pxe_interface = pxe_interface


class HardwareManager(object, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def evaluate_hardware_support(self):
        pass

    def list_network_interfaces(self):
        raise errors.IncompatibleHardwareMethodError

    def collect_lldp_data(self, interface_names=None):
        raise errors.IncompatibleHardwareMethodError

    def get_cpus(self):
        raise errors.IncompatibleHardwareMethodError

    def list_block_devices(self, include_partitions=False):
        """List physical block devices

        :param include_partitions: If to include partitions
        :returns: A list of BlockDevices
        """
        raise errors.IncompatibleHardwareMethodError

    def get_skip_list_from_node(self, node,
                                block_devices=None, just_raids=False):
        """Get the skip block devices list from the node

        :param block_devices: a list of BlockDevices
        :param just_raids: a boolean to signify that only RAID devices
                           are important
        :returns: A set of names of devices on the skip list
        """
        raise errors.IncompatibleHardwareMethodError

    def list_block_devices_check_skip_list(self, node,
                                           include_partitions=False):
        """List physical block devices without the ones listed in

        properties/skip_block_devices list

        :param node: A node used to check the skip list
        :param include_partitions: If to include partitions
        :returns: A list of BlockDevices
        """
        raise errors.IncompatibleHardwareMethodError

    def get_memory(self):
        raise errors.IncompatibleHardwareMethodError

    def get_os_install_device(self, permit_refresh=False):
        raise errors.IncompatibleHardwareMethodError

    def get_bmc_address(self):
        raise errors.IncompatibleHardwareMethodError()

    def get_bmc_mac(self):
        raise errors.IncompatibleHardwareMethodError()

    def get_bmc_v6address(self):
        raise errors.IncompatibleHardwareMethodError()

    def get_boot_info(self):
        raise errors.IncompatibleHardwareMethodError()

    def get_interface_info(self, interface_name):
        raise errors.IncompatibleHardwareMethodError()

    def generate_tls_certificate(self, ip_address):
        raise errors.IncompatibleHardwareMethodError()

    def get_usb_devices(self):
        """Collect USB devices

        List all USB final devices, based on lshw information

        :returns: a dict, containing product, vendor, and handle information
        """
        raise errors.IncompatibleHardwareMethodError()

    def erase_block_device(self, node, block_device):
        """Attempt to erase a block device.

        Implementations should detect the type of device and erase it in the
        most appropriate way possible. Generic implementations should support
        common erase mechanisms such as ATA secure erase, or multi-pass random
        writes. Operators with more specific needs should override this method
        in order to detect and handle "interesting" cases, or delegate to the
        parent class to handle generic cases.

        For example: operators running ACME MagicStore (TM) cards alongside
        standard SSDs might check whether the device is a MagicStore and use a
        proprietary tool to erase that, otherwise call this method on their
        parent class. Upstream submissions of common functionality are
        encouraged.

        This interface could be called concurrently to speed up erasure, as
        such, it should be implemented in a thread-safe way.

        :param node: Ironic node object
        :param block_device: a BlockDevice indicating a device to be erased.
        :raises IncompatibleHardwareMethodError: when there is no known way to
                erase the block device
        :raises BlockDeviceEraseError: when there is an error erasing the
                block device
        """
        raise errors.IncompatibleHardwareMethodError

    def erase_devices(self, node, ports):
        """Erase any device that holds user data.

        By default this will attempt to erase block devices. This method can be
        overridden in an implementation-specific hardware manager in order to
        erase additional hardware, although backwards-compatible upstream
        submissions are encouraged.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :raises: ProtectedDeviceError if a device has been identified which
                 may require manual intervention due to the contents and
                 operational risk which exists as it could also be a sign
                 of an environmental misconfiguration.
        :returns: a dictionary in the form {device.name: erasure output}
        """
        erase_results = {}
        block_devices = self.list_block_devices_check_skip_list(node)
        if not len(block_devices):
            return {}

        info = node.get('driver_internal_info', {})
        max_pool_size = info.get('disk_erasure_concurrency', 1)

        thread_pool = ThreadPool(min(max_pool_size, len(block_devices)))
        for block_device in block_devices:
            params = {'node': node, 'block_device': block_device}
            safety_check_block_device(node, block_device.name)
            erase_results[block_device.name] = thread_pool.apply_async(
                dispatch_to_managers, ('erase_block_device',), params)
        thread_pool.close()
        thread_pool.join()

        for device_name, result in erase_results.items():
            erase_results[device_name] = result.get()

        return erase_results

    def wait_for_disks(self):
        """Wait for the root disk to appear.

        Wait for at least one suitable disk to show up or a specific disk
        if any device hint is specified. Otherwise neither inspection
        not deployment have any chances to succeed.

        """
        if not CONF.disk_wait_attempts:
            return

        max_waits = CONF.disk_wait_attempts - 1
        for attempt in range(CONF.disk_wait_attempts):
            try:
                self.get_os_install_device()
            except errors.DeviceNotFound:
                LOG.debug('Still waiting for the root device to appear, '
                          'attempt %d of %d', attempt + 1,
                          CONF.disk_wait_attempts)

                if attempt < max_waits:
                    time.sleep(CONF.disk_wait_delay)
            else:
                break
        else:
            if max_waits:
                LOG.warning('The root device was not detected in %d seconds',
                            CONF.disk_wait_delay * max_waits)
            else:
                LOG.warning('The root device was not detected')

    def list_hardware_info(self):
        """Return full hardware inventory as a serializable dict.

        This inventory is sent to Ironic on lookup and to Inspector on
        inspection.

        :returns: a dictionary representing inventory
        """
        start = time.time()
        LOG.info('Collecting full inventory')
        # NOTE(dtantsur): don't forget to update docs when extending inventory
        hardware_info = {}
        hardware_info['interfaces'] = self.list_network_interfaces()
        hardware_info['cpu'] = self.get_cpus()
        hardware_info['disks'] = self.list_block_devices()
        hardware_info['memory'] = self.get_memory()
        hardware_info['bmc_address'] = self.get_bmc_address()
        hardware_info['bmc_v6address'] = self.get_bmc_v6address()
        hardware_info['system_vendor'] = self.get_system_vendor_info()
        hardware_info['boot'] = self.get_boot_info()
        hardware_info['hostname'] = netutils.get_hostname()

        try:
            hardware_info['bmc_mac'] = self.get_bmc_mac()
        except errors.IncompatibleHardwareMethodError:
            # if the hardware manager does not support obtaining the BMC MAC,
            # we simply don't expose it.
            pass

        LOG.info('Inventory collected in %.2f second(s)', time.time() - start)
        return hardware_info

    def get_clean_steps(self, node, ports):
        """Get a list of clean steps with priority.

        Returns a list of steps. Each step is represented by a dict::

          {
           'interface': the name of the driver interface that should execute
                        the step.
           'step': the HardwareManager function to call.
           'priority': the order steps will be run in. Ironic will sort all
                       the clean steps from all the drivers, with the largest
                       priority step being run first. If priority is set to 0,
                       the step will not be run during cleaning, but may be
                       run during zapping.
           'reboot_requested': Whether the agent should request Ironic reboots
                               the node via the power driver after the
                               operation completes.
           'abortable': Boolean value. Whether the clean step can be
                        stopped by the operator or not. Some clean step may
                        cause non-reversible damage to a machine if interrupted
                        (i.e firmware update), for such steps this parameter
                        should be set to False. If no value is set for this
                        parameter, Ironic will consider False (non-abortable).
          }


        If multiple hardware managers return the same step name, the following
        logic will be used to determine which manager's step "wins":

            * Keep the step that belongs to HardwareManager with highest
              HardwareSupport (larger int) value.
            * If equal support level, keep the step with the higher defined
              priority (larger int).
            * If equal support level and priority, keep the step associated
              with the HardwareManager whose name comes earlier in the
              alphabet.

        The steps will be called using `hardware.dispatch_to_managers` and
        handled by the best suited hardware manager. If you need a step to be
        executed by only your hardware manager, ensure it has a unique step
        name.

        `node` and `ports` can be used by other hardware managers to further
        determine if a clean step is supported for the node.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :returns: a list of cleaning steps, where each step is described as a
                 dict as defined above

        """
        return []

    def get_deploy_steps(self, node, ports):
        """Get a list of deploy steps with priority.

        Returns a list of steps. Each step is represented by a dict::

          {
           'interface': the name of the driver interface that should execute
                        the step.
           'step': the HardwareManager function to call.
           'priority': the order steps will be run in. Ironic will sort all
                       the deploy steps from all the drivers, with the largest
                       priority step being run first. If priority is set to 0,
                       the step will not be run during deployment
                       automatically, but may be requested via deploy
                       templates.
           'reboot_requested': Whether the agent should request Ironic reboots
                               the node via the power driver after the
                               operation completes.
           'argsinfo': arguments specification.
          }


        If multiple hardware managers return the same step name, the following
        logic will be used to determine which manager's step "wins":

            * Keep the step that belongs to HardwareManager with highest
              HardwareSupport (larger int) value.
            * If equal support level, keep the step with the higher defined
              priority (larger int).
            * If equal support level and priority, keep the step associated
              with the HardwareManager whose name comes earlier in the
              alphabet.

        The steps will be called using `hardware.dispatch_to_managers` and
        handled by the best suited hardware manager. If you need a step to be
        executed by only your hardware manager, ensure it has a unique step
        name.

        `node` and `ports` can be used by other hardware managers to further
        determine if a deploy step is supported for the node.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :returns: a list of deploying steps, where each step is described as a
                 dict as defined above

        """
        return []

    def get_service_steps(self, node, ports):
        """Get a list of service steps.

        Returns a list of steps. Each step is represented by a dict::

          {
           'interface': the name of the driver interface that should execute
                        the step.
           'step': the HardwareManager function to call.
           'priority': the order steps will be run in if executed upon
                       similar to automated cleaning or deployment.
                       In service steps, the order comes from the user request,
                       but this similarity is kept for consistency should we
                       further extend the capability at some point in the
                       future.
           'reboot_requested': Whether the agent should request Ironic reboots
                               the node via the power driver after the
                               operation completes.
           'abortable': Boolean value. Whether the service step can be
                        stopped by the operator or not. Some steps may
                        cause non-reversible damage to a machine if interrupted
                        (i.e firmware update), for such steps this parameter
                        should be set to False. If no value is set for this
                        parameter, Ironic will consider False (non-abortable).
          }


        If multiple hardware managers return the same step name, the following
        logic will be used to determine which manager's step "wins":

            * Keep the step that belongs to HardwareManager with highest
              HardwareSupport (larger int) value.
            * If equal support level, keep the step with the higher defined
              priority (larger int).
            * If equal support level and priority, keep the step associated
              with the HardwareManager whose name comes earlier in the
              alphabet.

        The steps will be called using `hardware.dispatch_to_managers` and
        handled by the best suited hardware manager. If you need a step to be
        executed by only your hardware manager, ensure it has a unique step
        name.

        `node` and `ports` can be used by other hardware managers to further
        determine if a step is supported for the node.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :returns: a list of service steps, where each step is described as a
                 dict as defined above

        """
        return []

    def get_version(self):
        """Get a name and version for this hardware manager.

        In order to avoid errors and make agent upgrades painless, cleaning
        will check the version of all hardware managers during get_clean_steps
        at the beginning of cleaning and before executing each step in the
        agent.

        The agent isn't aware of the steps being taken before or after via
        out of band steps, so it can never know if a new step is safe to run.
        Therefore, we default to restarting the whole process.

        :returns: a dictionary with two keys: `name` and
            `version`, where `name` is a string identifying the hardware
            manager and `version` is an arbitrary version string. `name` will
            be a class variable called HARDWARE_MANAGER_NAME, or default to
            the class name and `version` will be a class variable called
            HARDWARE_MANAGER_VERSION or default to '1.0'.
        """
        return {
            'name': getattr(self, 'HARDWARE_MANAGER_NAME',
                            type(self).__name__),
            'version': getattr(self, 'HARDWARE_MANAGER_VERSION', '1.0')
        }

    def collect_system_logs(self, io_dict, file_list):
        """Collect logs from the system.

        Implementations should update `io_dict` and `file_list` with logs
        to send to Ironic and Inspector.

        :param io_dict: Dictionary mapping file names to binary IO objects
            with corresponding data.
        :param file_list: List of full file paths to include.
        """
        raise errors.IncompatibleHardwareMethodError()

    def full_sync(self):
        """Synchronize all caches to the disk.

        This method will be called on *all* managers before the ramdisk
        is powered off externally. It is expected to try flush all caches
        to the disk to avoid data loss.
        """
        raise errors.IncompatibleHardwareMethodError()


class GenericHardwareManager(HardwareManager):
    HARDWARE_MANAGER_NAME = 'generic_hardware_manager'
    # 1.1 - Added new clean step called erase_devices_metadata
    # 1.2 - Added new get_service_steps method
    HARDWARE_MANAGER_VERSION = '1.2'

    def __init__(self):
        self.lldp_data = {}
        self._lshw_cache = None

    def evaluate_hardware_support(self):
        # Do some initialization before we declare ourself ready
        _check_for_iscsi()
        _md_scan_and_assemble()
        _load_ipmi_modules()
        global MULTIPATH_ENABLED
        if MULTIPATH_ENABLED is None:
            MULTIPATH_ENABLED = _enable_multipath()

        self.wait_for_disks()
        return HardwareSupport.GENERIC

    def list_hardware_info(self):
        """Return full hardware inventory as a serializable dict.

        This inventory is sent to Ironic on lookup and to Inspector on
        inspection.

        :returns: a dictionary representing inventory
        """
        with self._cached_lshw():
            return super().list_hardware_info()

    @contextlib.contextmanager
    def _cached_lshw(self):
        if self._lshw_cache:
            yield  # make this context manager reentrant without purging cache
            return

        self._lshw_cache = self._get_system_lshw_dict()
        try:
            yield
        finally:
            self._lshw_cache = None

    def _get_system_lshw_dict(self):
        """Get a dict representation of the system from lshw

        Retrieves a json representation of the system from lshw and converts
        it to a python dict

        :returns: A python dict from the lshw json output
        """
        if self._lshw_cache:
            return self._lshw_cache

        out, _e = utils.execute('lshw', '-quiet', '-json', log_stdout=False)
        out = json.loads(out)
        # Depending on lshw version, output might be a list, starting with
        # https://github.com/lyonel/lshw/commit/135a853c60582b14c5b67e5cd988a8062d9896f4  # noqa
        if isinstance(out, list):
            return out[0]
        return out

    def collect_lldp_data(self, interface_names=None):
        """Collect and convert LLDP info from the node.

        In order to process the LLDP information later, the raw data needs to
        be converted for serialization purposes.

        :param interface_names: list of names of node's interfaces.
        :returns: a dict, containing the lldp data from every interface.
        """
        if interface_names is None:
            interface_names = netutils.list_interfaces()
        interface_names = [name for name in interface_names if name != 'lo']
        lldp_data = {}
        try:
            raw_lldp_data = netutils.get_lldp_info(interface_names)
        except Exception:
            # NOTE(sambetts) The get_lldp_info function will log this exception
            # and we don't invalidate any existing data in the cache if we fail
            # to get data to replace it so just return.
            return lldp_data
        for ifname, tlvs in raw_lldp_data.items():
            # NOTE(sambetts) Convert each type-length-value (TLV) value to hex
            # so that it can be serialised safely
            processed_tlvs = []
            for typ, data in tlvs:
                try:
                    processed_tlvs.append((typ,
                                           binascii.hexlify(data).decode()))
                except (binascii.Error, binascii.Incomplete) as e:
                    LOG.warning('An error occurred while processing TLV type '
                                '%(type)s for interface %(name)s: %(err)s',
                                {'type': typ, 'name': ifname, 'err': e})
            lldp_data[ifname] = processed_tlvs
        return lldp_data

    def _get_lldp_data(self, interface_name):
        if self.lldp_data:
            return self.lldp_data.get(interface_name)

    def _get_network_speed(self, interface_name):
        sys_dict = self._get_system_lshw_dict()
        try:
            iface_dict = next(
                utils.find_in_lshw(sys_dict, by_class='network',
                                   logicalname=interface_name,
                                   recursive=True)
            )
        except StopIteration:
            LOG.warning('Cannot find detailed information about interface %s',
                        interface_name)
            return None

        # speed is the current speed, capacity is the maximum speed
        speed = iface_dict.get('capacity') or iface_dict.get('speed')
        if not speed:
            LOG.debug('No speed information about in %s', iface_dict)
            return None

        units = iface_dict.get('units', 'bit_s').replace('/', '_')
        return int(UNIT_CONVERTER(f'{speed} {units}')
                   .to(UNIT_CONVERTER.Mbit_s)
                   .magnitude)

    def get_interface_info(self, interface_name):
        mac_addr = netutils.get_mac_addr(interface_name)
        if mac_addr is None:
            raise errors.IncompatibleHardwareMethodError()

        return NetworkInterface(
            interface_name, mac_addr,
            ipv4_address=self.get_ipv4_addr(interface_name),
            ipv6_address=self.get_ipv6_addr(interface_name),
            has_carrier=netutils.interface_has_carrier(interface_name),
            vendor=_get_device_info(interface_name, 'net', 'vendor'),
            product=_get_device_info(interface_name, 'net', 'device'),
            biosdevname=self.get_bios_given_nic_name(interface_name),
            speed_mbps=self._get_network_speed(interface_name),
            pci_address=netutils.get_interface_pci_address(interface_name),
            driver=netutils.get_interface_driver(interface_name)
        )

    def get_ipv4_addr(self, interface_id):
        return netutils.get_ipv4_addr(interface_id)

    def get_ipv6_addr(self, interface_id):
        """Get the default IPv6 address assigned to the interface.

        With different networking environment, the address could be a
        link-local address, ULA or something else.
        """
        return netutils.get_ipv6_addr(interface_id)

    def get_bios_given_nic_name(self, interface_name):
        """Collect the BIOS given NICs name.

        This function uses the biosdevname utility to collect the BIOS given
        name of network interfaces.

        The collected data is added to the network interface inventory with an
        extra field named ``biosdevname``.

        :param interface_name: list of names of node's interfaces.
        :returns: the BIOS given NIC name of node's interfaces or default
                 as None.
        """
        global WARN_BIOSDEVNAME_NOT_FOUND

        if netutils.is_vlan(interface_name):
            LOG.debug('Interface %s is a VLAN, biosdevname not called',
                      interface_name)
            return

        try:
            stdout, _ = utils.execute('biosdevname', '-i', interface_name)
            return stdout.rstrip('\n')
        except OSError:
            if not WARN_BIOSDEVNAME_NOT_FOUND:
                LOG.warning("Executable 'biosdevname' not found")
                WARN_BIOSDEVNAME_NOT_FOUND = True
        except processutils.ProcessExecutionError as e:
            # NOTE(alezil) biosdevname returns 4 if running in a
            # virtual machine.
            if e.exit_code == 4:
                LOG.info('The system is a virtual machine, so biosdevname '
                         'utility does not provide names for virtual NICs.')
            else:
                LOG.warning('Biosdevname returned exit code %s', e.exit_code)

    def list_network_interfaces(self):
        iface_names = netutils.list_interfaces()

        if CONF.collect_lldp:
            self.lldp_data = dispatch_to_managers('collect_lldp_data',
                                                  interface_names=iface_names)

        network_interfaces_list = []
        with self._cached_lshw():
            for iface_name in iface_names:
                try:
                    result = dispatch_to_managers(
                        'get_interface_info', interface_name=iface_name)
                except errors.HardwareManagerMethodNotFound:
                    LOG.warning('No hardware manager was able to handle '
                                'interface %s', iface_name)
                    continue
                result.lldp = self._get_lldp_data(iface_name)
                network_interfaces_list.append(result)

            # If configured, bring up vlan interfaces. If the actual vlans
            # aren't defined they are derived from LLDP data
            if CONF.enable_vlan_interfaces:
                vlan_iface_names = netutils.bring_up_vlan_interfaces(
                    network_interfaces_list)
                for vlan_iface_name in vlan_iface_names:
                    result = dispatch_to_managers(
                        'get_interface_info', interface_name=vlan_iface_name)
                    network_interfaces_list.append(result)

        return network_interfaces_list

    def any_ipmi_device_exists(self):
        '''Check for an IPMI device to confirm IPMI capability.'''
        for pattern in ['/dev/ipmi*', '/dev/ipmi/*', '/dev/ipmidev/*']:
            ipmi_files = glob.glob(pattern)
            for device in ipmi_files:
                if utils.is_char_device(device):
                    return True
        return False

    @staticmethod
    def create_cpu_info_dict(lines):
        cpu_info = {k.strip().lower(): v.strip() for k, v in
                    (line.split(':', 1)
                    for line in lines.split('\n')
                    if line.strip())}

        return cpu_info

    def read_cpu_info(self):
        sections = []

        try:
            with open('/proc/cpuinfo', 'r') as file:
                file_contents = file.read()

            # Replace tabs with nothing (essentially removing them)
            file_contents = file_contents.replace("\t", "")

            # Split the string into a list of CPU core entries
            # Each core's info is separated by a double newline
            sections = file_contents.split("\n\n")[:-1]

        except (FileNotFoundError, errors.InspectionError, OSError) as e:
            LOG.warning(
                'Failed to get CPU information from /proc/cpuinfo: %s', e
            )

        return sections

    def get_cpu_cores(self):
        cpu_info_dicts = []

        sections = self.read_cpu_info()

        for lines in sections:
            cpu_info = self.create_cpu_info_dict(lines)

            if cpu_info is not None:
                cpu_info_dicts.append(cpu_info)

        if len(cpu_info_dicts) == 0:
            LOG.warning(
                'No per-core CPU information found'
            )

        cpus = []
        for cpu_info in cpu_info_dicts:
            cpu = CPUCore(
                model_name=cpu_info.get('model name', ''),
                frequency=cpu_info.get('cpu mhz', ''),
                architecture=cpu_info.get('architecture', ''),
                core_id=cpu_info.get('core id', ''),
                flags=cpu_info.get('flags', '').split()
            )
            cpus.append(cpu)

        return cpus

    def get_cpus(self):
        lines = utils.execute('lscpu')[0]
        cpu_info = self.create_cpu_info_dict(lines)

        # NOTE(adamcarthur) Kept this assuming it was added as a fallback
        # for systems where lscpu does not show flags.
        if not cpu_info.get("flags", None):

            sections = self.read_cpu_info()
            if len(sections) == 0:
                cpu_info['flags'] = ""
            else:
                cpu_info_proc = self.create_cpu_info_dict(sections[0])

                flags = cpu_info_proc.get('flags', "")

                # NOTE(adamcarthur) This is only a basic check to
                # check the flags look correct
                if flags and re.search(r'[A-Z!@#$%^&*()_+{}|:"<>?]', flags):
                    LOG.warning('Malformed CPU flags information: %s', flags)
                    cpu_info['flags'] = ""
                else:
                    cpu_info['flags'] = flags

        if cpu_info["flags"] == "":
            LOG.warning(
                'No CPU flags found'
            )

        return CPU(
            model_name=cpu_info.get('model name', ''),
            # NOTE(adamcarthur) Current CPU frequency can
            # be different from maximum one on modern processors
            frequency=cpu_info.get(
                'cpu max mhz',
                cpu_info.get('cpu mhz', "")
            ),
            count=int(cpu_info.get('cpu(s)', 0)),
            architecture=cpu_info.get('architecture', ''),
            flags=cpu_info.get('flags', '').split(),
            socket_count=int(cpu_info.get('socket(s)', 0)),
            cpus=self.get_cpu_cores()
        )

    def get_memory(self):
        # psutil returns a long, so we force it to an int
        try:
            total = int(psutil.virtual_memory().total)
        except Exception:
            # This is explicitly catching all exceptions. We want to catch any
            # situation where a newly upgraded psutil would fail, and instead
            # print an error instead of blowing up the stack on IPA.
            total = None
            LOG.exception(("Cannot fetch total memory size using psutil "
                           "version %s"), psutil.version_info[0])
        try:
            sys_dict = self._get_system_lshw_dict()
        except (processutils.ProcessExecutionError, OSError, ValueError) as e:
            LOG.warning('Could not get real physical RAM from lshw: %s', e)
            physical = None
        else:
            physical = _calc_memory(sys_dict)

            if not physical:
                LOG.warning('Did not find any physical RAM')

        return Memory(total=total, physical_mb=physical)

    def list_block_devices(self, include_partitions=False,
                           all_serial_and_wwn=False):
        block_devices = \
            list_all_block_devices(all_serial_and_wwn=all_serial_and_wwn)
        if include_partitions:
            block_devices.extend(
                list_all_block_devices(block_type='part',
                                       ignore_raid=True)
            )
        return block_devices

    def get_skip_list_from_node(self, node,
                                block_devices=None, just_raids=False):
        properties = node.get('properties', {})
        skip_list_hints = properties.get("skip_block_devices", [])
        if not skip_list_hints:
            return None
        if just_raids:
            return {d['volume_name'] for d in skip_list_hints
                    if 'volume_name' in d}
        if not block_devices:
            return None
        skip_list = set()
        serialized_devs = [dev.serialize() for dev in block_devices]
        for hint in skip_list_hints:
            if 'volume_name' in hint:
                continue
            found_devs = device_hints.find_devices_by_hints(serialized_devs,
                                                            hint)
            excluded_devs = {dev['name'] for dev in found_devs}
            skipped_devices = excluded_devs.difference(skip_list)
            skip_list = skip_list.union(excluded_devs)
            if skipped_devices:
                LOG.warning("Using hint %(hint)s skipping devices: %(devs)s",
                            {'hint': hint, 'devs': ','.join(skipped_devices)})
        return skip_list

    def list_block_devices_check_skip_list(self, node,
                                           include_partitions=False,
                                           all_serial_and_wwn=False):
        block_devices = self.list_block_devices(
            include_partitions=include_partitions,
            all_serial_and_wwn=all_serial_and_wwn)
        skip_list = self.get_skip_list_from_node(
            node, block_devices)
        if skip_list is not None:
            block_devices = [d for d in block_devices
                             if d.name not in skip_list]
        return block_devices

    def get_os_install_device(self, permit_refresh=False):
        cached_node = get_cached_node()
        root_device_hints = None
        if cached_node is not None:
            root_device_hints = (
                cached_node['instance_info'].get('root_device')
                or cached_node['properties'].get('root_device'))
            if permit_refresh and not root_device_hints:
                cached_node = update_cached_node()
                root_device_hints = (
                    cached_node['instance_info'].get('root_device')
                    or cached_node['properties'].get('root_device'))
            LOG.debug('Looking for a device matching root hints %s',
                      root_device_hints)
            block_devices = self.list_block_devices_check_skip_list(
                cached_node, all_serial_and_wwn=True)
        else:
            block_devices = self.list_block_devices(all_serial_and_wwn=True)
        if not root_device_hints:
            dev_name = utils.guess_root_disk(block_devices).name
        else:
            serialized_devs = [dev.serialize() for dev in block_devices]
            orig_size = len(serialized_devs)
            for dev_idx in range(orig_size):
                ser_dev = serialized_devs.pop(0)
                serials = ser_dev.get('serial')
                wwns = ser_dev.get('wwn')
                # (rozzi) static serial and static wwn are used to avoid
                # reundancy in the number of wwns and serials, if the code
                # would just loop over both serials and wwns it could be that
                # there would be an uncesarry duplication of the first wwn
                # number
                for serial in serials:
                    for wwn in wwns:
                        tmp_ser_dev = ser_dev.copy()
                        tmp_ser_dev['wwn'] = wwn
                        tmp_ser_dev['serial'] = serial
                        serialized_devs.append(tmp_ser_dev)
            try:
                device = device_hints.match_root_device_hints(
                    serialized_devs, root_device_hints)
            except ValueError as e:
                # NOTE(lucasagomes): Just playing on the safe side
                # here, this exception should never be raised because
                # Ironic should validate the root device hints before the
                # deployment starts.
                raise errors.DeviceNotFound(
                    'No devices could be found using the root device hints '
                    '%(hints)s because they failed to validate. Error: '
                    '%(error)s' % {'hints': root_device_hints, 'error': e})

            if not device:
                raise errors.DeviceNotFound(
                    "No suitable device was found for "
                    "deployment using these hints %s" % root_device_hints)

            dev_name = device['name']

        LOG.info('Picked root device %(dev)s for node %(node)s based on '
                 'root device hints %(hints)s',
                 {'dev': dev_name, 'hints': root_device_hints,
                  'node': cached_node['uuid'] if cached_node else None})
        return dev_name

    def get_usb_devices(self):
        sys_dict = self._get_system_lshw_dict()
        try:
            usb_dict = utils.find_in_lshw(sys_dict, by_id='usb',
                                          by_class='generic', recursive=True)

        except StopIteration:
            LOG.warning('Cannot find detailed information about USB')
            return None
        devices = []
        for dev in usb_dict:
            usb_info = USBInfo(product=dev.get('product', ''),
                               vendor=dev.get('vendor', ''),
                               handle=dev.get('handle', ''))
            devices.append(usb_info)
        return devices

    def get_system_vendor_info(self):
        try:
            sys_dict = self._get_system_lshw_dict()
        except (processutils.ProcessExecutionError, OSError, ValueError) as e:
            LOG.warning('Could not retrieve vendor info from lshw: %s', e)
            sys_dict = {}

        core_dict = next(utils.find_in_lshw(sys_dict, 'core'), {})
        fw_dict = next(utils.find_in_lshw(core_dict, 'firmware'), {})

        firmware = SystemFirmware(vendor=fw_dict.get('vendor', ''),
                                  version=fw_dict.get('version', ''),
                                  build_date=fw_dict.get('date', ''))
        return SystemVendorInfo(product_name=sys_dict.get('product', ''),
                                serial_number=sys_dict.get('serial', ''),
                                manufacturer=sys_dict.get('vendor', ''),
                                firmware=firmware)

    def get_boot_info(self):
        boot_mode = 'uefi' if os.path.isdir('/sys/firmware/efi') else 'bios'
        LOG.debug('The current boot mode is %s', boot_mode)
        pxe_interface = utils.get_agent_params().get('BOOTIF')
        return BootInfo(current_boot_mode=boot_mode,
                        pxe_interface=pxe_interface)

    def erase_block_device(self, node, block_device):
        # Check if the block device is virtual media and skip the device.
        if self._is_virtual_media_device(block_device):
            LOG.info("Skipping erase of virtual media device %s",
                     block_device.name)
            return
        if self._is_linux_raid_member(block_device):
            LOG.info("Skipping erase of RAID member device %s",
                     block_device.name)
            return
        info = node.get('driver_internal_info', {})
        if self._is_read_only_device(block_device):
            if info.get('agent_erase_skip_read_only', False):
                LOG.info("Skipping erase of read-only device %s",
                         block_device.name)
                return
            else:
                msg = ('Failed to invoke erase of device %(device)s '
                       'as the device is flagged read-only, and the '
                       'conductor has not signaled this is a permitted '
                       'case.' % {'device': block_device.name})
                LOG.error(msg)
                raise errors.BlockDeviceEraseError(msg)
        # Note(TheJulia) Use try/except to capture and log the failure
        # and then revert to attempting to shred the volume if enabled.
        try:
            if self._is_nvme(block_device):

                execute_nvme_erase = info.get(
                    'agent_enable_nvme_secure_erase', True)
                if execute_nvme_erase and self._nvme_erase(block_device):
                    return
            else:
                execute_secure_erase = info.get(
                    'agent_enable_ata_secure_erase', True)
                if execute_secure_erase and self._ata_erase(block_device):
                    return
        except errors.BlockDeviceEraseError as e:
            execute_shred = info.get('agent_continue_if_secure_erase_failed')

            # NOTE(janders) While we are deprecating
            # ``driver_internal_info['agent_continue_if_ata_erase_failed']``
            # names check for both ``agent_continue_if_secure_erase_failed``
            # and ``agent_continue_if_ata_erase_failed``.
            # This is to ensure interoperability between newer Ironic Python
            # Agent images and older Ironic API services.
            # In future releases, 'False' default value needs to be added to
            # the info.get call above and the code below can be removed.
            # If we're dealing with new-IPA and old-API scenario, NVMe secure
            # erase should not be attempted due to absence of
            # ``[deploy]/enable_nvme_secure_erase`` config option so
            # ``agent_continue_if_ata_erase_failed`` is not misleading here
            # as it will only apply to ATA Secure Erase.
            if execute_shred is None:
                execute_shred = info.get('agent_continue_if_ata_erase_failed',
                                         False)

            if execute_shred:
                LOG.warning('Failed to invoke secure erase, '
                            'falling back to shred: %s', e)
            else:
                msg = ('Failed to invoke secure erase, '
                       'fallback to shred is not enabled: %s' % e)
                LOG.error(msg)
                raise errors.IncompatibleHardwareMethodError(msg)

        if self._shred_block_device(node, block_device):
            return

        msg = ('Unable to erase block device {}: device is unsupported.'
               ).format(block_device.name)
        LOG.error(msg)
        raise errors.IncompatibleHardwareMethodError(msg)

    def _list_erasable_devices(self, node):
        block_devices = self.list_block_devices_check_skip_list(
            node, include_partitions=True)
        # NOTE(coreywright): Reverse sort by device name so a partition (eg
        # sda1) is processed before it disappears when its associated disk (eg
        # sda) has its partition table erased and the kernel notified.
        block_devices.sort(key=lambda dev: dev.name, reverse=True)
        erasable_devices = []
        for dev in block_devices:
            if self._is_virtual_media_device(dev):
                LOG.info("Skipping erasure of virtual media device %s",
                         dev.name)
                continue
            if self._is_linux_raid_member(dev):
                LOG.info("Skipping erasure of RAID member device %s",
                         dev.name)
                continue
            if self._is_read_only_device(dev):
                LOG.info("Skipping erasure of read-only device %s",
                         dev.name)
                continue
            erasable_devices.append(dev)

        return erasable_devices

    def erase_devices_metadata(self, node, ports):
        """Attempt to erase the disk devices metadata.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :raises BlockDeviceEraseError: when there's an error erasing the
                block device
        :raises: ProtectedDeviceError if a device has been identified which
                 may require manual intervention due to the contents and
                 operational risk which exists as it could also be a sign
                 of an environmental misconfiguration.
        """
        erase_errors = {}
        for dev in self._list_erasable_devices(node):
            safety_check_block_device(node, dev.name)
            try:
                disk_utils.destroy_disk_metadata(dev.name, node['uuid'])
            except processutils.ProcessExecutionError as e:
                LOG.error('Failed to erase the metadata on device "%(dev)s". '
                          'Error: %(error)s', {'dev': dev.name, 'error': e})
                erase_errors[dev.name] = e

        if erase_errors:
            excpt_msg = ('Failed to erase the metadata on the device(s): %s' %
                         '; '.join(['"%s": %s' % (k, v)
                                    for k, v in erase_errors.items()]))
            raise errors.BlockDeviceEraseError(excpt_msg)

    def erase_devices_express(self, node, ports):
        """Attempt to perform time-optimised disk erasure:

        for NVMe devices, perform NVMe Secure Erase if supported. For other
        devices, perform metadata erasure

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :raises BlockDeviceEraseError: when there's an error erasing the
                block device
        :raises: ProtectedDeviceError if a device has been identified which
                 may require manual intervention due to the contents and
                 operational risk which exists as it could also be a sign
                 of an environmental misconfiguration.
        """
        erase_errors = {}
        info = node.get('driver_internal_info', {})
        if not self._list_erasable_devices:
            LOG.debug("No erasable devices have been found.")
            return
        for dev in self._list_erasable_devices(node):
            safety_check_block_device(node, dev.name)
            secure_erase_error = None
            try:
                if self._is_nvme(dev):
                    execute_nvme_erase = info.get(
                        'agent_enable_nvme_secure_erase', True)
                    if execute_nvme_erase and self._nvme_erase(dev):
                        continue
            except errors.BlockDeviceEraseError as e:
                LOG.error('Failed to securely erase device "%(dev)s". '
                          'Error: %(error)s, falling back to metadata '
                          'clean', {'dev': dev.name, 'error': e})
                secure_erase_error = e
            try:
                disk_utils.destroy_disk_metadata(dev.name, node['uuid'])
            except processutils.ProcessExecutionError as e:
                LOG.error('Failed to erase the metadata on device '
                          '"%(dev)s". Error: %(error)s',
                          {'dev': dev.name, 'error': e})
                if secure_erase_error:
                    erase_errors[dev.name] = (
                        "Secure erase failed: %s. "
                        "Fallback to metadata erase also failed: %s.",
                        secure_erase_error, e)
                else:
                    erase_errors[dev.name] = e

        if erase_errors:
            excpt_msg = ('Failed to conduct an express erase on '
                         'the device(s): %s' % '\n'.join('"%s": %s' % item
                                                         for item in
                                                         erase_errors.items()))
            raise errors.BlockDeviceEraseError(excpt_msg)

    def _find_pstore_mount_point(self):
        """Find the pstore mount point by scanning /proc/mounts.

        :returns: The pstore mount if existing, none otherwise.
        """
        with open("/proc/mounts", "r") as mounts:
            for line in mounts:
                # /proc/mounts format is: "device mountpoint fstype ..."
                m = re.match(r'^pstore (\S+) pstore', line)
                if m:
                    return m.group(1)

    def erase_pstore(self, node, ports):
        """Attempt to erase the kernel pstore.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        """
        pstore_path = self._find_pstore_mount_point()
        if not pstore_path:
            LOG.debug("No pstore found")
            return

        LOG.info("Cleaning up pstore in %s", pstore_path)
        for file in os.listdir(pstore_path):
            filepath = os.path.join(pstore_path, file)
            try:
                shutil.rmtree(filepath)
            except OSError:
                os.remove(filepath)

    def burnin_cpu(self, node, ports):
        """Burn-in the CPU

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        """
        burnin.stress_ng_cpu(node)

    def burnin_gpu(self, node, ports):
        """Burn-in the GPU

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        """
        burnin.gpu_burn(node)

    def burnin_disk(self, node, ports):
        """Burn-in the disk

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        """
        burnin.fio_disk(node)

    def burnin_memory(self, node, ports):
        """Burn-in the memory

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        """
        burnin.stress_ng_vm(node)

    def burnin_network(self, node, ports):
        """Burn-in the network

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        """
        burnin.fio_network(node)

    def _shred_block_device(self, node, block_device):
        """Erase a block device using shred.

        :param node: Ironic node info.
        :param block_device: a BlockDevice object to be erased
        :returns: True if the erase succeeds, False if it fails for any reason
        """
        info = node.get('driver_internal_info', {})
        npasses = info.get('agent_erase_devices_iterations', 1)
        args = ('shred', '--force')

        if info.get('agent_erase_devices_zeroize', True):
            args += ('--zero', )

        args += ('--verbose', '--iterations', str(npasses), block_device.name)

        try:
            utils.execute(*args)
        except (processutils.ProcessExecutionError, OSError) as e:
            LOG.error("Erasing block device %(dev)s failed with error %(err)s",
                      {'dev': block_device.name, 'err': e})
            return False

        return True

    def _is_virtual_media_device(self, block_device):
        """Check if the block device corresponds to Virtual Media device.

        :param block_device: a BlockDevice object
        :returns: True if it's a virtual media device, else False
        """
        vm_device_label = '/dev/disk/by-label/ir-vfd-dev'
        if os.path.exists(vm_device_label):
            link = os.readlink(vm_device_label)
            device = os.path.normpath(os.path.join(os.path.dirname(
                                                   vm_device_label), link))
            if block_device.name == device:
                return True
        return False

    def _is_linux_raid_member(self, block_device):
        """Check if a block device is a Linux RAID member.

        :param block_device: a BlockDevice object
        :returns: True if it's Linux RAID member (or if we do not
                  manage to verify), False otherwise.
        """
        try:
            # Don't use the '--nodeps' of lsblk to also catch the
            # parent device of partitions which are RAID members.
            out, _ = utils.execute('lsblk', '--fs', '--noheadings',
                                   block_device.name)
        except processutils.ProcessExecutionError as e:
            LOG.warning("Could not determine if %(name)s is a RAID member: "
                        "%(err)s",
                        {'name': block_device.name, "err": e})
            return True

        return 'linux_raid_member' in out

    def _is_read_only_device(self, block_device, partition=False):
        """Check if a block device is read-only.

        Checks the device read-only flag in order to identify virtual
        and firmware driven devices that block write device access.

        :param block_device: a BlockDevice object
        :param partition: if True, this device is a partition
        :returns: True if the device is read-only.
        """
        try:
            dev_name = os.path.basename(block_device.name)
            if partition:
                # Check the base device
                dev_name = dev_name.rstrip(string.digits)

            with open('/sys/block/%s/ro' % dev_name, 'r') as f:
                flag = f.read().strip()
                if flag == '1':
                    return True
        except IOError as e:
            # Check underlying device as the file may exist there
            if (not partition and dev_name[-1].isdigit()
                and 'nvme' not in dev_name):
                return self._is_read_only_device(block_device, partition=True)

            LOG.warning("Could not determine if %(name)s is a"
                        "read-only device. Error: %(err)s",
                        {'name': block_device.name, 'err': e})
        return False

    def _get_ata_security_lines(self, block_device):
        output = utils.execute('hdparm', '-I', block_device.name)[0]

        if '\nSecurity: ' not in output:
            return []

        # Get all lines after the 'Security: ' line
        security_and_beyond = output.split('\nSecurity: \n')[1]
        security_and_beyond_lines = security_and_beyond.split('\n')

        security_lines = []
        for line in security_and_beyond_lines:
            if line.startswith('\t'):
                security_lines.append(line.strip().replace('\t', ' '))
            else:
                break

        return security_lines

    def _smartctl_security_check(self, block_device):
        """Checks if we can query security via smartctl.

            :param block_device: A block_device object

            :returns: True if we can query the block device via ATA
                      or the smartctl binary is not present.
                      False if we cannot query the device.
        """
        try:
            # NOTE(TheJulia): smartctl has a concept of drivers being how
            # to query or interpret data from the device. We want to use `ata`
            # instead of `scsi` or `sat` as smartctl will not be able to read
            # a bridged device that it doesn't understand, and accordingly
            # return an error code.
            output = utils.execute('smartctl', '-d', 'ata',
                                   block_device.name, '-g', 'security',
                                   check_exit_code=[0, 127])[0]
            if 'Unavailable' in output:
                # Smartctl is reporting it is unavailable, lets return false.
                LOG.debug('Smartctl has reported that security is '
                          'unavailable on device %s.', block_device.name)
                return False
            return True
        except processutils.ProcessExecutionError:
            # Things don't look so good....
            LOG.warning('Refusing to permit ATA Secure Erase as direct '
                        'ATA commands via the `smartctl` utility with device '
                        '%s do not succeed.', block_device.name)
            return False
        except OSError as e:
            # Processutils can raise OSError if a path is not found,
            # and it is okay that we tollerate that since it was the
            # prior behavior.
            LOG.warning('Unable to execute `smartctl` utility: %s', e)
            return True

    def _ata_erase(self, block_device):

        def __attempt_unlock_drive(block_device, security_lines=None):
            # Attempt to unlock the drive in the event it has already been
            # locked by a previous failed attempt. We try the empty string as
            # versions of hdparm < 9.51, interpreted NULL as the literal
            # string, "NULL", as opposed to the empty string.
            if not security_lines:
                security_lines = self._get_ata_security_lines(block_device)
            unlock_passwords = ['NULL', '']
            for password in unlock_passwords:
                if 'not locked' in security_lines:
                    break
                try:
                    utils.execute('hdparm', '--user-master', 'u',
                                  '--security-unlock', password,
                                  block_device.name)
                except processutils.ProcessExecutionError as e:
                    LOG.info('Security unlock failed for device '
                             '%(name)s using password "%(password)s": %(err)s',
                             {'name': block_device.name,
                              'password': password,
                              'err': e})
                security_lines = self._get_ata_security_lines(block_device)
            return security_lines

        security_lines = self._get_ata_security_lines(block_device)

        # If secure erase isn't supported return False so erase_block_device
        # can try another mechanism. Below here, if secure erase is supported
        # but fails in some way, error out (operators of hardware that supports
        # secure erase presumably expect this to work).
        if (not self._smartctl_security_check(block_device)
                or 'supported' not in security_lines):
            return False

        # At this point, we could be SEC1,2,4,5,6

        if 'not frozen' not in security_lines:
            # In SEC2 or 6
            raise errors.BlockDeviceEraseError(
                ('Block device {} is frozen and cannot be erased'
                 ).format(block_device.name))

        # At this point, we could be in SEC1,4,5
        # Attempt to unlock the drive if it has failed in a prior attempt.
        security_lines = __attempt_unlock_drive(block_device, security_lines)

        # If the unlock failed we will still be in SEC4, otherwise, we will be
        # in SEC1 or SEC5

        if 'not locked' not in security_lines:
            # In SEC4
            raise errors.BlockDeviceEraseError(
                ('Block device {} already has a security password set'
                 ).format(block_device.name))

        # At this point, we could be in SEC1 or 5
        if 'not enabled' in security_lines:
            # SEC1. Try to transition to SEC5 by setting empty user
            # password.
            try:
                utils.execute('hdparm', '--user-master', 'u',
                              '--security-set-pass', 'NULL',
                              block_device.name)
            except processutils.ProcessExecutionError as e:
                error_msg = ('Security password set failed for device '
                             '{name}: {err}'
                             ).format(name=block_device.name, err=e)
                raise errors.BlockDeviceEraseError(error_msg)

        # Use the 'enhanced' security erase option if it's supported.
        erase_option = '--security-erase'
        if 'not supported: enhanced erase' not in security_lines:
            erase_option += '-enhanced'

        try:
            utils.execute('hdparm', '--user-master', 'u', erase_option,
                          'NULL', block_device.name)
        except processutils.ProcessExecutionError as e:
            # NOTE(TheJulia): Attempt unlock to allow fallback to shred
            # to occur, otherwise shred will fail as well, as the security
            # mode will prevent IO operations to the disk.
            __attempt_unlock_drive(block_device)
            raise errors.BlockDeviceEraseError('Erase failed for device '
                                               '%(name)s: %(err)s' %
                                               {'name': block_device.name,
                                                'err': e})

        # Verify that security is now 'not enabled'
        security_lines = self._get_ata_security_lines(block_device)
        if 'not enabled' not in security_lines:
            # Not SEC1 - fail
            raise errors.BlockDeviceEraseError(
                ('An unknown error occurred erasing block device {}'
                 ).format(block_device.name))

        # In SEC1 security state
        return True

    def _is_nvme(self, block_device):
        """Check if a block device is a NVMe.

        Checks if the device name indicates that it is an NVMe drive.

        :param block_device: a BlockDevice object
        :returns: True if the device is an NVMe, False if it is not.
        """

        return block_device.name.startswith("/dev/nvme")

    def _nvme_erase(self, block_device):
        """Attempt to clean the NVMe using the most secure supported method

        :param block_device: a BlockDevice object
        :returns: True if cleaning operation succeeded, False if it failed
        :raises: BlockDeviceEraseError
        """

        # check if crypto format is supported
        try:
            LOG.debug("Attempting to fetch NVMe capabilities for device %s",
                      block_device.name)
            nvme_info, _e = utils.execute('nvme', 'id-ctrl',
                                          block_device.name, '-o', 'json')
            nvme_info = json.loads(nvme_info)

        except processutils.ProcessExecutionError as e:
            msg = (("Failed to fetch NVMe capabilities for device {}: {}")
                   .format(block_device, e))
            LOG.error(msg)
            raise errors.BlockDeviceEraseError(msg)

        # execute format with crypto option (ses=2) if supported
        # if crypto is unsupported use user-data erase (ses=1)
        if nvme_info:
            # Check if the device supports NVMe format at all. This info
            # is in "oacs" section of nvme-cli id-ctrl output. If it does,
            # set format mode to 1 (this is passed as -s <mode> parameter
            # to nvme-cli later)
            fmt_caps = nvme_info['oacs']
            if fmt_caps & NVME_CLI_FORMAT_SUPPORTED_FLAG:
                # Given the device supports format, check if crypto
                # erase format mode is supported and pass it to nvme-cli
                # instead
                crypto_caps = nvme_info['fna']
                if crypto_caps & NVME_CLI_CRYPTO_FORMAT_SUPPORTED_FLAG:
                    format_mode = 2     # crypto erase
                else:
                    format_mode = 1     # user-data erase
            else:
                msg = ('nvme-cli did not return any supported format modes '
                       'for device: {device}').format(
                    device=block_device.name)
                LOG.error(msg)
                raise errors.BlockDeviceEraseError(msg)
        else:
            # If nvme-cli output is empty, raise an exception
            msg = ('nvme-cli did not return any information '
                   'for device: {device}').format(device=block_device.name)
            LOG.error(msg)
            raise errors.BlockDeviceEraseError(msg)

        try:
            LOG.debug("Attempting to nvme-format %s using secure format mode "
                      "(ses) %s", block_device.name, format_mode)
            utils.execute('nvme', 'format', block_device.name, '-s',
                          format_mode, '-f')
            LOG.info("nvme-cli format for device %s (ses= %s ) completed "
                     "successfully.", block_device.name, format_mode)
            return True

        except processutils.ProcessExecutionError as e:
            msg = (("Failed to nvme format device {}: {}"
                    ).format(block_device, e))
            raise errors.BlockDeviceEraseError(msg)

    def get_bmc_address(self):
        """Attempt to detect BMC IP address

        :returns: IP address of lan channel or 0.0.0.0 in case none of them is
                 configured properly
        """
        if not self.any_ipmi_device_exists():
            return None

        try:
            # From all the channels 0-15, only 1-11 can be assigned to
            # different types of communication media and protocols and
            # effectively used
            for channel in range(1, 12):
                out, e = utils.execute(
                    "ipmitool lan print {} | awk '/IP Address[ \\t]*:/"
                    " {{print $4}}'".format(channel), shell=True)
                if e.startswith("Invalid channel"):
                    continue
                out = out.strip()

                try:
                    ipaddress.ip_address(out)
                except ValueError as exc:
                    LOG.warning('Invalid IP address %(output)s: %(exc)s',
                                {'output': out, 'exc': exc})
                    continue

                # In case we get 0.0.0.0 on a valid channel, we need to keep
                # querying
                if out != '0.0.0.0':
                    return out

        except (processutils.ProcessExecutionError, OSError) as e:
            # Not error, because it's normal in virtual environment
            LOG.warning("Cannot get BMC address: %s", e)
            return

        return '0.0.0.0'

    def get_bmc_mac(self):
        """Attempt to detect BMC MAC address

        :returns: MAC address of the first LAN channel or 00:00:00:00:00:00 in
                 case none of them has one or is configured properly
        :raises: IncompatibleHardwareMethodError if no valid mac is found.
        """
        if not self.any_ipmi_device_exists():
            return None

        try:
            # From all the channels 0-15, only 1-11 can be assigned to
            # different types of communication media and protocols and
            # effectively used
            for channel in range(1, 12):
                out, e = utils.execute(
                    "ipmitool lan print {} | awk '/(IP|MAC) Address[ \\t]*:/"
                    " {{print $4}}'".format(channel), shell=True)
                if e.startswith("Invalid channel"):
                    continue

                try:
                    ip, mac = out.strip().split("\n")
                except ValueError:
                    LOG.warning('Invalid ipmitool output %(output)s',
                                {'output': out})
                    continue

                if ip == "0.0.0.0":
                    # Check if we have IPv6 address configured
                    out, e = utils.execute(
                        "ipmitool lan6 print {} | awk '/^IPv6"
                        " (Dynamic|Static) Address [0-9]+:/"
                        " {{in_section=1; next}} /^IPv6 / {{in_section=0}}"
                        " in_section && /Address:/ {{print $2}}'".
                        format(channel), shell=True)
                    if e.startswith("Invalid channel"):
                        continue

                    valid_ipv6_found = False
                    try:
                        ipv6_list = out.strip().split("\n")
                        # Skip auto-configured link-local addresses
                        # and ignore "::/255", which indicates unconfigured
                        # addresses returned by ipmitool.
                        valid_ipv6_found = any(
                            not ipv6.startswith("::")
                            and not ipv6.startswith("fe80")
                            for ipv6 in ipv6_list
                        )
                    except ValueError:
                        LOG.warning('Invalid ipmitool output %(output)s',
                                    {'output': out})
                        continue

                    if not valid_ipv6_found:
                        continue

                if not re.match("^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", mac, re.I):
                    LOG.warning('Invalid MAC address %(output)s',
                                {'output': mac})
                    continue

                # In case we get 00:00:00:00:00:00 on a valid channel, we need
                # to keep querying
                if mac != '00:00:00:00:00:00':
                    return mac

        except (processutils.ProcessExecutionError, OSError) as e:
            # Not error, because it's normal in virtual environment
            LOG.warning("Cannot get BMC MAC address: %s", e)
            return

        # no valid mac found, signal this clearly
        raise errors.IncompatibleHardwareMethodError()

    def get_bmc_v6address(self):
        """Attempt to detect BMC v6 address

        :returns: IPv6 address of lan channel or ::/0 in case none of them is
                 configured properly. May return None value if it cannot
                 interact with system tools or critical error occurs.
        """
        if not self.any_ipmi_device_exists():
            return None

        null_address_re = re.compile(r'^::(/\d{1,3})*$')

        def get_addr(channel, dynamic=False):
            cmd = "ipmitool lan6 print {} {}_addr".format(
                channel, 'dynamic' if dynamic else 'static')
            try:
                out, exc = utils.execute(cmd, shell=True)
            except processutils.ProcessExecutionError:
                return

            # NOTE: More likely ipmitool was not intended to return
            #       stdout in yaml format. Fortunately, output of
            #       dynamic_addr and static_addr commands is a valid yaml.
            try:
                out = yaml.safe_load(out.strip())
            except yaml.YAMLError as ex:
                LOG.warning('Cannot process output of "%(cmd)s" '
                            'command: %(e)s', {'cmd': cmd, 'e': ex})
                return

            for addr_dict in out.values():
                address = addr_dict['Address']
                if dynamic:
                    enabled = addr_dict['Source/Type'] in ['DHCPv6', 'SLAAC']
                else:
                    enabled = addr_dict['Enabled']

                if addr_dict['Status'] == 'active' and enabled \
                        and not null_address_re.match(address):
                    return address

        try:
            # From all the channels 0-15, only 1-11 can be assigned to
            # different types of communication media and protocols and
            # effectively used
            for channel in range(1, 12):
                addr_mode, e = utils.execute(
                    r"ipmitool lan6 print {} enables | "
                    r"awk '/IPv6\/IPv4 Addressing Enables[ \t]*:/"
                    r"{{print $NF}}'".format(channel), shell=True)
                if addr_mode.strip() not in ['ipv6', 'both']:
                    continue

                address = get_addr(channel, dynamic=True) or get_addr(channel)
                if not address:
                    continue

                try:
                    return str(ipaddress.ip_interface(address).ip)
                except ValueError as exc:
                    LOG.warning('Invalid IP address %(addr)s: %(exception)s',
                                {'addr': address, 'exception': exc})
                    continue
        except (processutils.ProcessExecutionError, OSError) as exc:
            # Not error, because it's normal in virtual environment
            LOG.warning("Cannot get BMC v6 address: %s", exc)
            return

        return '::/0'

    def get_clean_steps(self, node, ports):
        return [
            {
                'step': 'erase_devices',
                'priority': 10,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_devices_metadata',
                'priority': 99,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_devices_express',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_pstore',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'clean_uefi_nvram',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True,
                'argsinfo': DEPLOY_CLEAN_UEFI_NVRAM_ARGSINFO,
            },
            {
                'step': 'delete_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'create_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_cpu',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_gpu',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_disk',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_memory',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_network',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
        ]

    def get_deploy_steps(self, node, ports):
        return [
            {
                'step': 'erase_devices_metadata',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
            },
            {
                'step': 'apply_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'argsinfo': RAID_APPLY_CONFIGURATION_ARGSINFO,
            },
            {
                'step': 'clean_uefi_nvram',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'argsinfo': DEPLOY_CLEAN_UEFI_NVRAM_ARGSINFO,
            },
            {
                'step': 'write_image',
                # NOTE(dtantsur): this step has to be proxied via an
                # out-of-band step with the same name, hence the priority here
                # doesn't really matter.
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
            },
            {
                'step': 'inject_files',
                'priority': CONF.inject_files_priority,
                'interface': 'deploy',
                'reboot_requested': False,
                'argsinfo': inject_files.ARGSINFO,
            },
            {
                'step': 'execute_bootc_install',
                # NOTE(TheJulia): Similar to write_image above, this step
                # has to be called directly by a driver to represent the
                # flow, hence no priority here and realistically it also
                # doesn't really matter.
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
            },
        ]

    # TODO(TheJulia): There has to be a better way, we should
    # make this less copy paste. That being said, I can also see
    # unique priorities being needed.
    def get_service_steps(self, node, ports):
        service_steps = [
            {
                'step': 'delete_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'apply_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'argsinfo': RAID_APPLY_CONFIGURATION_ARGSINFO,
            },
            {
                'step': 'create_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_cpu',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_gpu',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            # NOTE(TheJulia): Burnin disk is explicitly not carried in this
            # list because it would be destructive to data on a disk.
            # If someone needs to do that, the machine should be
            # unprovisioned.
            {
                'step': 'burnin_memory',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_network',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'write_image',
                # NOTE(dtantsur): this step has to be proxied via an
                # out-of-band step with the same name, hence the priority here
                # doesn't really matter.
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
            },
            {
                'step': 'inject_files',
                'priority': CONF.inject_files_priority,
                'interface': 'deploy',
                'reboot_requested': False,
                'argsinfo': inject_files.ARGSINFO,
            },
            {
                'step': 'execute_bootc_install',
                # NOTE(TheJulia): Similar to write_image above, this step
                # has to be called directly by a driver to represent the
                # flow, hence no priority here and realistically it also
                # doesn't really matter.
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
            },
        ]
        # TODO(TheJulia): Consider erase_devices and friends...
        return service_steps

    def clean_uefi_nvram(self, node, ports, match_patterns=None):
        """Clean UEFI NVRAM entries.

        :param node: A dictionary of the node object.
        :param ports: A list of dictionaries containing information
                      of ports for the node.
        :param match_patterns: A list of string regular expression patterns
                               where any matching entry will be deleted.
        """
        if match_patterns is None:
            match_patterns = DEFAULT_CLEAN_UEFI_NVRAM_MATCH_PATTERNS
        validation_error = ('The match_patterns must be a list of strings: '
                            '{}').format(match_patterns)
        if type(match_patterns) is not list:
            raise errors.InvalidCommandParamsError(validation_error)
        patterns = []
        for item in match_patterns:
            if not isinstance(item, str):
                raise errors.InvalidCommandParamsError(validation_error)
            try:
                patterns.append(re.compile(item, flags=re.IGNORECASE))
            except re.error:
                raise errors.InvalidCommandParamsError(validation_error)

        return efi_utils.clean_boot_records(patterns=patterns)

    def apply_configuration(self, node, ports, raid_config,
                            delete_existing=True):
        """Apply RAID configuration.

        :param node: A dictionary of the node object.
        :param ports: A list of dictionaries containing information
                      of ports for the node.
        :param raid_config: The configuration to apply.
        :param delete_existing: Whether to delete the existing configuration.
        """
        self.validate_configuration(raid_config, node)
        if delete_existing:
            self.delete_configuration(node, ports)
        return self._do_create_configuration(node, ports, raid_config)

    def create_configuration(self, node, ports):
        """Create a RAID configuration.

        Unless overwritten by a local hardware manager, this method
        will create a software RAID configuration as read from the
        node's 'target_raid_config'.

        :param node: A dictionary of the node object.
        :param ports: A list of dictionaries containing information
                      of ports for the node.
        :returns: The current RAID configuration in the usual format.
        :raises: SoftwareRAIDError if the desired configuration is not
                 valid or if there was an error when creating the RAID
                 devices.
        """
        raid_config = node.get('target_raid_config', {})
        if not raid_config:
            LOG.debug("No target_raid_config found")
            return {}

        return self._do_create_configuration(node, ports, raid_config)

    def _do_create_configuration(self, node, ports, raid_config):
        def _get_volume_names_of_existing_raids():
            list_of_raids = []
            raid_devices = list_all_block_devices(block_type='raid',
                                                  ignore_raid=False,
                                                  ignore_empty=False)
            raid_devices.extend(
                list_all_block_devices(block_type='md',
                                       ignore_raid=False,
                                       ignore_empty=False)
            )
            for raid_device in raid_devices:
                device = raid_device.name
                try:
                    utils.execute('mdadm', '--examine',
                                  device, use_standard_locale=True)
                except processutils.ProcessExecutionError as e:
                    if "No md superblock detected" in str(e):
                        continue
                volume_name = raid_utils.get_volume_name_of_raid_device(device)
                if volume_name:
                    list_of_raids.append(volume_name)
                else:
                    list_of_raids.append("unnamed_raid")
            return list_of_raids

        # No 'software' controller: do nothing. If 'controller' is
        # set to 'software' on only one of the drives, the validation
        # code will catch it.
        software_raid = False
        logical_disks = raid_config.get('logical_disks')
        software_raid_disks = []
        for logical_disk in logical_disks:
            if logical_disk.get('controller') == 'software':
                software_raid = True
                software_raid_disks.append(logical_disk)
        if not software_raid:
            LOG.debug("No Software RAID config found")
            return {}

        LOG.info("Creating Software RAID")

        # Check if the config is compliant with current limitations.
        self.validate_configuration(raid_config, node)

        # Remove any logical disk from being eligible for inclusion in the
        # RAID if it's on the skip list
        skip_list = self.get_skip_list_from_node(
            node, just_raids=True)
        rm_from_list = []
        if skip_list:
            present_raids = _get_volume_names_of_existing_raids()
            if present_raids:
                for ld in logical_disks:
                    volume_name = ld.get('volume_name', None)
                    if volume_name in skip_list \
                            and volume_name in present_raids:
                        rm_from_list.append(ld)
                        LOG.debug("Software RAID device with volume name %s "
                                  "exists and is, therefore, not going to be "
                                  "created", volume_name)
                        present_raids.remove(volume_name)
            # NOTE(kubajj): Raise an error if there is an existing software
            # RAID device that either does not have a volume name or does not
            # match one on the skip list
            if present_raids:
                msg = ("Existing Software RAID device detected that should"
                       " not")
                raise errors.SoftwareRAIDError(msg)
        logical_disks = [d for d in logical_disks if d not in rm_from_list]

        # Log the validated target_raid_configuration.
        LOG.debug("Target Software RAID configuration: %s", raid_config)

        block_devices, logical_disks = raid_utils.get_block_devices_for_raid(
            self.list_block_devices(), logical_disks)
        if not rm_from_list:
            # Make sure there are no partitions yet (or left behind).
            with_parts = []
            for dev_name in block_devices:
                try:
                    if disk_utils.list_partitions(dev_name):
                        with_parts.append(dev_name)
                except processutils.ProcessExecutionError:
                    # Presumably no partitions (or no partition table)
                    continue
            if with_parts:
                msg = ("Partitions detected on devices %s during RAID config" %
                       ', '.join(with_parts))
                raise errors.SoftwareRAIDError(msg)

        partition_table_type = utils.get_partition_table_type_from_specs(node)
        target_boot_mode = utils.get_node_boot_mode(node)

        parted_start_dict = raid_utils.create_raid_partition_tables(
            block_devices, partition_table_type, target_boot_mode)

        LOG.debug("First available sectors per devices %s", parted_start_dict)

        # Reorder logical disks so that MAX comes last if any:
        reordered_logical_disks = []
        max_disk = None
        for logical_disk in logical_disks:
            psize = logical_disk['size_gb']
            if psize == 'MAX':
                max_disk = logical_disk
            else:
                reordered_logical_disks.append(logical_disk)
        if max_disk:
            reordered_logical_disks.append(max_disk)
        logical_disks = reordered_logical_disks

        # With the partitioning below, the first partition is not
        # exactly the size_gb provided, but rather the size minus a small
        # amount (often 2048*512B=1MiB, depending on the disk geometry).
        # Easier to ignore. Another way could be to use sgdisk, which is really
        # user-friendly to compute part boundaries automatically, instead of
        # parted, then convert back to mbr table if needed and possible.

        for logical_disk in logical_disks:
            # Note: from the doc,
            # https://docs.openstack.org/ironic/latest/admin/raid.html#target-raid-configuration
            # size_gb unit is GiB

            psize = logical_disk['size_gb']
            if psize == 'MAX':
                psize = -1
            else:
                psize = int(psize)

            # NOTE(dtantsur): populated in get_block_devices_for_raid
            disk_names = logical_disk['block_devices']
            for device in disk_names:
                start = parted_start_dict[device]
                start_str, end_str, end = (
                    raid_utils.calc_raid_partition_sectors(psize, start)
                )
                try:
                    LOG.debug("Creating partition on %(dev)s: %(str)s %(end)s",
                              {'dev': device, 'str': start_str,
                               'end': end_str})

                    utils.execute('parted', device, '-s', '-a',
                                  'optimal', '--', 'mkpart', 'primary',
                                  start_str, end_str)

                except processutils.ProcessExecutionError as e:
                    msg = "Failed to create partitions on {}: {}".format(
                        device, e)
                    raise errors.SoftwareRAIDError(msg)

                utils.rescan_device(device)

                parted_start_dict[device] = end

        # Create the RAID devices. The indices mapping tracks the last used
        # partition index for each physical device.
        indices = {}
        for index, logical_disk in enumerate(logical_disks):
            raid_utils.create_raid_device(index, logical_disk, indices)

        LOG.info("Successfully created Software RAID")

        return raid_config

    def delete_configuration(self, node, ports):
        """Delete a RAID configuration.

        Unless overwritten by a local hardware manager, this method
        will delete all software RAID devices on the node.
        NOTE(arne_wiebalck): It may be worth considering to only
        delete RAID devices in the node's 'target_raid_config'. If
        that config has been lost, though, the cleanup may become
        difficult. So, for now, we delete everything we detect.

        :param node: A dictionary of the node object
        :param ports: A list of dictionaries containing information
                      of ports for the node
        """

        def _scan_raids():
            utils.execute('mdadm', '--assemble', '--scan',
                          check_exit_code=False)
            raid_devices = list_all_block_devices(block_type='raid',
                                                  ignore_raid=False,
                                                  ignore_empty=False)
            # NOTE(dszumski): Fetch all devices of type 'md'. This
            # will generally contain partitions on a software RAID
            # device, but crucially may also contain devices in a
            # broken state. See https://review.opendev.org/#/c/670807/
            # for more detail.
            raid_devices.extend(
                list_all_block_devices(block_type='md',
                                       ignore_raid=False,
                                       ignore_empty=False)
            )
            return raid_devices

        raid_devices = _scan_raids()
        skip_list = self.get_skip_list_from_node(
            node, just_raids=True)
        attempts = 0
        while attempts < 2:
            attempts += 1
            self._delete_config_pass(raid_devices, skip_list)
            raid_devices = _scan_raids()
            if not raid_devices:
                break
        else:
            msg = "Unable to clean all softraid correctly. Remaining {}".\
                format([dev.name for dev in raid_devices])
            LOG.error(msg)
            raise errors.SoftwareRAIDError(msg)

    def _delete_config_pass(self, raid_devices, skip_list):
        all_holder_disks = []
        do_not_delete_devices = set()
        delete_partitions = {}
        for raid_device in raid_devices:
            do_not_delete = False
            volume_name = raid_utils.get_volume_name_of_raid_device(
                raid_device.name)
            if volume_name:
                LOG.info("Software RAID device %(dev)s has volume name"
                         "%(name)s", {'dev': raid_device.name,
                                      'name': volume_name})
                if skip_list and volume_name in skip_list:
                    LOG.warning("RAID device %s will not be deleted",
                                raid_device.name)
                    do_not_delete = True
            component_devices = get_component_devices(raid_device.name)
            if not component_devices:
                # A "Software RAID device" without components is usually
                # a partition on an md device (as, for instance, created
                # by the conductor for the config drive). This will be
                # cleaned with the hosting md device.
                LOG.info("Software RAID cleaning is skipping "
                         "partition %s", raid_device.name)
                continue
            holder_disks = get_holder_disks(raid_device.name)

            if do_not_delete:
                LOG.warning("Software RAID device %(dev)s is not going to be "
                            "deleted as its volume name - %(vn)s - is on the "
                            "skip list", {'dev': raid_device.name,
                                          'vn': volume_name})
            else:
                LOG.info("Deleting Software RAID device %s", raid_device.name)
            LOG.debug('Found component devices %s', component_devices)
            LOG.debug('Found holder disks %s', holder_disks)

            if not do_not_delete:
                # Remove md devices.
                try:
                    utils.execute('wipefs', '-af', raid_device.name)
                except processutils.ProcessExecutionError as e:
                    LOG.warning('Failed to wipefs %(device)s: %(err)s',
                                {'device': raid_device.name, 'err': e})
                try:
                    utils.execute('mdadm', '--stop', raid_device.name)
                except processutils.ProcessExecutionError as e:
                    LOG.warning('Failed to stop %(device)s: %(err)s',
                                {'device': raid_device.name, 'err': e})

                # Remove md metadata from component devices.
                for component_device in component_devices:
                    try:
                        utils.execute('mdadm', '--examine',
                                      component_device,
                                      use_standard_locale=True)
                    except processutils.ProcessExecutionError as e:
                        if "No md superblock detected" in str(e):
                            # actually not a component device
                            continue
                        else:
                            msg = "Failed to examine device {}: {}".format(
                                  component_device, e)
                            raise errors.SoftwareRAIDError(msg)

                    LOG.debug('Deleting md superblock on %s', component_device)
                    try:
                        utils.execute('mdadm', '--zero-superblock',
                                      component_device)
                    except processutils.ProcessExecutionError as e:
                        LOG.warning('Failed to remove superblock from'
                                    '%(device)s: %(err)s',
                                    {'device': raid_device.name, 'err': e})
                    if skip_list:
                        dev, part = utils.split_device_and_partition_number(
                            component_device)
                        if dev in delete_partitions:
                            delete_partitions[dev].append(part)
                        else:
                            delete_partitions[dev] = [part]
            else:
                for component_device in component_devices:
                    do_not_delete_devices.add(component_device)

            # NOTE(arne_wiebalck): We cannot delete the partitions right
            # away since there may be other partitions on the same disks
            # which are members of other RAID devices. So we remember them
            # for later.
            all_holder_disks.extend(holder_disks)
            if do_not_delete:
                LOG.warning("Software RAID device %s was not deleted",
                            raid_device.name)
            else:
                LOG.info('Deleted Software RAID device %s', raid_device.name)

        # Remove all remaining raid traces from any drives, in case some
        # drives or partitions have been member of some raid once

        # TBD: should we consider all block devices by default, but still
        # provide some 'control' through the node information
        # (for example target_raid_config at the time of calling this). This
        # may make sense if you do not want the delete_config to touch some
        # drives, like cinder volumes locally attached, for example, or any
        # kind of 'non-ephemeral' drive that you do not want to consider during
        # deployment (= specify which drives to consider just like create
        # configuration might consider the physical_disks parameter in a near
        # future)

        # Consider partitions first, before underlying disks, never hurts and
        # can even avoid some failures. Example to reproduce:
        # mdadm --stop /dev/md0
        # mdadm --zero-superblock /dev/block
        # mdadm: Unrecognised md component device - /dev/block
        # (mdadm -E /dev/block still returns 0 so won't be skipped for zeroing)
        # mdadm --zero-superblock /dev/block1
        # mdadm: Couldn't open /dev/block for write - not zeroing
        # mdadm -E /dev/block1: still shows superblocks
        all_blks = reversed(self.list_block_devices(include_partitions=True))
        do_not_delete_disks = set()
        for blk in all_blks:
            if blk.name in do_not_delete_devices:
                do_not_delete_disks.add(utils.extract_device(blk.name))
                continue
            if blk.name in do_not_delete_disks:
                continue
            try:
                utils.execute('mdadm', '--examine', blk.name,
                              use_standard_locale=True)
            except processutils.ProcessExecutionError as e:
                if "No md superblock detected" in str(e):
                    # actually not a component device
                    continue
                else:
                    LOG.warning("Failed to examine device %(name)s: %(err)s",
                                {'name': blk.name, 'err': e})
                    continue
            try:
                utils.execute('mdadm', '--zero-superblock', blk.name)
            except processutils.ProcessExecutionError as e:
                LOG.warning('Failed to remove superblock from'
                            '%(device)s: %(err)s',
                            {'device': blk.name, 'err': e})

        # Erase all partition tables we created
        all_holder_disks_uniq = list(
            collections.OrderedDict.fromkeys(all_holder_disks))
        for holder_disk in all_holder_disks_uniq:
            if holder_disk in do_not_delete_disks:
                # Remove just partitions not listed in keep_partitions
                del_list = delete_partitions[holder_disk]
                if del_list:
                    LOG.warning('Holder disk %(dev)s contains logical disk '
                                'on the skip list. Deleting just partitions: '
                                '%(parts)s', {'dev': holder_disk,
                                              'parts': del_list})
                    for part in del_list:
                        utils.execute('parted', holder_disk, 'rm', part)
                else:
                    LOG.warning('Holder disk %(dev)s contains only logical '
                                'disk(s) on the skip list', holder_disk)
                continue
            LOG.info('Removing partitions on holder disk %s', holder_disk)
            try:
                utils.execute('wipefs', '-af', holder_disk)
            except processutils.ProcessExecutionError as e:
                LOG.warning('Failed to remove partitions on %s: %s',
                            holder_disk, e)

        LOG.debug("Finished deleting Software RAID(s)")

    def validate_configuration(self, raid_config, node):
        """Validate a (software) RAID configuration

        Validate a given raid_config, in particular with respect to
        the limitations of the current implementation of software
        RAID support.

        :param raid_config: The current RAID configuration in the usual format.
        """
        LOG.debug("Validating Software RAID config: %s", raid_config)

        if not raid_config:
            LOG.error("No RAID config passed")
            return False

        logical_disks = raid_config.get('logical_disks')
        if not logical_disks:
            msg = "RAID config contains no logical disks"
            raise errors.SoftwareRAIDError(msg)

        raid_errors = []

        # Only one or two RAID devices are supported for now.
        if len(logical_disks) not in [1, 2]:
            msg = ("Software RAID configuration requires one or "
                   "two logical disks")
            raid_errors.append(msg)

        volume_names = []
        # All disks need to be flagged for Software RAID
        for logical_disk in logical_disks:
            if logical_disk.get('controller') != 'software':
                msg = ("Software RAID configuration requires all logical "
                       "disks to have 'controller'='software'")
                raid_errors.append(msg)

            volume_name = logical_disk.get('volume_name')
            if volume_name is not None:
                if volume_name in volume_names:
                    msg = ("Duplicate software RAID device name %s "
                           "detected" % volume_name)
                    raid_errors.append(msg)
                else:
                    volume_names.append(volume_name)

            physical_disks = logical_disk.get('physical_disks')
            if physical_disks is not None:
                if (not isinstance(physical_disks, list)
                        or len(physical_disks) < 2):
                    msg = ("The physical_disks parameter for software RAID "
                           "must be a list with at least 2 items, each "
                           "specifying a disk in the device hints format")
                    raid_errors.append(msg)
                if any(not isinstance(item, dict) for item in physical_disks):
                    msg = ("The physical_disks parameter for software RAID "
                           "must be a list of device hints (dictionaries)")
                    raid_errors.append(msg)

        # The first RAID device needs to be RAID-1.
        if logical_disks[0]['raid_level'] != '1':
            msg = ("Software RAID Configuration requires RAID-1 for the "
                   "first logical disk")
            raid_errors.append(msg)

        # Additional checks when we have two RAID devices.
        if len(logical_disks) == 2:
            size1 = logical_disks[0]['size_gb']
            size2 = logical_disks[1]['size_gb']

            # Only one logical disk is allowed to span the whole device.
            # FIXME(dtantsur): this logic is not correct when logical disks use
            # different physical devices.
            if size1 == 'MAX' and size2 == 'MAX':
                msg = ("Software RAID can have only one RAID device with "
                       "size 'MAX'")
                raid_errors.append(msg)

            # Check the accepted RAID levels.
            current_level = logical_disks[1]['raid_level']
            if current_level not in SUPPORTED_SOFTWARE_RAID_LEVELS:
                msg = ("Software RAID configuration does not support "
                       "RAID level %s" % current_level)
                raid_errors.append(msg)
            physical_device_count = len(self.list_block_devices())
            if current_level == '5' and physical_device_count < 3:
                msg = ("Software RAID configuration is not possible for "
                       "RAID level 5 with only %s block devices found."
                       % physical_device_count)
                raid_errors.append(msg)
            if current_level == '6' and physical_device_count < 4:
                msg = ("Software RAID configuration is not possible for "
                       "RAID level 6 with only %s block devices found."
                       % physical_device_count)
                raid_errors.append(msg)
        if raid_errors:
            error = ('Could not validate Software RAID config for %(node)s: '
                     '%(errors)s') % {'node': node['uuid'],
                                      'errors': '; '.join(raid_errors)}
            raise errors.SoftwareRAIDError(error)

    def write_image(self, node, ports, image_info, configdrive=None):
        """A deploy step to write an image.

        Downloads and writes an image to disk if necessary. Also writes a
        configdrive to disk if the configdrive parameter is specified.

        :param node: A dictionary of the node object
        :param ports: A list of dictionaries containing information
                      of ports for the node
        :param image_info: Image information dictionary.
        :param configdrive: A string containing the location of the config
                            drive as a URL OR the contents (as gzip/base64)
                            of the configdrive. Optional, defaults to None.
        """
        ext = ext_base.get_extension('standby')
        cmd = ext.prepare_image(image_info=image_info, configdrive=configdrive)
        # The result is asynchronous, wait here.
        return cmd.wait()

    def execute_bootc_install(self, node, ports, image_source, configdrive,
                              oci_pull_secret):
        """Deploy a container using bootc install.

        Downloads, runs, and leverages bootc install to deploy the desired
        container to the disk using bootc and writes any configuration
        drive to the disk if necessary.

        :param node: A dictionary of the node object
        :param ports: A list of dictionaries containing information
                      of ports for the node
        :param image_info: Image information dictionary.
        :param configdrive: A string containing the location of the config
                            drive as a URL OR the contents (as gzip/base64)
                            of the configdrive. Optional, defaults to None.
        :param oci_pull_secret: The base64 encoded pull secret to utilize
                                to retrieve the user requested container.
        """
        ext = ext_base.get_extension('standby')
        cmd = ext.execute_bootc_install(
            image_source=image_source,
            instance_info=node.get('instance_info'),
            pull_secret=oci_pull_secret,
            configdrive=configdrive)
        # The result is asynchronous, wait here.
        return cmd.wait()

    def generate_tls_certificate(self, ip_address):
        """Generate a TLS certificate for the IP address."""
        return tls_utils.generate_tls_certificate(ip_address)

    def inject_files(self, node, ports, files=None, verify_ca=True):
        """A deploy step to inject arbitrary files.

        :param node: A dictionary of the node object
        :param ports: A list of dictionaries containing information
                      of ports for the node (unused)
        :param files: See :py:mod:`inject_files`
        :param verify_ca: Whether to verify TLS certificate.
        """
        return inject_files.inject_files(node, ports, files, verify_ca)

    def collect_system_logs(self, io_dict, file_list):
        commands = {
            'df': ['df', '-a'],
            'dmesg': ['dmesg'],
            'iptables': ['iptables', '-L'],
            'ip_addr': ['ip', 'addr'],
            'lsblk': ['lsblk', '--all',
                      '-o%s' % ','.join(utils.LSBLK_COLUMNS)],
            'lsblk-full': ['lsblk', '--all', '--bytes',
                           '--output-all', '--pairs'],
            'lshw': ['lshw', '-quiet', '-json'],
            'mdstat': ['cat', '/proc/mdstat'],
            'mount': ['mount'],
            'multipath': ['multipath', '-ll'],
            'parted': ['parted', '-l'],
            'ps': ['ps', 'au'],
        }
        for name, cmd in commands.items():
            utils.try_collect_command_output(io_dict, name, cmd)

        _collect_udev(io_dict)

    def full_sync(self):
        LOG.debug('Flushing file system buffers')
        try:
            utils.execute('sync')
        except processutils.ProcessExecutionError as e:
            error_msg = f'Flushing file system buffers failed: {e}'
            LOG.error(error_msg)
            # If sync fails, the machine is probably in a bad state and we
            # better not continue.
            raise errors.CommandExecutionError(error_msg)

        LOG.debug('Flushing device caches')
        try:
            # https://www.kernel.org/doc/Documentation/sysctl/vm.txt
            with open('/proc/sys/vm/drop_caches', 'wb') as fp:
                fp.write(b'3')
        except OSError as e:
            LOG.warning('Unable to tell the kernel to drop caches: %s', e)

        for blkdev in dispatch_to_managers('list_block_devices'):
            try:
                utils.execute('blockdev', '--flushbufs', blkdev.name)
            except (processutils.ProcessExecutionError, OSError) as e:
                LOG.warning('Cannot flush buffers of device %s: %s',
                            blkdev.name, e)


def _collect_udev(io_dict):
    """Collect device properties from udev."""
    try:
        out, _e = utils.execute('lsblk', '-no', 'KNAME')
    except processutils.ProcessExecutionError as exc:
        LOG.warning('Could not list block devices: %s', exc)
        return

    context = pyudev.Context()

    for kname in out.splitlines():
        kname = kname.strip()
        if not kname:
            continue

        name = os.path.join('/dev', kname)

        try:
            udev = pyudev.Devices.from_device_file(context, name)
        except Exception as e:
            LOG.warning("Device %(dev)s is inaccessible, skipping... "
                        "Error: %(error)s", {'dev': name, 'error': e})
            continue

        try:
            props = dict(udev.properties)
        except AttributeError:  # pyudev < 0.20
            props = dict(udev)

        fp = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        json.dump(props, fp)
        buf = fp.detach()
        buf.seek(0)
        io_dict[f'udev/{kname}'] = buf


def _compare_managers(hwm1, hwm2):
    return hwm2['support'] - hwm1['support']


def _get_extensions():
    return stevedore.ExtensionManager(
        namespace='ironic_python_agent.hardware_managers',
        invoke_on_load=True
    )


def get_managers():
    """Get a list of hardware managers in priority order.

    This exists as a backwards compatibility shim, returning a simple list
    of managers where expected. New usages should use get_managers_detail.

    :returns: Priority-sorted list of hardware managers
    :raises HardwareManagerNotFound: if no valid hardware managers found
    """
    return [hwm['manager'] for hwm in get_managers_detail()]


def get_managers_detail():
    """Get detailed information about hardware managers

    Use stevedore to find all eligible hardware managers, sort them based on
    self-reported (via evaluate_hardware_support()) priorities, and return a
    dict containing the manager object, it's class name, and hardware support
    value. The resulting list is cached in _global_managers.

    :returns: list of dictionaries representing hardware managers and metadata
    :raises HardwareManagerNotFound: if no valid hardware managers found
    """
    global _global_managers

    if not _global_managers:

        preferred_managers = []

        for extension in _get_extensions():
            hwm = extension.obj
            hardware_support = hwm.evaluate_hardware_support()
            if hardware_support > 0:
                preferred_managers.append({
                    'name': hwm.__class__.__name__,
                    'manager': hwm,
                    'support': hardware_support
                })
                LOG.info('Hardware manager found: %s',
                         extension.entry_point_target)

        if not preferred_managers:
            raise errors.HardwareManagerNotFound

        hwms = sorted(preferred_managers,
                      key=functools.cmp_to_key(_compare_managers))

        _global_managers = hwms

    return _global_managers


def dispatch_to_all_managers(method, *args, **kwargs):
    """Dispatch a method to all hardware managers.

    Dispatches the given method in priority order as sorted by
    `get_managers`. If the method doesn't exist or raises
    IncompatibleHardwareMethodError, it continues to the next hardware manager.
    All managers that have hardware support for this node will be called,
    and their responses will be added to a dictionary of the form
    {HardwareManagerClassName: response}.

    :param method: hardware manager method to dispatch
    :param args: arguments to dispatched method
    :param kwargs: keyword arguments to dispatched method
    :raises errors.HardwareManagerMethodNotFound: if all managers raise
        IncompatibleHardwareMethodError.
    :returns: a dictionary with keys for each hardware manager that returns
        a response and the value as a list of results from that hardware
        manager.
    """
    responses = {}
    managers = get_managers()
    for manager in managers:
        if getattr(manager, method, None):
            try:
                response = getattr(manager, method)(*args, **kwargs)
            except errors.IncompatibleHardwareMethodError:
                LOG.debug('HardwareManager %(manager)s does not '
                          'support %(method)s',
                          {'manager': manager, 'method': method})
                continue
            except Exception as e:
                LOG.exception('Unexpected error dispatching %(method)s to '
                              'manager %(manager)s: %(e)s',
                              {'method': method, 'manager': manager, 'e': e})
                raise
            responses[manager.__class__.__name__] = response
        else:
            LOG.debug('HardwareManager %(manager)s does not '
                      'have method %(method)s',
                      {'manager': manager, 'method': method})

    if responses == {}:
        raise errors.HardwareManagerMethodNotFound(method)

    return responses


def dispatch_to_managers(method, *args, **kwargs):
    """Dispatch a method to best suited hardware manager.

    Dispatches the given method in priority order as sorted by
    `get_managers`. If the method doesn't exist or raises
    IncompatibleHardwareMethodError, it is attempted again with a more generic
    hardware manager. This continues until a method executes that returns
    any result without raising an IncompatibleHardwareMethodError.

    :param method: hardware manager method to dispatch
    :param args: arguments to dispatched method
    :param kwargs: keyword arguments to dispatched method

    :returns: result of successful dispatch of method
    :raises HardwareManagerMethodNotFound: if all managers failed the method
    :raises HardwareManagerNotFound: if no valid hardware managers found
    """
    managers = get_managers()
    for manager in managers:
        if getattr(manager, method, None):
            try:
                return getattr(manager, method)(*args, **kwargs)
            except errors.IncompatibleHardwareMethodError:
                LOG.debug('HardwareManager %(manager)s does not '
                          'support %(method)s',
                          {'manager': manager, 'method': method})
            except Exception as e:
                LOG.exception('Unexpected error dispatching %(method)s to '
                              'manager %(manager)s: %(e)s',
                              {'method': method, 'manager': manager, 'e': e})
                raise
        else:
            LOG.debug('HardwareManager %(manager)s does not '
                      'have method %(method)s',
                      {'manager': manager, 'method': method})

    raise errors.HardwareManagerMethodNotFound(method)


_CACHED_HW_INFO = None


def list_hardware_info(use_cache=True):
    """List hardware information with caching."""
    global _CACHED_HW_INFO

    if _CACHED_HW_INFO is None:
        _CACHED_HW_INFO = dispatch_to_managers('list_hardware_info')
        return _CACHED_HW_INFO

    if use_cache:
        return _CACHED_HW_INFO
    else:
        return dispatch_to_managers('list_hardware_info')


def cache_node(node):
    """Store the node object in the hardware module.

    Stores the node object in the hardware module to facilitate the
    access of a node information in the hardware extensions.

    If the new node does not match the previously cached one, wait for the
    expected root device to appear.

    :param node: Ironic node object
    """
    global NODE
    new_node = NODE is None or NODE['uuid'] != node['uuid']
    NODE = node

    if new_node:
        LOG.info('Cached node %s, waiting for its root device to appear',
                 node['uuid'])
        # Root device hints, stored in the new node, can change the expected
        # root device. So let us wait for it to appear again.
        dispatch_to_managers('wait_for_disks')


def get_cached_node():
    """Guard function around the module variable NODE."""
    return NODE


def get_current_versions():
    """Fetches versions from all hardware managers.

    :returns: Dict in the format {name: version} containing one entry for
              every hardware manager.
    """
    return {version.get('name'): version.get('version')
            for version in dispatch_to_all_managers('get_version').values()}


def check_versions(provided_version=None):
    """Ensure the version of hardware managers hasn't changed.

    :param provided_version: Hardware manager versions used by ironic.
    :raises: errors.VersionMismatch if any hardware manager version on
             the currently running agent doesn't match the one stored in
             provided_version.
    :returns: None
    """
    # If the version is None, assume this is the first run
    if provided_version is None:
        return
    agent_version = get_current_versions()
    if provided_version != agent_version:
        LOG.warning('Mismatched hardware managers versions. Agent version: '
                    '%(agent)s, node version: %(node)s',
                    {'agent': agent_version, 'node': provided_version})
        raise errors.VersionMismatch(agent_version=agent_version,
                                     node_version=provided_version)


def _step_sort_key(step):
    return (-step['hwm']['support'], -step['priority'], step['hwm']['name'])


def deduplicate_steps(candidate_steps):
    """Remove duplicated clean or deploy steps

    Deduplicates steps returned from HardwareManagers to prevent running
    a given step more than once. Other than individual step priority,
    it doesn't actually impact the deployment which specific steps are kept
    and what HardwareManager they are associated with.
    However, in order to make testing easier, this method returns
    deterministic results.

    Uses the following filtering logic to decide which step "wins":

    - Keep the step that belongs to HardwareManager with highest
      HardwareSupport (larger int) value.
    - If equal support level, keep the step with the higher defined priority
      (larger int).
    - If equal support level and priority, keep the step associated with the
      HardwareManager whose name comes earlier in the alphabet.

    :param candidate_steps: A dict containing all possible steps from
        all managers, key=manager, value=list of steps
    :returns: A deduplicated dictionary of {hardware_manager: [steps]}
    """
    support = {hwm['name']: hwm['support']
               for hwm in get_managers_detail()}

    steps = collections.defaultdict(list)
    deduped_steps = collections.defaultdict(list)

    for manager, manager_steps in candidate_steps.items():
        # We cannot deduplicate steps with unknown hardware support
        for step in manager_steps:
            # build a new dict of steps that's easier to filter
            step['hwm'] = {'name': manager,
                           'support': support[manager]}
            steps[step['step']].append(step)

    for step_name, step_list in steps.items():
        winning_step = sorted(step_list, key=_step_sort_key)[0]
        # Remove extra metadata we added to the step for filtering
        manager = winning_step.pop('hwm')['name']
        # Add winning step to deduped_steps
        deduped_steps[manager].append(winning_step)

    return deduped_steps


def get_multipath_status():
    """Return the status of multipath initialization."""
    # NOTE(TheJulia): Provides a nice place to mock out and simplify testing
    # as if we directly try and work with the global var, we will be racing
    # tests endlessly.
    return MULTIPATH_ENABLED


def safety_check_block_device(node, device):
    """Performs safety checking of a block device before destroying.

    In order to guard against destruction of file systems such as
    shared-disk file systems
    (https://en.wikipedia.org/wiki/Clustered_file_system#SHARED-DISK)
    or similar filesystems where multiple distinct computers may have
    unlocked concurrent IO access to the entire block device or
    SAN Logical Unit Number, we need to evaluate, and block cleaning
    from occurring on these filesystems *unless* we have been explicitly
    configured to do so.

    This is because cleaning is an intentionally destructive operation,
    and once started against such a device, given the complexities of
    shared disk clustered filesystems where concurrent access is a design
    element, in all likelihood the entire cluster can be negatively
    impacted, and an operator will be forced to recover from snapshot and
    or backups of the volume's contents.

    :param node: A node, or cached node object.
    :param device: String representing the path to the block
                   device to be checked.
    :raises: ProtectedDeviceError when a device is identified with
             one of these known clustered filesystems, and the overall
             settings have not indicated for the agent to skip such
             safety checks.
    """

    # NOTE(TheJulia): While this seems super rare, I found out after this
    # thread of discussion started that I have customers which have done
    # this and wiped out SAN volumes and their contents unintentionally
    # as a result of these filesystems not being guarded.
    # For those not familiar with shared disk clustered filesystems, think
    # of it as like your impacting a Ceph cluster, except your suddenly
    # removing the underlying disks from the OSD, and the entire cluster
    # goes down.

    if not CONF.guard_special_filesystems:
        return
    di_info = node.get('driver_internal_info', {})
    if not di_info.get('wipe_special_filesystems', True):
        return
    lsblk_ids = ['UUID', 'PTUUID', 'PARTTYPE', 'PARTUUID']
    report = utils.execute('lsblk', '-bia', '--json',
                           '-o{}'.format(','.join(lsblk_ids)),
                           device, check_exit_code=[0])[0]

    try:
        report_json = json.loads(report)
    except json.decoder.JSONDecodeError as ex:
        LOG.error("Unable to decode lsblk output, invalid JSON: %s", ex)

    device_json = report_json['blockdevices'][0]
    identified_fs_types = []
    identified_ids = []

    fstype = device_json.get('fstype')
    identified_fs_types.append(fstype)
    for key in lsblk_ids:
        identified_ids.append(device_json.get(key.lower()))

    _check_for_special_partitions_filesystems(
        device,
        identified_ids,
        identified_fs_types)


def _check_for_special_partitions_filesystems(device, ids, fs_types):
    """Compare supplied IDs, Types to known items, and raise if found.

    :param device: The block device in use, specifically for logging.
    :param ids: A list above IDs found to check.
    :param fs_types: A list of FS types found to check.
    :raises: ProtectedDeviceError should a partition label or metadata
             be discovered which suggests a shared disk clustered filesystem
             has been discovered.
    """
    guarded_ids = {
        # Apparently GPFS can used shared volumes....
        '37AFFC90-EF7D-4E96-91C3-2D7AE055B174': 'IBM GPFS Partition',
        # Shared volume parallel filesystem
        'AA31E02A-400F-11DB-9590-000C2911D1B8': 'VMware VMFS Partition (GPT)',
        '0xfb': 'VMware VMFS Partition (MBR)',
    }
    for key, value in guarded_ids.items():
        for id_value in ids:
            if key == id_value:
                raise errors.ProtectedDeviceError(
                    device=device,
                    what=value)

    guarded_fs_types = {
        'gfs2': 'Red Hat Global File System 2',
    }

    for key, value in guarded_fs_types.items():
        for fs in fs_types:
            if key == fs:
                raise errors.ProtectedDeviceError(
                    device=device,
                    what=value)

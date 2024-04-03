#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import re
import sys
import tempfile

from oslo_concurrency import processutils
from oslo_log import log

from ironic_python_agent import disk_utils
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import partition_utils
from ironic_python_agent import raid_utils
from ironic_python_agent import utils


LOG = log.getLogger(__name__)


def get_partition_path_by_number(device, part_num):
    """Get partition path (/dev/something) by a partition number on device.

    Only works for GPT partition table.
    """
    uuid = None
    partinfo, _ = utils.execute('sgdisk', '-i', str(part_num), device,
                                use_standard_locale=True)
    for line in partinfo.splitlines():
        if not line.strip():
            continue

        try:
            field, value = line.rsplit(':', 1)
        except ValueError:
            LOG.warning('Invalid sgdisk line: %s', line)
            continue

        if 'partition unique guid' in field.lower():
            uuid = value.strip().lower()
            LOG.debug('GPT partition number %s on device %s has UUID %s',
                      part_num, device, uuid)
            break

    if uuid is not None:
        return partition_utils.get_partition(device, uuid)
    else:
        LOG.warning('No UUID information provided in sgdisk output for '
                    'partition %s on device %s', part_num, device)


def manage_uefi(device, efi_system_part_uuid=None):
    """Manage the device looking for valid efi bootloaders to update the nvram.

    This method checks for valid efi bootloaders in the device, if they exist
    it updates the nvram using the efibootmgr.

    :param device: the device to be checked.
    :param efi_system_part_uuid: efi partition uuid.
    :raises: DeviceNotFound if the efi partition cannot be found.
    :return: True - if it founds any efi bootloader and the nvram was updated
             using the efibootmgr.
             False - if no efi bootloader is found.
    """
    efi_partition_mount_point = None
    efi_mounted = False
    LOG.debug('Attempting UEFI loader autodetection and NVRAM record setup.')

    # Force UEFI to rescan the device.
    utils.rescan_device(device)

    # Trust the contents on the disk in the event of a whole disk image.
    efi_partition = disk_utils.find_efi_partition(device)
    if efi_partition:
        efi_part_num = efi_partition['number']
        efi_partition = get_partition_path_by_number(device, efi_part_num)

    if not efi_partition and efi_system_part_uuid:
        # get_partition returns <device>+<partition> and we only need the
        # partition number
        efi_partition = partition_utils.get_partition(
            device, uuid=efi_system_part_uuid)
        # FIXME(dtantsur): this procedure will not work for devicemapper
        # devices. To fix that we need a way to convert a UUID to a partition
        # number, which is surprisingly non-trivial and may involve looping
        # over existing numbers and calling `sgdisk -i` for each of them.
        # But I'm not sure we even need this logic: find_efi_partition should
        # be sufficient for both whole disk and partition images.
        try:
            efi_part_num = int(efi_partition.replace(device, ""))
        except ValueError:
            # NVMe Devices get a partitioning scheme that is different from
            # traditional block devices like SCSI/SATA
            try:
                efi_part_num = int(efi_partition.replace(device + 'p', ""))
            except ValueError as exc:
                # At least provide a reasonable error message if the device
                # does not follow this procedure.
                raise errors.DeviceNotFound(
                    "Cannot detect the partition number of the device %s: %s" %
                    (efi_partition, exc))

    if not efi_partition:
        # NOTE(dtantsur): we cannot have a valid EFI deployment without an
        # EFI partition at all. This code path is easily hit when using an
        # image that is not UEFI compatible (which sadly applies to most
        # cloud images out there, with a nice exception of Ubuntu).
        raise errors.DeviceNotFound(
            "No EFI partition could be detected on device %s and "
            "EFI partition UUID has not been recorded during deployment "
            "(which is often the case for whole disk images). "
            "Are you using a UEFI-compatible image?" % device)

    local_path = tempfile.mkdtemp()
    efi_partition_mount_point = os.path.join(local_path, "boot/efi")
    if not os.path.exists(efi_partition_mount_point):
        os.makedirs(efi_partition_mount_point)

    try:
        utils.execute('mount', efi_partition, efi_partition_mount_point)
        efi_mounted = True

        valid_efi_bootloaders = _get_efi_bootloaders(efi_partition_mount_point)
        if not valid_efi_bootloaders:
            # NOTE(dtantsur): if we have an empty EFI partition, try to use
            # grub-install to populate it.
            LOG.warning('Empty EFI partition detected.')
            return False

        if not hardware.is_md_device(device):
            efi_devices = [device]
            efi_partition_numbers = [efi_part_num]
            efi_label_suffix = ''
        else:
            # umount to allow for signature removal (to avoid confusion about
            # which ESP to mount once the instance is deployed)
            utils.execute('umount', efi_partition_mount_point, attempts=3,
                          delay_on_retry=True)
            efi_mounted = False

            holders = hardware.get_holder_disks(device)
            efi_md_device = raid_utils.prepare_boot_partitions_for_softraid(
                device, holders, efi_partition, target_boot_mode='uefi'
            )
            efi_devices = hardware.get_component_devices(efi_md_device)
            efi_partition_numbers = []
            _PARTITION_NUMBER = re.compile(r'(\d+)$')
            for dev in efi_devices:
                match = _PARTITION_NUMBER.search(dev)
                if match:
                    partition_number = match.group(1)
                    efi_partition_numbers.append(partition_number)
                else:
                    raise errors.DeviceNotFound(
                        "Could not extract the partition number "
                        "from %s!" % dev)
            efi_label_suffix = "(RAID, part%s)"

            # remount for _run_efibootmgr
            utils.execute('mount', efi_partition, efi_partition_mount_point)
            efi_mounted = True

        efi_dev_part = zip(efi_devices, efi_partition_numbers)
        for i, (efi_dev, efi_part) in enumerate(efi_dev_part):
            LOG.debug("Calling efibootmgr with dev %s partition number %s",
                      efi_dev, efi_part)
            if efi_label_suffix:
                # NOTE (arne_wiebalck): uniqify the labels to prevent
                # unintentional boot entry cleanup
                _run_efibootmgr(valid_efi_bootloaders, efi_dev, efi_part,
                                efi_partition_mount_point,
                                efi_label_suffix % i)
            else:
                _run_efibootmgr(valid_efi_bootloaders, efi_dev, efi_part,
                                efi_partition_mount_point)
        return True

    except processutils.ProcessExecutionError as e:
        error_msg = ('Could not configure UEFI boot on device %(dev)s: %(err)s'
                     % {'dev': device, 'err': e})
        LOG.exception(error_msg)
        raise errors.CommandExecutionError(error_msg)
    finally:
        if efi_mounted:
            try:
                utils.execute('umount', efi_partition_mount_point,
                              attempts=3, delay_on_retry=True)
            except processutils.ProcessExecutionError as e:
                error_msg = ('Umounting efi system partition failed. '
                             'Attempted 3 times. Error: %s' % e)
                LOG.error(error_msg)
                # Do not mask the actual failure, if any
                if sys.exc_info()[0] is None:
                    raise errors.CommandExecutionError(error_msg)

            else:
                try:
                    utils.execute('sync')
                except processutils.ProcessExecutionError as e:
                    LOG.warning('Unable to sync the local disks: %s', e)


# NOTE(TheJulia): Do not add bootia32.csv to this list. That is 32bit
# EFI booting and never really became popular.
BOOTLOADERS_EFI = [
    'bootx64.csv',  # Used by GRUB2 shim loader (Ubuntu, Red Hat)
    'boot.csv',  # Used by rEFInd, Centos7 Grub2
    'bootia32.efi',
    'bootx64.efi',  # x86_64 Default
    'bootia64.efi',
    'bootarm.efi',
    'bootaa64.efi',  # Arm64 Default
    'bootriscv32.efi',
    'bootriscv64.efi',
    'bootriscv128.efi',
    'grubaa64.efi',
    'winload.efi'
]


def _get_efi_bootloaders(location):
    """Get all valid efi bootloaders in a given location

    :param location: the location where it should start looking for the
                     efi files.
    :return: a list of relative paths to valid efi bootloaders or reference
             files.
    """
    # Let's find all files with .efi or .EFI extension
    LOG.debug('Looking for all efi files on %s', location)
    valid_bootloaders = []
    for root, dirs, files in os.walk(location):
        efi_files = [f for f in files if f.lower() in BOOTLOADERS_EFI]
        LOG.debug('efi files found in %(location)s : %(efi_files)s',
                  {'location': location, 'efi_files': str(efi_files)})
        for name in efi_files:
            efi_f = os.path.join(root, name)
            LOG.debug('Checking if %s is executable', efi_f)
            if os.access(efi_f, os.X_OK):
                v_bl = efi_f.split(location)[-1][1:]
                LOG.debug('%s is a valid bootloader', v_bl)
                valid_bootloaders.append(v_bl)
            if 'csv' in efi_f.lower():
                v_bl = efi_f.split(location)[-1][1:]
                LOG.debug('%s is a pointer to a bootloader', v_bl)
                # The CSV files are intended to be authortative as
                # to the bootloader and the label to be used. Since
                # we found one, we're going to point directly to it.
                # centos7 did ship with 2, but with the same contents.
                # TODO(TheJulia): Perhaps we extend this to make a list
                # of CSVs instead and only return those?! But then the
                # question is which is right/first/preferred.
                return [v_bl]
    return valid_bootloaders


# NOTE(TheJulia): regex used to identify entries in the efibootmgr
# output on stdout.
_ENTRY_LABEL = re.compile(
    r'Boot([0-9a-f-A-F]+)\*?\s+(.*?)\s+'
    r'((BBS|HD|FvFile|FvVol|PciRoot|VenMsg|VenHw|UsbClass)\(.*)$')


def get_boot_records():
    """Executes efibootmgr and returns boot records.

    :return: An iterator yielding tuples
             (boot number, boot record, root device type, device path).
    """
    # Invokes binary=True so we get a bytestream back.
    efi_output = utils.execute('efibootmgr', '-v', binary=True)
    # Bytes must be decoded before regex can be run and
    # matching to work as intended.
    # Also ignore errors on decoding, as we can basically get
    # garbage out of the nvram record, this way we don't fail
    # hard on unrelated records.
    cmd_output = efi_output[0].decode('utf-16', errors='ignore')
    for line in cmd_output.split('\n'):
        match = _ENTRY_LABEL.match(line)
        if match is not None:
            yield (match[1], match[2], match[4], match[3])


def add_boot_record(device, efi_partition, loader, label):
    """Add an EFI boot record with efibootmgr.

    :param device: the device to be used
    :param efi_partition: the number of the EFI partition on the device
    :param loader: path to the EFI boot loader
    :param label: the record label
    """
    # https://linux.die.net/man/8/efibootmgr
    utils.execute('efibootmgr', '-v', '-c', '-d', device,
                  '-p', str(efi_partition), '-w', '-L', label,
                  '-l', loader, binary=True)


def remove_boot_record(boot_num):
    """Remove an EFI boot record with efibootmgr.

    :param boot_num: the number of the boot record
    """
    utils.execute('efibootmgr', '-b', boot_num, '-B', binary=True)


def clean_boot_records(patterns):
    """Remove EFI boot records matching regex patterns.

    :param match_patterns: A list of string regular expression patterns
                            where any matching entry will be deleted.
    """

    for boot_num, entry, _, path in get_boot_records():
        for pattern in patterns:
            if pattern.search(path):
                LOG.debug('Path %s matched pattern %s, '
                          'entry will be deleted: %s',
                          path, pattern.pattern, entry)
                remove_boot_record(boot_num)
                break


def _run_efibootmgr(valid_efi_bootloaders, device, efi_partition,
                    mount_point, label_suffix=None):
    """Executes efibootmgr and removes duplicate entries.

    :param valid_efi_bootloaders: the list of valid efi bootloaders
    :param device: the device to be used
    :param efi_partition: the efi partition on the device
    :param mount_point: The mountpoint for the EFI partition so we can
                        read contents of files if necessary to perform
                        proper bootloader injection operations.
    :param label_suffix: a string to be appended to the EFI label,
                         mainly used in the case of software to uniqify
                         the entries for the md components.
    """

    # Before updating let's get information about the bootorder
    LOG.debug("Getting information about boot order.")
    boot_records = list(get_boot_records())
    label_id = 1
    for v_bl in valid_efi_bootloaders:
        if 'csv' in v_bl.lower():
            LOG.debug('A CSV file has been identified as a bootloader hint. '
                      'File: %s', v_bl)
            # These files are always UTF-16 encoded, sometimes have a header.
            # Positive bonus is python silently drops the FEFF header.
            try:
                with open(mount_point + '/' + v_bl, 'r',
                          encoding='utf-16') as csv:
                    contents = str(csv.read())
            except UnicodeError:
                with open(mount_point + '/' + v_bl, 'r',
                          encoding='utf-16-le') as csv:
                    contents = str(csv.read())
            csv_contents = contents.split(',', maxsplit=3)
            csv_filename = v_bl.split('/')[-1]
            v_efi_bl_path = v_bl.replace(csv_filename, str(csv_contents[0]))
            v_efi_bl_path = '\\' + v_efi_bl_path.replace('/', '\\')
            label = csv_contents[1]
            if label_suffix:
                label = label + " " + str(label_suffix)
        else:
            v_efi_bl_path = '\\' + v_bl.replace('/', '\\')
            label = 'ironic' + str(label_id)
            if label_suffix:
                label = label + " " + str(label_suffix)

        # Iterate through standard out, and look for duplicates
        for boot_num, boot_rec, boot_type, boot_details in boot_records:
            # Look for the base label in the string if a line match
            # occurs, so we can identify if we need to eliminate the
            # entry.
            if label == boot_rec:
                LOG.debug("Found bootnum %s matching label", boot_num)
                remove_boot_record(boot_num)

        LOG.info("Adding loader %(path)s on partition %(part)s of device "
                 " %(dev)s with label %(label)s",
                 {'path': v_efi_bl_path, 'part': efi_partition,
                  'dev': device, 'label': label})

        # Update the nvram using efibootmgr
        add_boot_record(device, efi_partition, v_efi_bl_path, label)
        # Increment the ID in case the loop runs again.
        label_id += 1

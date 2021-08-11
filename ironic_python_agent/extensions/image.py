# Copyright 2015 Red Hat, Inc.
# All Rights Reserved.
#
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
import shlex
import shutil
import stat
import tempfile

from ironic_lib import utils as ilib_utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import raid_utils
from ironic_python_agent import utils

LOG = log.getLogger(__name__)

CONF = cfg.CONF

BIND_MOUNTS = ('/dev', '/proc', '/run')

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


def _rescan_device(device):
    """Force the device to be rescanned

    :param device: device upon which to rescan and update
                   kernel partition records.
    """
    try:
        utils.execute('partx', '-u', device, attempts=3,
                      delay_on_retry=True)
        utils.execute('udevadm', 'settle')
    except processutils.ProcessExecutionError:
        LOG.warning("Couldn't re-read the partition table "
                    "on device %s", device)


def _get_partition(device, uuid):
    """Find the partition of a given device."""
    LOG.debug("Find the partition %(uuid)s on device %(dev)s",
              {'dev': device, 'uuid': uuid})

    try:
        _rescan_device(device)
        lsblk = utils.execute(
            'lsblk', '-PbioKNAME,UUID,PARTUUID,TYPE,LABEL', device)
        report = lsblk[0]
        for line in report.split('\n'):
            part = {}
            # Split into KEY=VAL pairs
            vals = shlex.split(line)
            for key, val in (v.split('=', 1) for v in vals):
                part[key] = val.strip()
            # Ignore non partition
            if part.get('TYPE') not in ['md', 'part']:
                # NOTE(TheJulia): This technically creates an edge failure
                # case where a filesystem on a whole block device sans
                # partitioning would behave differently.
                continue

            if part.get('UUID') == uuid:
                LOG.debug("Partition %(uuid)s found on device "
                          "%(dev)s", {'uuid': uuid, 'dev': device})
                return '/dev/' + part.get('KNAME')
            if part.get('PARTUUID') == uuid:
                LOG.debug("Partition %(uuid)s found on device "
                          "%(dev)s", {'uuid': uuid, 'dev': device})
                return '/dev/' + part.get('KNAME')
            if part.get('LABEL') == uuid:
                LOG.debug("Partition %(uuid)s found on device "
                          "%(dev)s", {'uuid': uuid, 'dev': device})
                return '/dev/' + part.get('KNAME')
        else:
            # NOTE(TheJulia): We may want to consider moving towards using
            # findfs in the future, if we're comfortable with the execution
            # and interaction. There is value in either way though.
            # NOTE(rg): alternative: blkid -l -t UUID=/PARTUUID=
            try:
                findfs, stderr = utils.execute('findfs', 'UUID=%s' % uuid)
                return findfs.strip()
            except processutils.ProcessExecutionError as e:
                LOG.debug('First fallback detection attempt for locating '
                          'partition via UUID %(uuid)s failed. '
                          'Error: %(err)s',
                          {'uuid': uuid,
                           'err': e})
                try:
                    findfs, stderr = utils.execute(
                        'findfs', 'PARTUUID=%s' % uuid)
                    return findfs.strip()
                except processutils.ProcessExecutionError as e:
                    LOG.debug('Secondary fallback detection attempt for '
                              'locating partition via UUID %(uuid)s failed. '
                              'Error: %(err)s',
                              {'uuid': uuid,
                               'err': e})

            # Last fallback: In case we cannot find the partition by UUID
            # and the deploy device is an md device, we check if the md
            # device has a partition (which we assume to contain the root fs).
            if hardware.is_md_device(device):
                md_partition = device + 'p1'
                if (os.path.exists(md_partition)
                        and stat.S_ISBLK(os.stat(md_partition).st_mode)):
                    LOG.debug("Found md device with partition %s",
                              md_partition)
                    return md_partition
                else:
                    LOG.debug('Could not find partition %(part)s on md '
                              'device %(dev)s',
                              {'part': md_partition,
                               'dev': device})

            # Partition not found, time to escalate.
            error_msg = ("No partition with UUID %(uuid)s found on "
                         "device %(dev)s" % {'uuid': uuid, 'dev': device})
            LOG.error(error_msg)
            raise errors.DeviceNotFound(error_msg)
    except processutils.ProcessExecutionError as e:
        error_msg = ('Finding the partition with UUID %(uuid)s on '
                     'device %(dev)s failed with %(err)s' %
                     {'uuid': uuid, 'dev': device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def _has_dracut(root):
    try:
        utils.execute('chroot %(path)s /bin/sh -c '
                      '"which dracut"' %
                      {'path': root}, shell=True)
    except processutils.ProcessExecutionError:
        return False
    return True


def _has_boot_sector(device):
    """Checks the device for a boot sector indicator."""
    stdout, stderr = utils.execute('file', '-s', device)
    if 'boot sector' not in stdout:
        return False
    # Now lets check the signature
    ddout, dderr = utils.execute(
        'dd', 'if=%s' % device, 'bs=218', 'count=1', binary=True)
    stdout, stderr = utils.execute('file', '-', process_input=ddout)
    # The bytes recovered by dd show as a "dos executable" when
    # examined with file. In other words, the bootloader is present.
    return 'executable' in stdout


def _find_bootable_device(partitions, dev):
    """Checks the base device and partition for bootloader contents."""
    LOG.debug('Looking for a bootable device in %s', dev)
    for line in partitions.splitlines():
        partition = line.split(':')
        try:
            if 'boot' in partition[6]:
                if _has_boot_sector(dev) or _has_boot_sector(partition[0]):
                    return True
        except IndexError:
            continue
    return False


def _is_bootloader_loaded(dev):
    """Checks the device to see if a MBR bootloader is present.

    :param str dev: Block device upon which to check if it appears
                       to be bootable via MBR.
    :returns: True if a device appears to be bootable with a boot
              loader, otherwise False.
    """

    boot = hardware.dispatch_to_managers('get_boot_info')

    if boot.current_boot_mode != 'bios':
        # We're in UEFI mode, this logic is invalid
        LOG.debug('Skipping boot sector check as the system is in UEFI '
                  'boot mode.')
        return False
    LOG.debug('Starting check for pre-intalled BIOS boot-loader.')
    try:
        # Looking for things marked "bootable" in the partition table
        stdout, stderr = utils.execute('parted', dev, '-s', '-m',
                                       '--', 'print')
    except processutils.ProcessExecutionError:
        return False

    return _find_bootable_device(stdout, dev)


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


def _run_efibootmgr(valid_efi_bootloaders, device, efi_partition,
                    mount_point):
    """Executes efibootmgr and removes duplicate entries.

    :param valid_efi_bootloaders: the list of valid efi bootloaders
    :param device: the device to be used
    :param efi_partition: the efi partition on the device
    :param mount_point: The mountpoint for the EFI partition so we can
                        read contents of files if necessary to perform
                        proper bootloader injection operations.
    """

    # Before updating let's get information about the bootorder
    LOG.debug("Getting information about boot order.")
    utils.execute('efibootmgr', '-v')
    # NOTE(iurygregory): regex used to identify the Warning in the stderr after
    # we add the new entry. Example:
    # "efibootmgr: ** Warning ** : Boot0004 has same label ironic"
    duplicated_label = re.compile(r'^.*:\s\*\*.*\*\*\s:\s.*'
                                  r'Boot([0-9a-f-A-F]+)\s.*$')
    label_id = 1
    for v_bl in valid_efi_bootloaders:
        if 'csv' in v_bl.lower():
            LOG.debug('A CSV file has been identified as a bootloader hint. '
                      'File: %s', v_bl)
            # These files are always UTF-16 encoded, sometimes have a header.
            # Positive bonus is python silently drops the FEFF header.
            with open(mount_point + '/' + v_bl, 'r', encoding='utf-16') as csv:
                contents = str(csv.read())
            csv_contents = contents.split(',', maxsplit=3)
            csv_filename = v_bl.split('/')[-1]
            v_efi_bl_path = v_bl.replace(csv_filename, str(csv_contents[0]))
            v_efi_bl_path = '\\' + v_efi_bl_path.replace('/', '\\')
            label = csv_contents[1]
        else:
            v_efi_bl_path = '\\' + v_bl.replace('/', '\\')
            label = 'ironic' + str(label_id)

        LOG.debug("Adding loader %(path)s on partition %(part)s of device "
                  " %(dev)s", {'path': v_efi_bl_path, 'part': efi_partition,
                               'dev': device})
        # Update the nvram using efibootmgr
        # https://linux.die.net/man/8/efibootmgr
        cmd = utils.execute('efibootmgr', '-v', '-c', '-d', device,
                            '-p', efi_partition, '-w', '-L', label,
                            '-l', v_efi_bl_path)
        for line in cmd[1].split('\n'):
            match = duplicated_label.match(line)
            if match:
                boot_num = match.group(1)
                LOG.debug("Found bootnum %s matching label", boot_num)
                utils.execute('efibootmgr', '-b', boot_num, '-B')
        label_id += 1


def _manage_uefi(device, efi_system_part_uuid=None):
    """Manage the device looking for valid efi bootloaders to update the nvram.

    This method checks for valid efi bootloaders in the device, if they exists
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
    try:
        # Force UEFI to rescan the device.
        _rescan_device(device)

        local_path = tempfile.mkdtemp()
        # Trust the contents on the disk in the event of a whole disk image.
        efi_partition = utils.get_efi_part_on_device(device)
        if not efi_partition and efi_system_part_uuid:
            # _get_partition returns <device>+<partition> and we only need the
            # partition number
            partition = _get_partition(device, uuid=efi_system_part_uuid)
            try:
                efi_partition = int(partition.replace(device, ""))
            except ValueError:
                # NVMe Devices get a partitioning scheme that is different from
                # traditional block devices like SCSI/SATA
                efi_partition = int(partition.replace(device + 'p', ""))

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

        efi_partition_mount_point = os.path.join(local_path, "boot/efi")
        if not os.path.exists(efi_partition_mount_point):
            os.makedirs(efi_partition_mount_point)

        # The mount needs the device with the partition, in case the
        # device ends with a digit we add a `p` and the partition number we
        # found, otherwise we just join the device and the partition number
        if device[-1].isdigit():
            efi_device_part = '{}p{}'.format(device, efi_partition)
            utils.execute('mount', efi_device_part, efi_partition_mount_point)
        else:
            efi_device_part = '{}{}'.format(device, efi_partition)
            utils.execute('mount', efi_device_part, efi_partition_mount_point)
        efi_mounted = True

        valid_efi_bootloaders = _get_efi_bootloaders(efi_partition_mount_point)
        if valid_efi_bootloaders:
            _run_efibootmgr(valid_efi_bootloaders, device, efi_partition,
                            efi_partition_mount_point)
            return True
        else:
            # NOTE(dtantsur): if we have an empty EFI partition, try to use
            # grub-install to populate it.
            LOG.warning('Empty EFI partition detected.')
            return False

    except processutils.ProcessExecutionError as e:
        error_msg = ('Could not verify uefi on device %(dev)s'
                     'failed with %(err)s.' % {'dev': device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)
    finally:
        LOG.debug('Executing _manage_uefi clean-up.')
        umount_warn_msg = "Unable to umount %(local_path)s. Error: %(error)s"

        try:
            if efi_mounted:
                utils.execute('umount', efi_partition_mount_point,
                              attempts=3, delay_on_retry=True)
        except processutils.ProcessExecutionError as e:
            error_msg = ('Umounting efi system partition failed. '
                         'Attempted 3 times. Error: %s' % e)
            LOG.error(error_msg)
            raise errors.CommandExecutionError(error_msg)

        else:
            # If umounting the binds succeed then we can try to delete it
            try:
                utils.execute('sync')
            except processutils.ProcessExecutionError as e:
                LOG.warning(umount_warn_msg, {'path': local_path, 'error': e})
            else:
                # After everything is umounted we can then remove the
                # temporary directory
                shutil.rmtree(local_path)


# TODO(rg): handle PreP boot parts relocation as well
def _prepare_boot_partitions_for_softraid(device, holders, efi_part,
                                          target_boot_mode):
    """Prepare boot partitions when relevant.

    Create either a RAIDed EFI partition or bios boot partitions for software
    RAID, according to both target boot mode and disk holders partition table
    types.

    :param device: the softraid device path
    :param holders: the softraid drive members
    :param efi_part: when relevant the efi partition coming from the image
     deployed on softraid device, can be/is often None
    :param target_boot_mode: target boot mode can be bios/uefi/None
     or anything else for unspecified

    :returns: the path to the ESP md device when target boot mode is uefi,
     nothing otherwise.
    """
    # Actually any fat partition could be a candidate. Let's assume the
    # partition also has the esp flag
    if target_boot_mode == 'uefi':
        if not efi_part:

            LOG.debug("No explicit EFI partition provided. Scanning for any "
                      "EFI partition located on software RAID device %s to "
                      "be relocated",
                      device)

            # NOTE: for whole disk images, no efi part uuid will be provided.
            # Let's try to scan for esp on the root softraid device. If not
            # found, it's fine in most cases to just create an empty esp and
            # let grub handle the magic.
            efi_part = utils.get_efi_part_on_device(device)
            if efi_part:
                efi_part = '{}p{}'.format(device, efi_part)

        LOG.info("Creating EFI partitions on software RAID holder disks")
        # We know that we kept this space when configuring raid,see
        # hardware.GenericHardwareManager.create_configuration.
        # We could also directly get the EFI partition size.
        partsize_mib = raid_utils.ESP_SIZE_MIB
        partlabel_prefix = 'uefi-holder-'
        efi_partitions = []
        for number, holder in enumerate(holders):
            # NOTE: see utils.get_partition_table_type_from_specs
            # for uefi we know that we have setup a gpt partition table,
            # sgdisk can be used to edit table, more user friendly
            # for alignment and relative offsets
            partlabel = '{}{}'.format(partlabel_prefix, number)
            out, _u = utils.execute('sgdisk', '-F', holder)
            start_sector = '{}s'.format(out.splitlines()[-1].strip())
            out, _u = utils.execute(
                'sgdisk', '-n', '0:{}:+{}MiB'.format(start_sector,
                                                     partsize_mib),
                '-t', '0:ef00', '-c', '0:{}'.format(partlabel), holder)

            # Refresh part table
            utils.execute("partprobe")
            utils.execute("blkid")

            target_part, _u = utils.execute(
                "blkid", "-l", "-t", "PARTLABEL={}".format(partlabel), holder)

            target_part = target_part.splitlines()[-1].split(':', 1)[0]
            efi_partitions.append(target_part)

            LOG.debug("EFI partition %s created on holder disk %s",
                      target_part, holder)

        # RAID the ESPs, metadata=1.0 is mandatory to be able to boot
        md_device = '/dev/md/esp'
        LOG.debug("Creating md device %(md_device)s for the ESPs "
                  "on %(efi_partitions)s",
                  {'md_device': md_device, 'efi_partitions': efi_partitions})
        utils.execute('mdadm', '--create', md_device, '--force',
                      '--run', '--metadata=1.0', '--level', '1',
                      '--raid-devices', len(efi_partitions),
                      *efi_partitions)

        if efi_part:
            # Blockdev copy the source ESP and erase it
            LOG.debug("Relocating EFI %s to %s", efi_part, md_device)
            utils.execute('cp', efi_part, md_device)
            LOG.debug("Erasing EFI partition %s", efi_part)
            utils.execute('wipefs', '-a', efi_part)
        else:
            fslabel = 'efi-part'
            ilib_utils.mkfs(fs='vfat', path=md_device, label=fslabel)

        return md_device

    elif target_boot_mode == 'bios':
        partlabel_prefix = 'bios-boot-part-'
        for number, holder in enumerate(holders):
            label = utils.scan_partition_table_type(holder)
            if label == 'gpt':
                LOG.debug("Creating bios boot partition on disk holder %s",
                          holder)
                out, _u = utils.execute('sgdisk', '-F', holder)
                start_sector = '{}s'.format(out.splitlines()[-1].strip())
                partlabel = '{}{}'.format(partlabel_prefix, number)
                out, _u = utils.execute(
                    'sgdisk', '-n', '0:{}:+2MiB'.format(start_sector),
                    '-t', '0:ef02', '-c', '0:{}'.format(partlabel), holder)

            # Q: MBR case, could we dd the boot code from the softraid
            # (446 first bytes) if we detect a bootloader with
            # _is_bootloader_loaded?
            # A: This won't work. Because it includes the address on the
            # disk, as in virtual disk, where to load the data from.
            # Since there is a structural difference, this means it will
            # fail.


def _umount_all_partitions(path, path_variable, umount_warn_msg):
    """Umount all partitions we may have mounted"""
    umount_binds_success = True
    LOG.debug("Unmounting all vfat partitions inside the image ...")
    try:
        utils.execute('chroot %(path)s /bin/sh -c "umount -a -t vfat"' %
                      {'path': path}, shell=True,
                      env_variables={'PATH': path_variable})
    except processutils.ProcessExecutionError as e:
        LOG.warning("Unable to umount vfat partitions. Error: %(error)s",
                    {'error': e})

    for fs in BIND_MOUNTS + ('/sys',):
        try:
            utils.execute('umount', path + fs, attempts=3,
                          delay_on_retry=True)
        except processutils.ProcessExecutionError as e:
            umount_binds_success = False
            LOG.warning(umount_warn_msg, {'path': path + fs, 'error': e})

    return umount_binds_success


def _mount_partition(partition, path):
    if not os.path.ismount(path):
        LOG.debug('Attempting to mount %(device)s to %(path)s to '
                  'partition.',
                  {'device': partition,
                   'path': path})
        try:
            utils.execute('mount', partition, path)
        except processutils.ProcessExecutionError as e:
            # NOTE(TheJulia): It seems in some cases,
            # the python os.path.ismount can return False
            # even *if* it is actually mounted. This appears
            # to be becasue it tries to rely on inode on device
            # logic, yet the rules are sometimes different inside
            # ramdisks. So lets check the error first.
            if 'already mounted' not in e:
                # Raise the error, since this is not a known
                # failure case
                raise
            else:
                LOG.debug('Partition already mounted, proceeding.')


def _install_grub2(device, root_uuid, efi_system_part_uuid=None,
                   prep_boot_part_uuid=None, target_boot_mode='bios'):
    """Install GRUB2 bootloader on a given device."""
    LOG.debug("Installing GRUB2 bootloader on device %s", device)

    efi_partition = None
    efi_part = None
    efi_partition_mount_point = None
    efi_mounted = False
    efi_preserved = False
    holders = None
    path_variable = _get_path_variable()

    # NOTE(TheJulia): Seems we need to get this before ever possibly
    # restart the device in the case of multi-device RAID as pyudev
    # doesn't exactly like the partition disappearing.
    root_partition = _get_partition(device, uuid=root_uuid)

    # If the root device is an md device (or partition), restart the device
    # (to help grub finding it) and identify the underlying holder disks
    # to install grub.
    if hardware.is_md_device(device):
        # If the root device is an md device (or partition),
        # restart the device to help grub find it later on.
        hardware.md_restart(device)
        # If an md device, we need to rescan the devices anyway to pickup
        # the md device partition.
        _rescan_device(device)
    elif (_is_bootloader_loaded(device)
          and not (efi_system_part_uuid
                   or prep_boot_part_uuid)):
        # We always need to put the bootloader in place with software raid
        # so it is okay to elif into the skip doing a bootloader step.
        LOG.info("Skipping installation of bootloader on device %s "
                 "as it is already marked bootable.", device)
        return

    try:
        # Mount the partition and binds
        path = tempfile.mkdtemp()
        if efi_system_part_uuid:
            efi_part = _get_partition(device, uuid=efi_system_part_uuid)
            efi_partition = efi_part
        if hardware.is_md_device(device):
            holders = hardware.get_holder_disks(device)
            efi_partition = _prepare_boot_partitions_for_softraid(
                device, holders, efi_part, target_boot_mode
            )

        if efi_partition:
            efi_partition_mount_point = os.path.join(path, "boot/efi")

        # For power we want to install grub directly onto the PreP partition
        if prep_boot_part_uuid:
            device = _get_partition(device, uuid=prep_boot_part_uuid)

        # If the root device is an md device (or partition),
        # identify the underlying holder disks to install grub.
        if hardware.is_md_device(device):
            disks = holders
        else:
            disks = [device]

        utils.execute('mount', root_partition, path)

        _mount_for_chroot(path)

        # UEFI asset management for RAID is handled elsewhere
        if not hardware.is_md_device(device) and efi_partition_mount_point:
            # NOTE(TheJulia): It may make sense to retool all efi
            # asset preservation logic at some point since the paths
            # can be a little different, but largely this is JUST for
            # partition images as there _should not_ be a mount
            # point if we have no efi partitions at all.
            efi_preserved = _try_preserve_efi_assets(
                device, path, efi_system_part_uuid,
                efi_partition, efi_partition_mount_point)
            if efi_preserved:
                _append_uefi_to_fstab(path, efi_system_part_uuid)
                # Success preserving efi assets
                return
            else:
                # Failure, either via exception or not found
                # which in this case the partition needs to be
                # remounted.
                LOG.debug('No EFI assets were preserved for setup or the '
                          'ramdisk was unable to complete the setup. '
                          'falling back to bootloader installation from '
                          'deployed image.')
                _mount_partition(root_partition, path)

        binary_name = "grub"
        if os.path.exists(os.path.join(path, 'usr/sbin/grub2-install')):
            binary_name = "grub2"

        # Mount all vfat partitions listed in the fstab of the root partition.
        # This is to make sure grub2 finds all files it needs, as some of them
        # may not be inside the root partition but in the ESP (like grub2env).
        LOG.debug("Mounting all partitions inside the image ...")
        utils.execute('chroot %(path)s /bin/sh -c "mount -a -t vfat"' %
                      {'path': path}, shell=True,
                      env_variables={'PATH': path_variable})

        if efi_partition:
            if not os.path.exists(efi_partition_mount_point):
                os.makedirs(efi_partition_mount_point)
            LOG.warning("GRUB2 will be installed for UEFI on efi partition "
                        "%s using the install command which does not place "
                        "Secure Boot signed binaries.", efi_partition)

            _mount_partition(efi_partition, efi_partition_mount_point)
            efi_mounted = True
            try:
                utils.execute('chroot %(path)s /bin/sh -c '
                              '"%(bin)s-install"' %
                              {'path': path, 'bin': binary_name},
                              shell=True,
                              env_variables={
                                  'PATH': path_variable
                              })
            except processutils.ProcessExecutionError as e:
                LOG.warning('Ignoring GRUB2 boot loader installation failure: '
                            '%s.', e)
            try:
                # Also run grub-install with --removable, this installs grub to
                # the EFI fallback path. Useful if the NVRAM wasn't written
                # correctly, was reset or if testing with virt as libvirt
                # resets the NVRAM on instance start.
                # This operation is essentially a copy operation. Use of the
                # --removable flag, per the grub-install source code changes
                # the default file to be copied, destination file name, and
                # prevents NVRAM from being updated.
                # We only run grub2_install for uefi if we can't verify the
                # uefi bits
                utils.execute('chroot %(path)s /bin/sh -c '
                              '"%(bin)s-install --removable"' %
                              {'path': path, 'bin': binary_name},
                              shell=True,
                              env_variables={
                                  'PATH': path_variable
                              })
            except processutils.ProcessExecutionError as e:
                LOG.warning('Ignoring GRUB2 boot loader installation failure: '
                            '%s.', e)
            utils.execute('umount', efi_partition_mount_point, attempts=3,
                          delay_on_retry=True)
            efi_mounted = False
            # NOTE: probably never needed for grub-mkconfig, does not hurt in
            # case of doubt, cleaned in the finally clause anyway
            utils.execute('mount', efi_partition,
                          efi_partition_mount_point)
            efi_mounted = True
        else:
            # FIXME(rg): does not work if ramdisk boot mode is not the same
            # as the target (--target=i386-pc, arch dependent).
            # See previous FIXME

            # Install grub. Normally, grub goes to one disk only. In case of
            # md devices, grub goes to all underlying holder (RAID-1) disks.
            LOG.info("GRUB2 will be installed on disks %s", disks)
            for grub_disk in disks:
                LOG.debug("Installing GRUB2 on disk %s", grub_disk)
                utils.execute(
                    'chroot %(path)s /bin/sh -c "%(bin)s-install %(dev)s"' %
                    {
                        'path': path,
                        'bin': binary_name,
                        'dev': grub_disk
                    },
                    shell=True,
                    env_variables={
                        'PATH': path_variable
                    }
                )
                LOG.debug("GRUB2 successfully installed on device %s",
                          grub_disk)

        # NOTE(TheJulia): Setup grub configuration again since IF we reach
        # this point, then we've manually installed grub which is not the
        # recommended path.
        _configure_grub(device, path)

        if efi_mounted:
            _append_uefi_to_fstab(path, efi_system_part_uuid)

        LOG.info("GRUB2 successfully installed on %s", device)

    except processutils.ProcessExecutionError as e:
        error_msg = ('Installing GRUB2 boot loader to device %(dev)s '
                     'failed with %(err)s.' % {'dev': device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)

    finally:
        LOG.debug('Executing _install_grub2 clean-up.')
        # Umount binds and partition
        umount_warn_msg = "Unable to umount %(path)s. Error: %(error)s"

        # If umount fails for efi partition, then we cannot be sure that all
        # the changes were written back to the filesystem.
        try:
            if efi_mounted:
                utils.execute('umount', efi_partition_mount_point, attempts=3,
                              delay_on_retry=True)
        except processutils.ProcessExecutionError as e:
            error_msg = ('Umounting efi system partition failed. '
                         'Attempted 3 times. Error: %s' % e)
            LOG.error(error_msg)
            raise errors.CommandExecutionError(error_msg)

        # If umounting the binds succeed then we can try to delete it
        if _umount_all_partitions(path,
                                  path_variable,
                                  umount_warn_msg):
            try:
                utils.execute('umount', path, attempts=3, delay_on_retry=True)
            except processutils.ProcessExecutionError as e:
                LOG.warning(umount_warn_msg, {'path': path, 'error': e})
            else:
                # After everything is umounted we can then remove the
                # temporary directory
                shutil.rmtree(path)


def _get_path_variable():
    # Add /bin to PATH variable as grub requires it to find efibootmgr
    # when running in uefi boot mode.
    # Add /usr/sbin to PATH variable to ensure it is there as we do
    # not use full path to grub binary anymore.
    path_variable = os.environ.get('PATH', '')
    return '%s:/bin:/usr/sbin:/sbin' % path_variable


def _configure_grub(device, path):
    """Make consolidated grub configuration as it is device aware.

    :param device: The device for the filesystem.
    :param path: The path in which the filesystem is mounted.
    """
    LOG.debug('Attempting to generate grub Configuration')
    path_variable = _get_path_variable()
    binary_name = "grub"
    if os.path.exists(os.path.join(path, 'usr/sbin/grub2-install')):
        binary_name = "grub2"
    # If the image has dracut installed, set the rd.md.uuid kernel
    # parameter for discovered md devices.
    if hardware.is_md_device(device) and _has_dracut(path):
        rd_md_uuids = ["rd.md.uuid=%s" % x['UUID']
                       for x in hardware.md_get_raid_devices().values()]
        LOG.debug("Setting rd.md.uuid kernel parameters: %s", rd_md_uuids)
        with open('%s/etc/default/grub' % path, 'r') as g:
            contents = g.read()
        with open('%s/etc/default/grub' % path, 'w') as g:
            g.write(
                re.sub(r'GRUB_CMDLINE_LINUX="(.*)"',
                       r'GRUB_CMDLINE_LINUX="\1 %s"'
                       % " ".join(rd_md_uuids),
                       contents))

    utils.execute('chroot %(path)s /bin/sh -c '
                  '"%(bin)s-mkconfig -o '
                  '/boot/%(bin)s/grub.cfg"' %
                  {'path': path, 'bin': binary_name}, shell=True,
                  env_variables={'PATH': path_variable,
                                 'GRUB_DISABLE_OS_PROBER': 'true',
                                 'GRUB_SAVEDEFAULT': 'true'},
                  use_standard_locale=True)
    LOG.debug('Completed basic grub configuration.')


def _mount_for_chroot(path):
    """Mount items for grub-mkconfig to succeed."""
    LOG.debug('Mounting Linux standard partitions for bootloader '
              'configuration generation')
    for fs in BIND_MOUNTS:
        utils.execute('mount', '-o', 'bind', fs, path + fs)
    utils.execute('mount', '-t', 'sysfs', 'none', path + '/sys')


def _try_preserve_efi_assets(device, path,
                             efi_system_part_uuid,
                             efi_partition,
                             efi_partition_mount_point):
    """Attempt to preserve UEFI boot assets.

    :param device: The device upon which wich to try to preserve
                   assets.
    :param path: The path in which the filesystem is already mounted
                 which we should examine to preserve assets from.
    :param efi_system_part_uuid: The partition ID representing the
                                 created EFI system partition.
    :param efi_partition: The partitions upon wich to write the preserved
                          assets to.
    :param efi_partition_mount_point: The folder at which to mount
                                      the assets for the process of
                                      preservation.

    :returns: True if assets have been preserved, otherwise False.
              None is the result of this method if a failure has
              occured.
    """
    efi_assets_folder = efi_partition_mount_point + '/EFI'
    if os.path.exists(efi_assets_folder):
        # We appear to have EFI Assets, that need to be preserved
        # and as such if we succeed preserving them, we will be returned
        # True from _preserve_efi_assets to correspond with success or
        # failure in this action.
        # NOTE(TheJulia): Still makes sense to invoke grub-install as
        # fragmentation of grub has occured.
        if (os.path.exists(os.path.join(path, 'usr/sbin/grub2-install'))
            or os.path.exists(os.path.join(path, 'usr/sbin/grub-install'))):
            _configure_grub(device, path)
        # But first, if we have grub, we should try to build a grub config!
        LOG.debug('EFI asset folder detected, attempting to preserve assets.')
        if _preserve_efi_assets(path, efi_assets_folder,
                                efi_partition,
                                efi_partition_mount_point):
            try:
                # Since we have preserved the assets, we should be able
                # to call the _efi_boot_setup method to scan the device
                # and add loader entries
                efi_preserved = _efi_boot_setup(device, efi_system_part_uuid)
                # Executed before the return so we don't return and then begin
                # execution.
                return efi_preserved
            except Exception as e:
                # Remount the partition and proceed as we were.
                LOG.debug('Exception encountered while attempting to '
                          'setup the EFI loader from a root '
                          'filesystem. Error: %s', e)


def _append_uefi_to_fstab(fs_path, efi_system_part_uuid):
    """Append the efi partition id to the filesystem table.

    :param fs_path:
    :param efi_system_part_uuid:
    """
    fstab_file = os.path.join(fs_path, 'etc/fstab')
    if not os.path.exists(fstab_file):
        return
    try:
        fstab_string = ("UUID=%s\t/boot/efi\tvfat\tumask=0077\t"
                        "0\t1\n") % efi_system_part_uuid
        with open(fstab_file, "r+") as fstab:
            if efi_system_part_uuid not in fstab.read():
                fstab.writelines(fstab_string)
    except (OSError, EnvironmentError, IOError) as exc:
        LOG.debug('Failed to add entry to /etc/fstab. Error %s', exc)
    LOG.debug('Added entry to /etc/fstab for EFI partition auto-mount '
              'with uuid %s', efi_system_part_uuid)


def _efi_boot_setup(device, efi_system_part_uuid=None, target_boot_mode=None):
    """Identify and setup an EFI bootloader from supplied partition/disk.

    :param device: The device upon which to attempt the EFI bootloader setup.
    :param efi_system_part_uuid: The partition UUID to utilize in searching
                                 for an EFI bootloader.
    :param target_boot_mode: The requested boot mode target for the
                             machine. This is optional and is mainly used
                             for the purposes of identifying a mismatch and
                             reporting a warning accordingly.
    :returns: True if we succeeded in setting up an EFI bootloader in the
              EFI nvram table.
              False if we were unable to set the machine to EFI boot,
              due to inability to locate assets required OR the efibootmgr
              tool not being present.
              None is returned if the node is NOT in UEFI boot mode or
              the system is deploying upon a software RAID device.
    """
    boot = hardware.dispatch_to_managers('get_boot_info')
    # Explicitly only run if a target_boot_mode is set which prevents
    # callers following-up from re-logging the same message
    if target_boot_mode and boot.current_boot_mode != target_boot_mode:
        LOG.warning('Boot mode mismatch: target boot mode is %(target)s, '
                    'current boot mode is %(current)s. Installing boot '
                    'loader may fail or work incorrectly.',
                    {'target': target_boot_mode,
                     'current': boot.current_boot_mode})

    # FIXME(arne_wiebalck): make software RAID work with efibootmgr
    if (boot.current_boot_mode == 'uefi'
            and not hardware.is_md_device(device)):
        try:
            utils.execute('efibootmgr', '--version')
        except FileNotFoundError:
            LOG.warning("efibootmgr is not available in the ramdisk")
        else:
            if _manage_uefi(device,
                            efi_system_part_uuid=efi_system_part_uuid):
                return True
        return False


def _preserve_efi_assets(path, efi_assets_folder, efi_partition,
                         efi_partition_mount_point):
    """Preserve the EFI assets in a partition image.

    :param path: The path used for the mounted image filesystem.
    :param efi_assets_folder: The folder where we can find the
                              UEFI assets required for booting.
    :param efi_partition: The partition upon which to write the
                          perserved assets to.
    :param efi_partition_mount_point: The folder at which to mount
                                      the assets for the process of
                                      preservation.
    :returns: True if EFI assets were able to be located and preserved
              to their appropriate locations based upon the supplied
              efi_partition.
              False if any error is encountered in this process.
    """
    try:
        save_efi = os.path.join(tempfile.mkdtemp(), 'efi_loader')
        LOG.debug('Copying EFI assets to %s.', save_efi)
        shutil.copytree(efi_assets_folder, save_efi)

        # Identify grub2 config file for EFI booting as grub may require it
        # in the folder.

        destlist = os.listdir(efi_assets_folder)
        grub2_file = os.path.join(path, 'boot/grub2/grub.cfg')
        if os.path.isfile(grub2_file):
            LOG.debug('Local Grub2 configuration detected.')
            # A grub2 config seems to be present, we should preserve it!
            for dest in destlist:
                grub_dest = os.path.join(save_efi, dest, 'grub.cfg')
                if not os.path.isfile(grub_dest):
                    LOG.debug('A grub.cfg file was not found in %s. %s'
                              'will be copied to that location.',
                              grub_dest, grub2_file)
                    try:
                        shutil.copy2(grub2_file, grub_dest)
                    except (IOError, OSError, shutil.SameFileError) as e:
                        LOG.warning('Failed to copy grub.cfg file for '
                                    'EFI boot operation. Error %s', e)
        grub2_env_file = os.path.join(path, 'boot/grub2/grubenv')
        # NOTE(TheJulia): By saving the default, this file should be created.
        # this appears to what diskimage-builder does.
        # if the file is just a file, then we'll need to copy it. If it is
        # anything else like a link, we're good. This behaivor is inconsistent
        # depending on packager install scripts for grub.
        if os.path.isfile(grub2_env_file):
            LOG.debug('Detected grub environment file %s, will attempt '
                      'to copy this file to align with apparent bootloaders',
                      grub2_env_file)
            for dest in destlist:
                grub2env_dest = os.path.join(save_efi, dest, 'grubenv')
                if not os.path.isfile(grub2env_dest):
                    LOG.debug('A grubenv file was not found. Copying '
                              'to %s along with the grub.cfg file as '
                              'grub generally expects it is present.',
                              grub2env_dest)
                    try:
                        shutil.copy2(grub2_env_file, grub2env_dest)
                    except (IOError, OSError, shutil.SameFileError) as e:
                        LOG.warning('Failed to copy grubenv file. '
                                    'Error: %s', e)
        utils.execute('mount', '-t', 'vfat', efi_partition,
                      efi_partition_mount_point)
        shutil.copytree(save_efi, efi_assets_folder)
        LOG.debug('Files preserved to %(disk)s for %(part)s. '
                  'Files: %(filelist)s From: %(from)s',
                  {'disk': efi_partition,
                   'part': efi_partition_mount_point,
                   'filelist': os.listdir(efi_assets_folder),
                   'from': save_efi})
        utils.execute('umount', efi_partition_mount_point)
        return True
    except Exception as e:
        LOG.debug('Failed to preserve EFI assets. Error %s', e)
        try:
            utils.execute('umount', efi_partition_mount_point)
        except Exception as e:
            LOG.debug('Exception encountered while attempting unmount '
                      'the EFI partition mount point. Error: %s', e)
        return False


class ImageExtension(base.BaseAgentExtension):

    @base.async_command('install_bootloader')
    def install_bootloader(self, root_uuid, efi_system_part_uuid=None,
                           prep_boot_part_uuid=None,
                           target_boot_mode='bios',
                           ignore_bootloader_failure=None):
        """Install the GRUB2 bootloader on the image.

        :param root_uuid: The UUID of the root partition.
        :param efi_system_part_uuid: The UUID of the efi system partition.
            To be used only for uefi boot mode.  For uefi boot mode, the
            boot loader will be installed here.
        :param prep_boot_part_uuid: The UUID of the PReP Boot partition.
            Used only for booting ppc64* partition images locally. In this
            scenario the bootloader will be installed here.
        :param target_boot_mode: bios, uefi. Only taken into account
            for softraid, when no efi partition is explicitely provided
            (happens for whole disk images)
        :raises: CommandExecutionError if the installation of the
                 bootloader fails.
        :raises: DeviceNotFound if the root partition is not found.

        """
        device = hardware.dispatch_to_managers('get_os_install_device')

        # Always allow the API client to be the final word on if this is
        # overridden or not.
        if ignore_bootloader_failure is None:
            ignore_failure = CONF.ignore_bootloader_failure
        else:
            ignore_failure = ignore_bootloader_failure

        try:
            if _efi_boot_setup(device, efi_system_part_uuid, target_boot_mode):
                return
        except Exception as e:
            LOG.error('Error setting up bootloader. Error %s', e)
            if not ignore_failure:
                raise

        # We don't have a working root UUID detection for whole disk images.
        # Until we can do it, avoid a confusing traceback.
        if root_uuid == '0x00000000' or root_uuid is None:
            LOG.info('Not using grub2-install since root UUID is not provided.'
                     ' Assuming a whole disk image')
            return

        # In case we can't use efibootmgr for uefi we will continue using grub2
        LOG.debug('Using grub2-install to set up boot files')
        try:
            _install_grub2(device,
                           root_uuid=root_uuid,
                           efi_system_part_uuid=efi_system_part_uuid,
                           prep_boot_part_uuid=prep_boot_part_uuid,
                           target_boot_mode=target_boot_mode)
        except Exception as e:
            LOG.error('Error setting up bootloader. Error %s', e)
            if not ignore_failure:
                raise

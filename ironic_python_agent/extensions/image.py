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

from oslo_concurrency import processutils
from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent.extensions import iscsi
from ironic_python_agent import hardware
from ironic_python_agent import utils

LOG = log.getLogger(__name__)


BIND_MOUNTS = ('/dev', '/proc', '/run')

BOOTLOADERS_EFI = ['bootx64.efi', 'grubaa64.efi', 'winload.efi']


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

        # If the deploy device is an md device, we want to install on
        # the first partition. We clearly take a shortcut here for now.
        # TODO(arne_wiebalck): Would it possible to use the partition
        #                      UUID and use the "normal" discovery instead?
        if hardware.is_md_device(device):
            md_partition = device + 'p1'
            if (not os.path.exists(md_partition) or
                not stat.S_ISBLK(os.stat(md_partition).st_mode)):
                error_msg = ("Could not find partition %(part)s on md "
                             "device %(dev)s" % {'part': md_partition,
                                                 'dev': device})
                LOG.error(error_msg)
                raise errors.DeviceNotFound(error_msg)
            LOG.debug("Found md device with partition %s", md_partition)
            return md_partition

        lsblk = utils.execute('lsblk', '-PbioKNAME,UUID,PARTUUID,TYPE', device)
        report = lsblk[0]
        for line in report.split('\n'):
            part = {}
            # Split into KEY=VAL pairs
            vals = shlex.split(line)
            for key, val in (v.split('=', 1) for v in vals):
                part[key] = val.strip()
            # Ignore non partition
            if part.get('TYPE') != 'part':
                # NOTE(TheJulia): This techincally creates an edge failure
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
        else:
            # NOTE(TheJulia): We may want to consider moving towards using
            # findfs in the future, if we're comfortable with the execution
            # and interaction. There is value in either way though.
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


def _is_bootloader_loaded(dev):
    """Checks the device to see if a MBR bootloader is present.

    :param str dev: Block device upon which to check if it appears
                       to be bootable via MBR.
    :returns: True if a device appears to be bootable with a boot
              loader, otherwise False.
    """

    def _has_boot_sector(device):
        """Check the device for a boot sector indiator."""
        stdout, stderr = utils.execute('file', '-s', device)
        if 'boot sector' in stdout:
            # Now lets check the signature
            ddout, dderr = utils.execute(
                'dd', 'if=%s' % device, 'bs=218', 'count=1')
            stdout, stderr = utils.execute('file', '-', process_input=ddout)
            # The bytes recovered by dd show as a "dos executable" when
            # examined with file. In other words, the bootloader is present.
            if 'executable' in stdout:
                return True
        return False

    boot = hardware.dispatch_to_managers('get_boot_info')

    if boot.current_boot_mode != 'bios':
        # We're in UEFI mode, this logic is invalid
        LOG.debug('Skipping boot sector check as the system is in UEFI '
                  'boot mode.')
        return False

    try:
        # Looking for things marked "bootable" in the partition table
        stdout, stderr = utils.execute('parted', dev, '-s', '-m',
                                       '--', 'print')
    except processutils.ProcessExecutionError:
        return False

    lines = stdout.splitlines()
    for line in lines:
        partition = line.split(':')
        try:
            # Find the bootable device, and check the base
            # device and partition for bootloader contents.
            if 'boot' in partition[6]:
                if (_has_boot_sector(dev)
                    or _has_boot_sector(partition[0])):
                    return True
        except IndexError:
            continue
    return False


def _get_efi_bootloaders(location):
    """Get all valid efi bootloaders in a given location

    :param location: the location where it should  start looking for the
                     efi files.
    :return: a list of valid efi bootloaders
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
                v_bl = efi_f.split('/boot/efi')[-1].replace('/', '\\')
                LOG.debug('%s is a valid bootloader', v_bl)
                valid_bootloaders.append(v_bl)
    return valid_bootloaders


def _run_efibootmgr(valid_efi_bootloaders, device, efi_partition):
    """Executes efibootmgr and removes duplicate entries.

    :param valid_efi_bootloaders: the list of valid efi bootloaders
    :param device: the device to be used
    :param efi_partition: the efi partition on the device
    """

    # Before updating let's get information about the bootorder
    LOG.debug("Getting information about boot order")
    utils.execute('efibootmgr')
    # NOTE(iurygregory): regex used to identify the Warning in the stderr after
    # we add the new entry. Example:
    # "efibootmgr: ** Warning ** : Boot0004 has same label ironic"
    duplicated_label = re.compile(r'^.*:\s\*\*.*\*\*\s:\s.*'
                                  r'Boot([0-9a-f-A-F]+)\s.*$')
    label_id = 1
    for v_efi_bl_path in valid_efi_bootloaders:
        # Update the nvram using efibootmgr
        # https://linux.die.net/man/8/efibootmgr
        label = 'ironic' + str(label_id)
        LOG.debug("Adding loader %(path)s on partition %(part)s of device "
                  " %(dev)s", {'path': v_efi_bl_path, 'part': efi_partition,
                               'dev': device})
        cmd = utils.execute('efibootmgr', '-c', '-d', device,
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
    :return: True - if it founds any efi bootloader and the nvram was updated
             using the efibootmgr.
             False - if no efi bootloader is found.
    """
    efi_partition = None
    efi_partition_mount_point = None
    efi_mounted = False

    try:
        # Force UEFI to rescan the device. Required if the deployment
        # was over iscsi.
        _rescan_device(device)

        local_path = tempfile.mkdtemp()
        # Trust the contents on the disk in the event of a whole disk image.
        efi_partition = utils.get_efi_part_on_device(device)
        if not efi_partition:
            # _get_partition returns <device>+<partition> and we only need the
            # partition number
            partition = _get_partition(device, uuid=efi_system_part_uuid)
            efi_partition = int(partition.replace(device, ""))

        if efi_partition:
            efi_partition_mount_point = os.path.join(local_path, "boot/efi")
            if not os.path.exists(efi_partition_mount_point):
                os.makedirs(efi_partition_mount_point)

            # The mount needs the device with the partition, in case the
            # device ends with a digit we add a `p` and the partition number we
            # found, otherwise we just join the device and the partition number
            if device[-1].isdigit():
                efi_device_part = '{}p{}'.format(device, efi_partition)
                utils.execute('mount', efi_device_part,
                              efi_partition_mount_point)
            else:
                efi_device_part = '{}{}'.format(device, efi_partition)
                utils.execute('mount', efi_device_part,
                              efi_partition_mount_point)
            efi_mounted = True
        else:
            # If we can't find the partition we need to decide what should
            # happen
            return False
        valid_efi_bootloaders = _get_efi_bootloaders(efi_partition_mount_point)
        if valid_efi_bootloaders:
            _run_efibootmgr(valid_efi_bootloaders, device, efi_partition)
            return True
        else:
            return False

    except processutils.ProcessExecutionError as e:
        error_msg = ('Could not verify uefi on device %(dev)s'
                     'failed with %(err)s.' % {'dev': device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)
    finally:
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


def _install_grub2(device, root_uuid, efi_system_part_uuid=None,
                   prep_boot_part_uuid=None):
    """Install GRUB2 bootloader on a given device."""
    LOG.debug("Installing GRUB2 bootloader on device %s", device)

    efi_partition = None
    efi_partition_mount_point = None
    efi_mounted = False

    # NOTE(TheJulia): Seems we need to get this before ever possibly
    # restart the device in the case of multi-device RAID as pyudev
    # doesn't exactly like the partition disappearing.
    root_partition = _get_partition(device, uuid=root_uuid)

    # If the root device is an md device (or partition), restart the device
    # (to help grub finding it) and identify the underlying holder disks
    # to install grub.
    if hardware.is_md_device(device):
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
            efi_partition = _get_partition(device, uuid=efi_system_part_uuid)
            efi_partition_mount_point = os.path.join(path, "boot/efi")

        # For power we want to install grub directly onto the PreP partition
        if prep_boot_part_uuid:
            device = _get_partition(device, uuid=prep_boot_part_uuid)

        # If the root device is an md device (or partition),
        # identify the underlying holder disks to install grub.
        if hardware.is_md_device(device):
            disks = hardware.get_holder_disks(device)
        else:
            disks = [device]

        utils.execute('mount', root_partition, path)
        for fs in BIND_MOUNTS:
            utils.execute('mount', '-o', 'bind', fs, path + fs)

        utils.execute('mount', '-t', 'sysfs', 'none', path + '/sys')

        if efi_partition:
            if not os.path.exists(efi_partition_mount_point):
                os.makedirs(efi_partition_mount_point)
            utils.execute('mount', efi_partition, efi_partition_mount_point)
            efi_mounted = True

        binary_name = "grub"
        if os.path.exists(os.path.join(path, 'usr/sbin/grub2-install')):
            binary_name = "grub2"

        # Add /bin to PATH variable as grub requires it to find efibootmgr
        # when running in uefi boot mode.
        # Add /usr/sbin to PATH variable to ensure it is there as we do
        # not use full path to grub binary anymore.
        path_variable = os.environ.get('PATH', '')
        path_variable = '%s:/bin:/usr/sbin' % path_variable

        # Install grub. Normally, grub goes to one disk only. In case of
        # md devices, grub goes to all underlying holder (RAID-1) disks.
        LOG.info("GRUB2 will be installed on disks %s", disks)
        for grub_disk in disks:
            LOG.debug("Installing GRUB2 on disk %s", grub_disk)
            utils.execute('chroot %(path)s /bin/sh -c '
                          '"%(bin)s-install %(dev)s"' %
                          {'path': path, 'bin': binary_name,
                           'dev': grub_disk},
                          shell=True, env_variables={'PATH': path_variable})
            LOG.debug("GRUB2 successfully installed on device %s", grub_disk)

        # Also run grub-install with --removable, this installs grub to the
        # EFI fallback path. Useful if the NVRAM wasn't written correctly,
        # was reset or if testing with virt as libvirt resets the NVRAM
        # on instance start.
        # This operation is essentially a copy operation. Use of the
        # --removable flag, per the grub-install source code changes
        # the default file to be copied, destination file name, and
        # prevents NVRAM from being updated.
        # We only run grub2_install for uefi if we can't verify the uefi bits
        if efi_partition:
            utils.execute('chroot %(path)s /bin/sh -c '
                          '"%(bin)s-install %(dev)s --removable"' %
                          {'path': path, 'bin': binary_name, 'dev': device},
                          shell=True, env_variables={'PATH': path_variable})

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

        # Generate the grub configuration file
        utils.execute('chroot %(path)s /bin/sh -c '
                      '"%(bin)s-mkconfig -o '
                      '/boot/%(bin)s/grub.cfg"' %
                      {'path': path, 'bin': binary_name}, shell=True,
                      env_variables={'PATH': path_variable})

        LOG.info("GRUB2 successfully installed on %s", device)

    except processutils.ProcessExecutionError as e:
        error_msg = ('Installing GRUB2 boot loader to device %(dev)s '
                     'failed with %(err)s.' % {'dev': device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)

    finally:
        umount_warn_msg = "Unable to umount %(path)s. Error: %(error)s"
        # Umount binds and partition
        umount_binds_fail = False

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

        for fs in BIND_MOUNTS:
            try:
                utils.execute('umount', path + fs, attempts=3,
                              delay_on_retry=True)
            except processutils.ProcessExecutionError as e:
                umount_binds_fail = True
                LOG.warning(umount_warn_msg, {'path': path + fs, 'error': e})

        try:
            utils.execute('umount', path + '/sys', attempts=3,
                          delay_on_retry=True)
        except processutils.ProcessExecutionError as e:
            umount_binds_fail = True
            LOG.warning(umount_warn_msg, {'path': path + '/sys', 'error': e})

        # If umounting the binds succeed then we can try to delete it
        if not umount_binds_fail:
            try:
                utils.execute('umount', path, attempts=3, delay_on_retry=True)
            except processutils.ProcessExecutionError as e:
                LOG.warning(umount_warn_msg, {'path': path, 'error': e})
            else:
                # After everything is umounted we can then remove the
                # temporary directory
                shutil.rmtree(path)


class ImageExtension(base.BaseAgentExtension):

    @base.sync_command('install_bootloader')
    def install_bootloader(self, root_uuid, efi_system_part_uuid=None,
                           prep_boot_part_uuid=None):
        """Install the GRUB2 bootloader on the image.

        :param root_uuid: The UUID of the root partition.
        :param efi_system_part_uuid: The UUID of the efi system partition.
            To be used only for uefi boot mode.  For uefi boot mode, the
            boot loader will be installed here.
        :param prep_boot_part_uuid: The UUID of the PReP Boot partition.
            Used only for booting ppc64* partition images locally. In this
            scenario the bootloader will be installed here.
        :raises: CommandExecutionError if the installation of the
                 bootloader fails.
        :raises: DeviceNotFound if the root partition is not found.

        """
        device = hardware.dispatch_to_managers('get_os_install_device')
        iscsi.clean_up(device)
        boot = hardware.dispatch_to_managers('get_boot_info')
        if boot.current_boot_mode == 'uefi':
            has_efibootmgr = True
            # NOTE(iurygregory): adaptation for py27 since we don't have
            # FileNotFoundError defined.
            try:
                FileNotFoundError
            except NameError:
                FileNotFoundError = OSError
            try:
                utils.execute('efibootmgr', '--version')
            except FileNotFoundError:
                LOG.warning("efibootmgr is not available in the ramdisk")
                has_efibootmgr = False

            if has_efibootmgr:
                if _manage_uefi(device,
                                efi_system_part_uuid=efi_system_part_uuid):
                    return

        # In case we can't use efibootmgr for uefi we will continue using grub2
        LOG.debug('Using grub2-install to set up boot files')
        _install_grub2(device,
                       root_uuid=root_uuid,
                       efi_system_part_uuid=efi_system_part_uuid,
                       prep_boot_part_uuid=prep_boot_part_uuid)

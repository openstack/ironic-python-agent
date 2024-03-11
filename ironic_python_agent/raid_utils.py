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

import copy
import re
import shlex

from ironic_lib import utils as il_utils
from oslo_concurrency import processutils
from oslo_log import log as logging

from ironic_python_agent import disk_utils
from ironic_python_agent import errors
from ironic_python_agent import utils


LOG = logging.getLogger(__name__)


# NOTE(dtantsur): 550 MiB is used by DIB and seems a common guidance:
# https://www.rodsbooks.com/efi-bootloaders/principles.html
ESP_SIZE_MIB = 550

# NOTE(rpittau) The partition number used to create a raid device.
# Could be changed to variable if we ever decide, for example to create
# some additional partitions (e.g. boot partitions), so md0 is on the
# partition 1, md1 on the partition 2, and so on.
RAID_PARTITION = 1


def get_block_devices_for_raid(block_devices, logical_disks):
    """Get block devices that are involved in the RAID configuration.

    This call does two things:
    * Collect all block devices that are involved in RAID.
    * Update each logical disks with suitable block devices.
    """
    serialized_devs = [dev.serialize() for dev in block_devices]
    # NOTE(dtantsur): we're going to modify the structure, so make a copy
    logical_disks = copy.deepcopy(logical_disks)
    # NOTE(dtantsur): using a list here is less efficient than a set, but
    # allows keeping the original ordering.
    result = []
    for logical_disk in logical_disks:
        if logical_disk.get('physical_disks'):
            matching = []
            for phys_disk in logical_disk['physical_disks']:
                candidates = [
                    dev['name'] for dev in il_utils.find_devices_by_hints(
                        serialized_devs, phys_disk)
                ]
                if not candidates:
                    raise errors.SoftwareRAIDError(
                        "No candidates for physical disk %(hints)s "
                        "from the list %(devices)s"
                        % {'hints': phys_disk, 'devices': serialized_devs})

                try:
                    matching.append(next(x for x in candidates
                                         if x not in matching))
                except StopIteration:
                    raise errors.SoftwareRAIDError(
                        "No candidates left for physical disk %(hints)s "
                        "from the list %(candidates)s after picking "
                        "%(matching)s for previous volumes"
                        % {'hints': phys_disk, 'matching': matching,
                           'candidates': candidates})
        else:
            # This RAID device spans all disks.
            matching = [dev.name for dev in block_devices]

        # Update the result keeping the ordering and avoiding duplicates.
        result.extend(disk for disk in matching if disk not in result)
        logical_disk['block_devices'] = matching

    return result, logical_disks


def calculate_raid_start(target_boot_mode, partition_table_type, dev_name):
    """Define the start sector for the raid partition.

    :param target_boot_mode: the node boot mode.
    :param partition_table_type: the node partition label, gpt or msdos.
    :param dev_name: block device in the raid configuration.
    :return: The start sector for the raid partition.
    """
    # TODO(rg): TBD, several options regarding boot part slots here:
    # 1. Create boot partitions in prevision
    # 2. Just leave space
    # 3. Do nothing: rely on the caller to specify target_raid_config
    # correctly according to what they intend to do (e.g. not set MAX
    # if they know they will need some space for bios boot or efi
    # parts). Best option imo, if we accept that the target volume
    # granularity is GiB, so you lose up to 1GiB just for a bios boot
    # partition...
    if target_boot_mode == 'uefi':
        # Leave 551MiB - start_sector s for the esp (approx 550 MiB)
        # TODO(dtantsur): 550 MiB is a waste in most cases, make it
        # configurable?
        raid_start = '%sMiB' % (ESP_SIZE_MIB + 1)
    else:
        if partition_table_type == 'gpt':
            # Leave 8MiB - start_sector s (approx 7MiB)
            # for the bios boot partition or the ppc prepboot part
            # This should avoid grub errors saying that it cannot
            # install boot stage 1.5/2 (since the mbr gap does not
            # exist on disk holders with gpt tables)
            raid_start = '8MiB'
        else:
            # sgdisk works fine for display data on mbr tables too
            out, _u = utils.execute('sgdisk', '-F', dev_name)
            raid_start = "{}s".format(out.splitlines()[-1])

    return raid_start


def calc_raid_partition_sectors(psize, start):
    """Calculates end sector and converts start and end sectors including

    the unit of measure, compatible with parted.
    :param psize: size of the raid partition
    :param start: start sector of the raid partition in integer format
    :return: start and end sector in parted compatible format, end sector
        as integer
    """

    if isinstance(start, int):
        start_str = '%dGiB' % start
    else:
        start_str = start

    if psize == -1:
        end_str = '-1'
        end = '-1'
    else:
        if isinstance(start, int):
            end = start + psize
        else:
            # First partition case, start is sth like 2048s
            end = psize
        end_str = '%dGiB' % end

    return start_str, end_str, end


def create_raid_partition_tables(block_devices, partition_table_type,
                                 target_boot_mode):
    """Creates partition tables in all disks in a RAID configuration and

    reports the starting sector for each partition on each disk.
    :param block_devices: disks where we want to create the partition tables.
    :param partition_table_type: type of partition table to create, for example
        gpt or msdos.
    :param target_boot_mode: the node selected boot mode, for example uefi
        or bios.
    :return: a dictionary of devices and the start of the corresponding
        partition.
    """
    parted_start_dict = {}
    for dev_name in block_devices:
        utils.create_partition_table(dev_name, partition_table_type)
        parted_start_dict[dev_name] = calculate_raid_start(
            target_boot_mode, partition_table_type, dev_name)
    return parted_start_dict


def _get_actual_component_devices(raid_device):
    """Get the component devices of a Software RAID device.

    Examine an md device and return its constituent devices.

    :param raid_device: A Software RAID block device name.
    :returns: A list of the component devices.
    """
    if not raid_device:
        return []

    try:
        out, _ = utils.execute('mdadm', '--detail', raid_device,
                               use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        LOG.warning('Could not get component devices of %(dev)s: %(err)s',
                    {'dev': raid_device, 'err': e})
        return []

    component_devices = []
    lines = out.splitlines()
    # the first line contains the md device itself
    for line in lines[1:]:
        device = re.findall(r'/dev/\w+', line)
        component_devices += device

    return component_devices


def create_raid_device(index, logical_disk):
    """Create a raid device.

    :param index: the index of the resulting md device.
    :param logical_disk: the logical disk containing the devices used to
        crete the raid.
    :raise: errors.SoftwareRAIDError if not able to create the raid device
        or fails to re-add a device to a raid.
    """
    md_device = '/dev/md%d' % index
    component_devices = []
    for device in logical_disk['block_devices']:
        # The partition delimiter for all common harddrives (sd[a-z]+)
        part_delimiter = ''
        if 'nvme' in device:
            part_delimiter = 'p'
        component_devices.append(
            device + part_delimiter + str(index + RAID_PARTITION))
    raid_level = logical_disk['raid_level']
    # The schema check allows '1+0', but mdadm knows it as '10'.
    if raid_level == '1+0':
        raid_level = '10'
    volume_name = logical_disk.get('volume_name')
    try:
        if volume_name is None:
            volume_name = md_device
        LOG.debug("Creating md device %(dev)s with name %(name)s"
                  "on %(comp)s",
                  {'dev': md_device, 'name': volume_name,
                   'comp': component_devices})
        utils.execute('mdadm', '--create', md_device, '--force',
                      '--run', '--metadata=1', '--level', raid_level,
                      '--name', volume_name, '--raid-devices',
                      len(component_devices), *component_devices)

    except processutils.ProcessExecutionError as e:
        msg = "Failed to create md device {} on {}: {}".format(
            md_device, ' '.join(component_devices), e)
        raise errors.SoftwareRAIDError(msg)

    # check for missing devices and re-add them
    actual_components = _get_actual_component_devices(md_device)
    missing = set(component_devices) - set(actual_components)
    for dev in missing:
        try:
            LOG.warning('Found %(device)s to be missing from %(md)s '
                        '... re-adding!',
                        {'device': dev, 'md': md_device})
            utils.execute('mdadm', '--add', md_device, dev,
                          attempts=3, delay_on_retry=True)
        except processutils.ProcessExecutionError as e:
            msg = "Failed re-add {} to {}: {}".format(
                dev, md_device, e)
            raise errors.SoftwareRAIDError(msg)


def get_next_free_raid_device():
    """Get a device name that is still free."""
    from ironic_python_agent import hardware

    names = {dev.name for dev in
             hardware.dispatch_to_managers('list_block_devices')}
    for idx in range(128):
        name = f'/dev/md{idx}'
        if name not in names:
            return name
    raise errors.SoftwareRAIDError("No free md (RAID) devices are left")


def get_volume_name_of_raid_device(raid_device):
    """Get the volume name of a RAID device

    :param raid_device: A Software RAID block device name.
    :returns: volume name of the device, or None
    """
    if not raid_device:
        return None
    try:
        out, _ = utils.execute('mdadm', '--detail', raid_device,
                               use_standard_locale=True)
    except processutils.ProcessExecutionError as e:
        LOG.warning('Could not retrieve the volume name of %(dev)s: %(err)s',
                    {'dev': raid_device, 'err': e})
        return None
    lines = out.splitlines()
    for line in lines:
        if re.search(r'Name', line) is not None:
            split_array = line.split(':')
            # expecting format:
            # Name : <host>:name (optional comment)
            if len(split_array) == 3:
                candidate = split_array[2]
            else:
                return None
            # if name is followed by some other text
            # such as (local to host <domain>) remove
            # everything after " "
            if " " in candidate:
                candidate = candidate.split(" ")[0]
            volume_name = candidate
            return volume_name
    return None


# TODO(rg): handle PreP boot parts relocation as well
def prepare_boot_partitions_for_softraid(device, holders, efi_part,
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
            efi_part = disk_utils.find_efi_partition(device)
            if efi_part:
                efi_part = '{}p{}'.format(device, efi_part['number'])

        # check if we have a RAIDed ESP already
        md_device = find_esp_raid()
        if md_device:
            LOG.info("Found RAIDed ESP %s, skip creation", md_device)
        else:
            LOG.info("Creating EFI partitions on software RAID holder disks")
            # We know that we kept this space when configuring raid,see
            # hardware.GenericHardwareManager.create_configuration.
            # We could also directly get the EFI partition size.
            partsize_mib = ESP_SIZE_MIB
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
                    "blkid", "-l", "-t", "PARTLABEL={}".format(partlabel),
                    holder)

                target_part = target_part.splitlines()[-1].split(':', 1)[0]
                efi_partitions.append(target_part)

                LOG.debug("EFI partition %s created on holder disk %s",
                          target_part, holder)

            # RAID the ESPs, metadata=1.0 is mandatory to be able to boot
            md_device = get_next_free_raid_device()
            LOG.debug("Creating md device %(md_device)s for the ESPs "
                      "on %(efi_partitions)s",
                      {'md_device': md_device,
                       'efi_partitions': efi_partitions})
            utils.execute('mdadm', '--create', md_device, '--force',
                          '--run', '--metadata=1.0', '--level', '1',
                          '--name', 'esp', '--raid-devices',
                          len(efi_partitions),
                          *efi_partitions)

            disk_utils.trigger_device_rescan(md_device)

        if efi_part:
            # Blockdev copy the source ESP and erase it
            LOG.debug("Relocating EFI %s to %s", efi_part, md_device)
            utils.execute('cp', efi_part, md_device)
            LOG.debug("Erasing EFI partition %s", efi_part)
            utils.execute('wipefs', '-a', efi_part)
        else:
            fslabel = 'efi-part'
            il_utils.mkfs(fs='vfat', path=md_device, label=fslabel)

        return md_device

    elif target_boot_mode == 'bios':
        partlabel_prefix = 'bios-boot-part-'
        for number, holder in enumerate(holders):
            label = disk_utils.get_partition_table_type(holder)
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


def find_esp_raid():
    """Find the ESP md device in case of a rebuild."""

    # find devices of type 'RAID1' and fstype 'VFAT'
    lsblk = utils.execute('lsblk', '-PbioNAME,TYPE,FSTYPE')
    report = lsblk[0]
    for line in report.split('\n'):
        dev = {}
        vals = shlex.split(line)
        for key, val in (v.split('=', 1) for v in vals):
            dev[key] = val.strip()
        if dev.get('TYPE') == 'raid1' and dev.get('FSTYPE') == 'vfat':
            return '/dev/' + dev.get('NAME')

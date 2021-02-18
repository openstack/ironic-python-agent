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

from ironic_lib import utils as il_utils
from oslo_concurrency import processutils
from oslo_log import log as logging

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
    :param start: start sector of the raid partion in integer format
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
    try:
        LOG.debug("Creating md device %(dev)s on %(comp)s",
                  {'dev': md_device, 'comp': component_devices})
        utils.execute('mdadm', '--create', md_device, '--force',
                      '--run', '--metadata=1', '--level', raid_level,
                      '--raid-devices', len(component_devices),
                      *component_devices)
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

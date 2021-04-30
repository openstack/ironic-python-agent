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

"""
Logic related to handling partitions.

Imported from ironic-lib's disk_utils as of the following commit:
https://opendev.org/openstack/ironic-lib/commit/9fb5be348202f4854a455cd08f400ae12b99e1f2
"""

import base64
import gzip
import io
import math
import os
import shutil
import tempfile

from ironic_lib import disk_utils
from ironic_lib import exception
from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import units
import requests


LOG = log.getLogger()

MAX_CONFIG_DRIVE_SIZE_MB = 64

# Maximum disk size supported by MBR is 2TB (2 * 1024 * 1024 MB)
MAX_DISK_SIZE_MB_SUPPORTED_BY_MBR = 2097152


def get_configdrive(configdrive, node_uuid, tempdir=None):
    """Get the information about size and location of the configdrive.

    :param configdrive: Base64 encoded Gzipped configdrive content or
        configdrive HTTP URL.
    :param node_uuid: Node's uuid. Used for logging.
    :param tempdir: temporary directory for the temporary configdrive file
    :raises: InstanceDeployFailure if it can't download or decode the
       config drive.
    :returns: A tuple with the size in MiB and path to the uncompressed
        configdrive file.

    """
    # Check if the configdrive option is a HTTP URL or the content directly
    is_url = utils.is_http_url(configdrive)
    if is_url:
        try:
            data = requests.get(configdrive).content
        except requests.exceptions.RequestException as e:
            raise exception.InstanceDeployFailure(
                "Can't download the configdrive content for node %(node)s "
                "from '%(url)s'. Reason: %(reason)s" %
                {'node': node_uuid, 'url': configdrive, 'reason': e})
    else:
        data = configdrive

    configdrive_file = tempfile.NamedTemporaryFile(delete=False,
                                                   prefix='configdrive',
                                                   dir=tempdir)

    try:
        data = io.BytesIO(base64.b64decode(data))
    except Exception as exc:
        if isinstance(data, bytes):
            LOG.debug('Config drive for node %(node)s is not base64 encoded '
                      '(%(error)s), assuming binary',
                      {'node': node_uuid, 'error': exc})
            configdrive_mb = int(math.ceil(len(data) / units.Mi))
            configdrive_file.write(data)
            configdrive_file.close()
            return (configdrive_mb, configdrive_file.name)
        else:
            configdrive_file.close()
            utils.unlink_without_raise(configdrive_file.name)

            error_msg = ('Config drive for node %(node)s is not base64 '
                         'encoded or the content is malformed. '
                         '%(cls)s: %(err)s.'
                         % {'node': node_uuid, 'err': exc,
                            'cls': type(exc).__name__})
            if is_url:
                error_msg += ' Downloaded from "%s".' % configdrive
            raise exception.InstanceDeployFailure(error_msg)

    configdrive_mb = 0
    with gzip.GzipFile('configdrive', 'rb', fileobj=data) as gunzipped:
        try:
            shutil.copyfileobj(gunzipped, configdrive_file)
        except EnvironmentError as e:
            # Delete the created file
            utils.unlink_without_raise(configdrive_file.name)
            raise exception.InstanceDeployFailure(
                'Encountered error while decompressing and writing '
                'config drive for node %(node)s. Error: %(exc)s' %
                {'node': node_uuid, 'exc': e})
        else:
            # Get the file size and convert to MiB
            configdrive_file.seek(0, os.SEEK_END)
            bytes_ = configdrive_file.tell()
            configdrive_mb = int(math.ceil(float(bytes_) / units.Mi))
        finally:
            configdrive_file.close()

        return (configdrive_mb, configdrive_file.name)


def get_labelled_partition(device_path, label, node_uuid):
    """Check and return if partition with given label exists

    :param device_path: The device path.
    :param label: Partition label
    :param node_uuid: UUID of the Node. Used for logging.
    :raises: InstanceDeployFailure, if any disk partitioning related
        commands fail.
    :returns: block device file for partition if it exists; otherwise it
              returns None.
    """
    disk_utils.partprobe(device_path)
    try:
        output, err = utils.execute('lsblk', '-Po', 'name,label', device_path,
                                    check_exit_code=[0, 1],
                                    use_standard_locale=True, run_as_root=True)

    except (processutils.UnknownArgumentError,
            processutils.ProcessExecutionError, OSError) as e:
        msg = ('Failed to retrieve partition labels on disk %(disk)s '
               'for node %(node)s. Error: %(error)s' %
               {'disk': device_path, 'node': node_uuid, 'error': e})
        LOG.error(msg)
        raise exception.InstanceDeployFailure(msg)

    found_part = None
    if output:
        for dev in utils.parse_device_tags(output):
            if dev['LABEL'].upper() == label.upper():
                if found_part:
                    found_2 = '/dev/%(part)s' % {'part': dev['NAME'].strip()}
                    found = [found_part, found_2]
                    raise exception.InstanceDeployFailure(
                        'More than one partition with label "%(label)s" '
                        'exists on device %(device)s for node %(node)s: '
                        '%(found)s.' %
                        {'label': label, 'device': device_path,
                         'node': node_uuid, 'found': ' and '.join(found)})
                found_part = '/dev/%(part)s' % {'part': dev['NAME'].strip()}

    return found_part


def work_on_disk(dev, root_mb, swap_mb, ephemeral_mb, ephemeral_format,
                 image_path, node_uuid, preserve_ephemeral=False,
                 configdrive=None, boot_option="netboot", boot_mode="bios",
                 tempdir=None, disk_label=None, cpu_arch="", conv_flags=None):
    """Create partitions and copy an image to the root partition.

    :param dev: Path for the device to work on.
    :param root_mb: Size of the root partition in megabytes.
    :param swap_mb: Size of the swap partition in megabytes.
    :param ephemeral_mb: Size of the ephemeral partition in megabytes. If 0,
        no ephemeral partition will be created.
    :param ephemeral_format: The type of file system to format the ephemeral
        partition.
    :param image_path: Path for the instance's disk image. If ``None``,
        the root partition is prepared but not populated.
    :param node_uuid: node's uuid. Used for logging.
    :param preserve_ephemeral: If True, no filesystem is written to the
        ephemeral block device, preserving whatever content it had (if the
        partition table has not changed).
    :param configdrive: Optional. Base64 encoded Gzipped configdrive content
                        or configdrive HTTP URL.
    :param boot_option: Can be "local" or "netboot". "netboot" by default.
    :param boot_mode: Can be "bios" or "uefi". "bios" by default.
    :param tempdir: A temporary directory
    :param disk_label: The disk label to be used when creating the
        partition table. Valid values are: "msdos", "gpt" or None; If None
        Ironic will figure it out according to the boot_mode parameter.
    :param cpu_arch: Architecture of the node the disk device belongs to.
        When using the default value of None, no architecture specific
        steps will be taken. This default should be used for x86_64. When
        set to ppc64*, architecture specific steps are taken for booting a
        partition image locally.
    :param conv_flags: Flags that need to be sent to the dd command, to control
        the conversion of the original file when copying to the host. It can
        contain several options separated by commas.
    :returns: a dictionary containing the following keys:
        'root uuid': UUID of root partition
        'efi system partition uuid': UUID of the uefi system partition
        (if boot mode is uefi).
        `partitions`: mapping of partition types to their device paths.
        NOTE: If key exists but value is None, it means partition doesn't
        exist.
    """
    # the only way for preserve_ephemeral to be set to true is if we are
    # rebuilding an instance with --preserve_ephemeral.
    commit = not preserve_ephemeral
    # now if we are committing the changes to disk clean first.
    if commit:
        disk_utils.destroy_disk_metadata(dev, node_uuid)

    try:
        # If requested, get the configdrive file and determine the size
        # of the configdrive partition
        configdrive_mb = 0
        configdrive_file = None
        if configdrive:
            configdrive_mb, configdrive_file = get_configdrive(
                configdrive, node_uuid, tempdir=tempdir)

        part_dict = disk_utils.make_partitions(dev,
                                               root_mb, swap_mb, ephemeral_mb,
                                               configdrive_mb, node_uuid,
                                               commit=commit,
                                               boot_option=boot_option,
                                               boot_mode=boot_mode,
                                               disk_label=disk_label,
                                               cpu_arch=cpu_arch)
        LOG.info("Successfully completed the disk device"
                 " %(dev)s partitioning for node %(node)s",
                 {'dev': dev, "node": node_uuid})

        ephemeral_part = part_dict.get('ephemeral')
        swap_part = part_dict.get('swap')
        configdrive_part = part_dict.get('configdrive')
        root_part = part_dict.get('root')

        if not disk_utils.is_block_device(root_part):
            raise exception.InstanceDeployFailure(
                "Root device '%s' not found" % root_part)

        for part in ('swap', 'ephemeral', 'configdrive',
                     'efi system partition', 'PReP Boot partition'):
            part_device = part_dict.get(part)
            LOG.debug("Checking for %(part)s device (%(dev)s) on node "
                      "%(node)s.", {'part': part, 'dev': part_device,
                                    'node': node_uuid})
            if part_device and not disk_utils.is_block_device(part_device):
                raise exception.InstanceDeployFailure(
                    "'%(partition)s' device '%(part_device)s' not found" %
                    {'partition': part, 'part_device': part_device})

        # If it's a uefi localboot, then we have created the efi system
        # partition.  Create a fat filesystem on it.
        if boot_mode == "uefi" and boot_option == "local":
            efi_system_part = part_dict.get('efi system partition')
            utils.mkfs(fs='vfat', path=efi_system_part, label='efi-part')

        if configdrive_part:
            # Copy the configdrive content to the configdrive partition
            disk_utils.dd(configdrive_file, configdrive_part,
                          conv_flags=conv_flags)
            LOG.info("Configdrive for node %(node)s successfully copied "
                     "onto partition %(partition)s",
                     {'node': node_uuid, 'partition': configdrive_part})

    finally:
        # If the configdrive was requested make sure we delete the file
        # after copying the content to the partition
        if configdrive_file:
            utils.unlink_without_raise(configdrive_file)

    if image_path is not None:
        disk_utils.populate_image(image_path, root_part, conv_flags=conv_flags)
        LOG.info("Image for %(node)s successfully populated",
                 {'node': node_uuid})
    else:
        LOG.debug("Root partition for %s was created, but not populated",
                  node_uuid)

    if swap_part:
        utils.mkfs(fs='swap', path=swap_part, label='swap1')
        LOG.info("Swap partition %(swap)s successfully formatted "
                 "for node %(node)s",
                 {'swap': swap_part, 'node': node_uuid})

    if ephemeral_part and not preserve_ephemeral:
        utils.mkfs(fs=ephemeral_format, path=ephemeral_part,
                   label="ephemeral0")
        LOG.info("Ephemeral partition %(ephemeral)s successfully "
                 "formatted for node %(node)s",
                 {'ephemeral': ephemeral_part, 'node': node_uuid})

    uuids_to_return = {
        'root uuid': root_part,
        'efi system partition uuid': part_dict.get('efi system partition'),
    }

    if cpu_arch.startswith('ppc'):
        uuids_to_return[
            'PReP Boot partition uuid'
        ] = part_dict.get('PReP Boot partition')

    try:
        for part, part_dev in uuids_to_return.items():
            if part_dev:
                uuids_to_return[part] = disk_utils.block_uuid(part_dev)

    except processutils.ProcessExecutionError:
        with excutils.save_and_reraise_exception():
            LOG.error("Failed to detect %s", part)

    return dict(partitions=part_dict, **uuids_to_return)


def create_config_drive_partition(node_uuid, device, configdrive):
    """Create a partition for config drive

    Checks if the device is GPT or MBR partitioned and creates config drive
    partition accordingly.

    :param node_uuid: UUID of the Node.
    :param device: The device path.
    :param configdrive: Base64 encoded Gzipped configdrive content or
        configdrive HTTP URL.
    :raises: InstanceDeployFailure if config drive size exceeds maximum limit
        or if it fails to create config drive.
    """
    confdrive_file = None
    try:
        config_drive_part = get_labelled_partition(
            device, disk_utils.CONFIGDRIVE_LABEL, node_uuid)

        confdrive_mb, confdrive_file = get_configdrive(configdrive, node_uuid)
        if confdrive_mb > MAX_CONFIG_DRIVE_SIZE_MB:
            raise exception.InstanceDeployFailure(
                'Config drive size exceeds maximum limit of 64MiB. '
                'Size of the given config drive is %(size)d MiB for '
                'node %(node)s.'
                % {'size': confdrive_mb, 'node': node_uuid})

        LOG.debug("Adding config drive partition %(size)d MiB to "
                  "device: %(dev)s for node %(node)s",
                  {'dev': device, 'size': confdrive_mb, 'node': node_uuid})

        disk_utils.fix_gpt_partition(device, node_uuid)
        if config_drive_part:
            LOG.debug("Configdrive for node %(node)s exists at "
                      "%(part)s",
                      {'node': node_uuid, 'part': config_drive_part})
        else:
            cur_parts = set(part['number']
                            for part in disk_utils.list_partitions(device))

            if disk_utils.get_partition_table_type(device) == 'gpt':
                create_option = '0:-%dMB:0' % MAX_CONFIG_DRIVE_SIZE_MB
                utils.execute('sgdisk', '-n', create_option, device,
                              run_as_root=True)
            else:
                # Check if the disk has 4 partitions. The MBR based disk
                # cannot have more than 4 partitions.
                # TODO(stendulker): One can use logical partitions to create
                # a config drive if there are 3 primary partitions.
                # https://bugs.launchpad.net/ironic/+bug/1561283
                try:
                    pp_count, lp_count = disk_utils.count_mbr_partitions(
                        device)
                except ValueError as e:
                    raise exception.InstanceDeployFailure(
                        'Failed to check the number of primary partitions '
                        'present on %(dev)s for node %(node)s. Error: '
                        '%(error)s' % {'dev': device, 'node': node_uuid,
                                       'error': e})
                if pp_count > 3:
                    raise exception.InstanceDeployFailure(
                        'Config drive cannot be created for node %(node)s. '
                        'Disk (%(dev)s) uses MBR partitioning and already '
                        'has %(parts)d primary partitions.'
                        % {'node': node_uuid, 'dev': device,
                           'parts': pp_count})

                # Check if disk size exceeds 2TB msdos limit
                startlimit = '-%dMiB' % MAX_CONFIG_DRIVE_SIZE_MB
                endlimit = '-0'
                if _is_disk_larger_than_max_size(device, node_uuid):
                    # Need to create a small partition at 2TB limit
                    LOG.warning("Disk size is larger than 2TB for "
                                "node %(node)s. Creating config drive "
                                "at the end of the disk %(disk)s.",
                                {'node': node_uuid, 'disk': device})
                    startlimit = (MAX_DISK_SIZE_MB_SUPPORTED_BY_MBR
                                  - MAX_CONFIG_DRIVE_SIZE_MB - 1)
                    endlimit = MAX_DISK_SIZE_MB_SUPPORTED_BY_MBR - 1

                utils.execute('parted', '-a', 'optimal', '-s', '--', device,
                              'mkpart', 'primary', 'fat32', startlimit,
                              endlimit, run_as_root=True)
            # Trigger device rescan
            disk_utils.trigger_device_rescan(device)

            upd_parts = set(part['number']
                            for part in disk_utils.list_partitions(device))
            new_part = set(upd_parts) - set(cur_parts)
            if len(new_part) != 1:
                raise exception.InstanceDeployFailure(
                    'Disk partitioning failed on device %(device)s. '
                    'Unable to retrieve config drive partition information.'
                    % {'device': device})

            config_drive_part = disk_utils.partition_index_to_path(
                device, new_part.pop())

            disk_utils.udev_settle()

            # NOTE(vsaienko): check that devise actually exists,
            # it is not handled by udevadm when using ISCSI, for more info see:
            # https://bugs.launchpad.net/ironic/+bug/1673731
            # Do not use 'udevadm settle --exit-if-exist' here
            LOG.debug('Waiting for the config drive partition %(part)s '
                      'on node %(node)s to be ready for writing.',
                      {'part': config_drive_part, 'node': node_uuid})
            utils.execute('test', '-e', config_drive_part, attempts=15,
                          delay_on_retry=True)

        disk_utils.dd(confdrive_file, config_drive_part)
        LOG.info("Configdrive for node %(node)s successfully "
                 "copied onto partition %(part)s",
                 {'node': node_uuid, 'part': config_drive_part})

    except (processutils.UnknownArgumentError,
            processutils.ProcessExecutionError, OSError) as e:
        msg = ('Failed to create config drive on disk %(disk)s '
               'for node %(node)s. Error: %(error)s' %
               {'disk': device, 'node': node_uuid, 'error': e})
        LOG.error(msg)
        raise exception.InstanceDeployFailure(msg)
    finally:
        # If the configdrive was requested make sure we delete the file
        # after copying the content to the partition
        if confdrive_file:
            utils.unlink_without_raise(confdrive_file)


def _is_disk_larger_than_max_size(device, node_uuid):
    """Check if total disk size exceeds 2TB msdos limit

    :param device: device path.
    :param node_uuid: node's uuid. Used for logging.
    :raises: InstanceDeployFailure, if any disk partitioning related
        commands fail.
    :returns: True if total disk size exceeds 2TB. Returns False otherwise.
    """
    try:
        disksize_bytes, err = utils.execute('blockdev', '--getsize64',
                                            device,
                                            use_standard_locale=True,
                                            run_as_root=True)
    except (processutils.UnknownArgumentError,
            processutils.ProcessExecutionError, OSError) as e:
        msg = ('Failed to get size of disk %(disk)s for node %(node)s. '
               'Error: %(error)s' %
               {'disk': device, 'node': node_uuid, 'error': e})
        LOG.error(msg)
        raise exception.InstanceDeployFailure(msg)

    disksize_mb = int(disksize_bytes.strip()) // 1024 // 1024

    return disksize_mb > MAX_DISK_SIZE_MB_SUPPORTED_BY_MBR

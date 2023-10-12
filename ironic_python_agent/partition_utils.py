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
import stat
import tempfile

from ironic_lib import disk_utils
from ironic_lib import exception
from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import units
from oslo_utils import uuidutils
import requests

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import utils as ipa_utils


LOG = log.getLogger()
CONF = cfg.CONF

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
        verify, cert = ipa_utils.get_ssl_client_options(CONF)
        timeout = CONF.image_download_connection_timeout
        # TODO(dtantsur): support proxy parameters from instance_info
        try:
            resp = requests.get(configdrive, verify=verify, cert=cert,
                                timeout=timeout)
        except requests.exceptions.RequestException as e:
            raise exception.InstanceDeployFailure(
                "Can't download the configdrive content for node %(node)s "
                "from '%(url)s'. Reason: %(reason)s" %
                {'node': node_uuid, 'url': configdrive, 'reason': e})

        if resp.status_code >= 400:
            raise exception.InstanceDeployFailure(
                "Can't download the configdrive content for node %(node)s "
                "from '%(url)s'. Got status code %(code)s, response "
                "body %(body)s" %
                {'node': node_uuid, 'url': configdrive,
                 'code': resp.status_code, 'body': resp.text})

        data = resp.content
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
                 configdrive=None, boot_mode="bios",
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
                                               boot_option='local',
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
        if boot_mode == "uefi":
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

    # Rescan device to get current status (e.g. reflect modification of mkfs)
    disk_utils.trigger_device_rescan(dev)

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
            part_uuid = None
            if disk_utils.get_partition_table_type(device) == 'gpt':
                part_uuid = uuidutils.generate_uuid()
                create_option = '0:-%dMB:0' % MAX_CONFIG_DRIVE_SIZE_MB
                uuid_option = '0:%s' % part_uuid
                utils.execute('sgdisk', '-n', create_option,
                              '-u', uuid_option, device,
                              run_as_root=True)
            else:
                cur_parts = set(part['number']
                                for part in disk_utils.list_partitions(device))

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

            if part_uuid is None:
                new_parts = {part['number']: part
                             for part in disk_utils.list_partitions(device)}
                new_part = set(new_parts) - set(cur_parts)
                if len(new_part) != 1:
                    raise exception.InstanceDeployFailure(
                        'Disk partitioning failed on device %(device)s. '
                        'Unable to retrieve config drive partition '
                        'information.' % {'device': device})

                config_drive_part = disk_utils.partition_index_to_path(
                    device, new_part.pop())
            else:
                try:
                    config_drive_part = get_partition(device, part_uuid)
                except errors.DeviceNotFound:
                    msg = ('Failed to create config drive on disk %(disk)s '
                           'for node %(node)s. Partition with UUID %(uuid)s '
                           'has not been found after creation.') % {
                               'disk': device, 'node': node_uuid,
                               'uuid': part_uuid}
                    LOG.error(msg)
                    raise exception.InstanceDeployFailure(msg)

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
        if not CONF.config_drive_rebuild:
            disk_utils.dd(confdrive_file, config_drive_part)
            if not _does_config_drive_work(config_drive_part):
                # If we have reached this point, we might have an
                # invalid configuration drive, OR the block device
                # layer doesn't support 2K block Logical IO (iso9660)
                _try_build_fat32_config_drive(config_drive_part,
                                              confdrive_file)
        else:
            LOG.info('Extracting configuration drive to write copy to disk.')
            _try_build_fat32_config_drive(config_drive_part, confdrive_file)
        LOG.info("Configdrive for node %(node)s successfully "
                 "copied onto partition %(part)s",
                 {'node': node_uuid, 'part': config_drive_part})

    except exception.InstanceDeployFailure:
        # Since we no longer have a final action on the decorator, we need
        # to catch the failure, and still perform the cleanup.
        if confdrive_file:
            utils.unlink_without_raise(confdrive_file)
        raise
    except (processutils.UnknownArgumentError,
            processutils.ProcessExecutionError, OSError) as e:
        msg = ('Failed to create config drive on disk %(disk)s '
               'for node %(node)s. Error: %(error)s' %
               {'disk': device, 'node': node_uuid, 'error': e})
        LOG.error(msg)
        raise exception.InstanceDeployFailure(msg)
        # If the configdrive was requested make sure we delete the file
        # after copying the content to the partition

    finally:
        if confdrive_file:
            utils.unlink_without_raise(confdrive_file)


def _does_config_drive_work(config_drive_part):
    """Attempts to mount the config drive to validate it works.

    :param config_drive_part: The partition to which the configuration drive
                              was written.
    :returns: True if we were able to mount the configuration drive partition.
    """
    temp_folder = tempfile.mkdtemp()
    try:
        # Why: If the filesystem is ISO9660 or vfat, and the logical sector
        # size which is supported is *not* something which supports 512 bytes,
        # i.e. a 4k Block size, then ISO9660 just will not work. Vfat also
        # will not work because the logical size needs to match the logical
        # size which is usable. If the underlying driver cannot use that size,
        # then the filesystem will not work and cannot be updated because
        # structurally it is incompaible with the block device driver.
        utils.execute('mount', '-o', 'ro', '-t', 'auto', config_drive_part,
                      temp_folder)
        utils.execute('umount', temp_folder)
    except (processutils.ProcessExecutionError, OSError) as e:
        LOG.error('Encountered issue attempting to validate the '
                  'supplied configuration drive. Error: %s', e)
        return False
    finally:
        utils.unlink_without_raise(temp_folder)

    return True


def _try_build_fat32_config_drive(partition, confdrive_file):
    conf_drive_temp = tempfile.mkdtemp()
    try:
        utils.execute('mount', '-o', 'loop,ro', '-t', 'auto',
                      confdrive_file, conf_drive_temp)
    except (processutils.ProcessExecutionError, OSError) as e:
        # Config drive is invalid, at least to our point of view.
        # Bailing.
        LOG.warning('We were unable to examine the configuration drive, '
                    'bypassing. Error: %s', e)
        return

    new_drive_temp = tempfile.mkdtemp()
    try:
        # While creating a config drive file from scratch or on
        # a loopback will likely result in a 512 byte sector size,
        # the underlying fat filesystem utilities *automatically*
        # check the device block sector sizing. This *will* break
        # above 4k blocks, or at least might. Officially, 4k is the
        # *maximum* in the FAT standard. See:
        # https://github.com/dosfstools/dosfstools/blame/c483196dd46eab22abba756cef511d36f5f42070/src/mkfs.fat.c#L1987
        utils.mkfs(fs='vfat', path=partition, label='CONFIG-2')
        utils.execute('mount', '-t', 'auto', partition, new_drive_temp)
        # copytree, using copy2, copies everything in the source folder
        # into the destination folder, so we should be good, and metadata
        # is attempted to be preserved.
        shutil.copytree(conf_drive_temp, new_drive_temp, dirs_exist_ok=True)
    except (processutils.ProcessExecutionError, OSError) as e:
        # We failed to make the filesystem :(
        # This is a fairly hard error as we could not use the
        # config drive, nor could we recover the state.
        LOG.error('We were unable to make a new filesystem for the '
                  'configuration drive. Error: %s', e)
        msg = ('A failure occured while attempting to format, copy, and '
               're-create the configuration drive in a structure which '
               'is compatible with the underlying hardware and Operating '
               'System. Due to the nature of configuration drive, it could '
               'have been incorrectly formatted. Operator investigation is '
               'required. Error: {}'.format(str(e)))
        raise exception.InstanceDeployFailure(msg)
    finally:
        utils.execute('umount', conf_drive_temp)
        utils.execute('umount', new_drive_temp)
        utils.unlink_without_raise(new_drive_temp)
        utils.unlink_without_raise(conf_drive_temp)


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


def get_partition(device, uuid):
    """Find the partition of a given device."""
    LOG.debug("Find the partition %(uuid)s on device %(dev)s",
              {'dev': device, 'uuid': uuid})

    try:
        ipa_utils.rescan_device(device)
        lsblk, _ = utils.execute(
            'lsblk', '-PbioKNAME,UUID,PARTUUID,TYPE,LABEL', device)
        if lsblk:
            for dev in utils.parse_device_tags(lsblk):
                # Ignore non partition
                if dev.get('TYPE') not in ['md', 'part']:
                    # NOTE(TheJulia): This technically creates an edge failure
                    # case where a filesystem on a whole block device sans
                    # partitioning would behave differently.
                    continue

                if dev.get('UUID') == uuid:
                    LOG.debug("Partition %(uuid)s found on device "
                              "%(dev)s", {'uuid': uuid, 'dev': device})
                    return '/dev/' + dev.get('KNAME')
                if dev.get('PARTUUID') == uuid:
                    LOG.debug("Partition %(uuid)s found on device "
                              "%(dev)s", {'uuid': uuid, 'dev': device})
                    return '/dev/' + dev.get('KNAME')
                if dev.get('LABEL') == uuid:
                    LOG.debug("Partition %(uuid)s found on device "
                              "%(dev)s", {'uuid': uuid, 'dev': device})
                    return '/dev/' + dev.get('KNAME')
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
                              'Error: %(err)s', {'uuid': uuid, 'err': e})
                    try:
                        findfs, stderr = utils.execute(
                            'findfs', 'PARTUUID=%s' % uuid)
                        return findfs.strip()
                    except processutils.ProcessExecutionError as e:
                        LOG.debug('Secondary fallback detection attempt for '
                                  'locating partition via UUID %(id)s failed.'
                                  'Error: %(err)s', {'id': uuid, 'err': e})

                # Last fallback: In case we cannot find the partition by UUID
                # and the deploy device is an md device, we check if the md
                # device has a partition (which we assume to contain the
                # root fs).
                if hardware.is_md_device(device):
                    md_partition = device + 'p1'
                    if (os.path.exists(md_partition)
                            and stat.S_ISBLK(os.stat(md_partition).st_mode)):
                        LOG.debug("Found md device with partition %s",
                                  md_partition)
                        return md_partition
                    else:
                        LOG.debug('Could not find partition %(part)s on md '
                                  'device %(dev)s', {'part': md_partition,
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

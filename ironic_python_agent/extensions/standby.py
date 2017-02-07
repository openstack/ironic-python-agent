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

import hashlib
import os
import requests
import six
import time

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log

from ironic_lib import disk_utils
from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import utils

CONF = cfg.CONF
LOG = log.getLogger(__name__)

IMAGE_CHUNK_SIZE = 1024 * 1024  # 1MB


def _configdrive_location():
    """Get the configdrive location in the local file system.

    :returns: The full, absolute path to the configdrive as a string.
    """
    return '/tmp/configdrive'


def _image_location(image_info):
    """Get the location of the image in the local file system.

    :param image_info: Image information dictionary.
    :returns: The full, absolute path to the image as a string.
    """
    return '/tmp/{}'.format(image_info['id'])


def _path_to_script(script):
    """Get the location of a script which ships with ironic-python-agent.

    :param script: The script name as a string.
    :returns: The relative path to the script.
    """
    cwd = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(cwd, '..', script)


def _write_partition_image(image, image_info, device):
    """Call disk_util to create partition and write the partition image.

    :param image: Local path to image file to be written to the partition.
    :param image_info: Image information dictionary.
    :param device: The device name, as a string, on which to store the image.
                   Example: '/dev/sda'

    :raises: InvalidCommandParamsError if the partition is too small for the
             provided image.
    :raises: ImageWriteError if writing the image to disk encounters any error.
    """
    node_uuid = image_info.get('node_uuid')
    preserve_ep = image_info['preserve_ephemeral']
    configdrive = image_info['configdrive']
    boot_option = image_info.get('boot_option', 'netboot')
    boot_mode = image_info.get('deploy_boot_mode', 'bios')
    disk_label = image_info.get('disk_label', 'msdos')
    image_mb = disk_utils.get_image_mb(image)
    root_mb = image_info['root_mb']
    if image_mb > int(root_mb):
        msg = ('Root partition is too small for requested image. Image '
               'virtual size: {} MB, Root size: {} MB').format(image_mb,
                                                               root_mb)
        raise errors.InvalidCommandParamsError(msg)
    try:
        return disk_utils.work_on_disk(device, root_mb,
                                       image_info['swap_mb'],
                                       image_info['ephemeral_mb'],
                                       image_info['ephemeral_format'],
                                       image, node_uuid,
                                       preserve_ephemeral=preserve_ep,
                                       configdrive=configdrive,
                                       boot_option=boot_option,
                                       boot_mode=boot_mode,
                                       disk_label=disk_label)
    except processutils.ProcessExecutionError as e:
        raise errors.ImageWriteError(device, e.exit_code, e.stdout, e.stderr)


def _write_whole_disk_image(image, image_info, device):
    """Writes a whole disk image to the specified device.

    :param image: Local path to image file to be written to the disk.
    :param image_info: Image information dictionary.
                       This parameter is currently unused by the function.
    :param device: The device name, as a string, on which to store the image.
                   Example: '/dev/sda'

    :raises: ImageWriteError if the command to write the image encounters an
             error.
    """
    script = _path_to_script('shell/write_image.sh')
    command = ['/bin/bash', script, image, device]
    LOG.info('Writing image with command: {}'.format(' '.join(command)))
    try:
        stdout, stderr = utils.execute(*command, check_exit_code=[0])
    except processutils.ProcessExecutionError as e:
        raise errors.ImageWriteError(device, e.exit_code, e.stdout, e.stderr)


def _write_image(image_info, device):
    """Writes an image to the specified device.

    :param image_info: Image information dictionary.
    :param device: The disk name, as a string, on which to store the image.
                   Example: '/dev/sda'
    :raises: ImageWriteError if the command to write the image encounters an
             error.
    """
    starttime = time.time()
    image = _image_location(image_info)
    uuids = {}
    if image_info.get('image_type') == 'partition':
        uuids = _write_partition_image(image, image_info, device)
    else:
        _write_whole_disk_image(image, image_info, device)
    totaltime = time.time() - starttime
    LOG.info('Image {} written to device {} in {} seconds'.format(
             image, device, totaltime))
    return uuids


def _message_format(msg, image_info, device, partition_uuids):
    """Helper method to get and populate different messages."""
    message = None
    result_msg = msg
    if image_info.get('image_type') == 'partition':
        root_uuid = partition_uuids.get('root uuid')
        efi_system_partition_uuid = (
            partition_uuids.get('efi system partition uuid'))
        if (image_info.get('deploy_boot_mode') == 'uefi' and
                image_info.get('boot_option') == 'local'):
            result_msg = msg + 'root_uuid={} efi_system_partition_uuid={}'
            message = result_msg.format(image_info['id'], device,
                                        root_uuid,
                                        efi_system_partition_uuid)
        else:
            result_msg = msg + 'root_uuid={}'
            message = result_msg.format(image_info['id'], device, root_uuid)
    else:
        message = result_msg.format(image_info['id'], device)
    return message


class ImageDownload(object):
    """Helper class that opens a HTTP connection to download an image.

    This class opens a HTTP connection to download an image from a URL
    and create an iterator so the image can be downloaded in chunks. The
    MD5 hash of the image being downloaded is calculated on-the-fly.
    """

    def __init__(self, image_info, time_obj=None):
        """Initialize an instance of the ImageDownload class.

        Trys each URL in image_info successively until a URL returns a
        successful request code. Once the object is initialized, the user may
        retrieve chunks of the image through the standard python iterator
        interface until either the image is fully downloaded, or an error is
        encountered.

        :param image_info: Image information dictionary.
        :param time_obj: Optional time object to indicate when the image
                         download began. Defaults to None. If None, then
                         time.time() will be used to find the start time of
                         the download.

        :raises: ImageDownloadError if starting the image download fails for
                 any reason.
        """
        self._md5checksum = hashlib.md5()
        self._time = time_obj or time.time()
        self._request = None
        details = []
        for url in image_info['urls']:
            try:
                LOG.info("Attempting to download image from {}".format(url))
                self._request = self._download_file(image_info, url)
            except errors.ImageDownloadError as e:
                failtime = time.time() - self._time
                log_msg = ('URL: {}; time: {} '
                           'seconds. Error: {}').format(
                    url, failtime, e.details)
                LOG.warning('Image download failed. %s', log_msg)
                details += log_msg
                continue
            else:
                break
        else:
            details = '/n'.join(details)
            msg = ('Image download failed for all URLs with following errors: '
                   '{}'.format(details))
            raise errors.ImageDownloadError(image_info['id'], msg)

    def _download_file(self, image_info, url):
        """Opens a download stream for the given URL.

        :param image_info: Image information dictionary.
        :param url: The URL string to request the image from.

        :raises: ImageDownloadError if the download stream was not started
                 properly.
        """
        no_proxy = image_info.get('no_proxy')
        if no_proxy:
            os.environ['no_proxy'] = no_proxy
        proxies = image_info.get('proxies', {})
        verify, cert = utils.get_ssl_client_options(CONF)
        resp = requests.get(url, stream=True, proxies=proxies,
                            verify=verify, cert=cert)
        if resp.status_code != 200:
            msg = ('Received status code {} from {}, expected 200. Response '
                   'body: {}').format(resp.status_code, url, resp.text)
            raise errors.ImageDownloadError(image_info['id'], msg)
        return resp

    def __iter__(self):
        """Downloads and returns the next chunk of the image.

        :returns: A chunk of the image. Size of chunk is IMAGE_CHUNK_SIZE
                  which is a constant in this module.
        """
        for chunk in self._request.iter_content(IMAGE_CHUNK_SIZE):
            self._md5checksum.update(chunk)
            yield chunk

    def md5sum(self):
        """Computes and returns the md5 checksum of the downloaded image.

        Note that md5sum will not return the true checksum of the image until
        the download has been fully completed through this object's
        iterator inferface.

        :returns: The md5 checksum of the image as a string in hexadecimal.
        """
        return self._md5checksum.hexdigest()


def _verify_image(image_info, image_location, checksum):
    """Verifies the checksum of the local images matches expectations.

    If this function does not raise ImageChecksumError then it is very likely
    that the local copy of the image was transmitted and stored correctly.

    :param image_info: Image information dictionary.
    :param image_location: The location of the local image.
    :param checksum: The computed checksum of the local image.
    :raises: ImageChecksumError if the checksum of the local image does not
             match the checksum as reported by glance in image_info.
    """
    LOG.debug('Verifying image at {} against MD5 checksum '
              '{}'.format(image_location, checksum))
    if checksum != image_info['checksum']:
        LOG.error(errors.ImageChecksumError.details_str.format(
            image_location, image_info['id'],
            image_info['checksum'], checksum))
        raise errors.ImageChecksumError(image_location, image_info['id'],
                                        image_info['checksum'], checksum)


def _download_image(image_info):
    """Downloads the specified image to the local file system.

    :param image_info: Image information dictionary.
    :raises: ImageDownloadError if the image download fails for any reason.
    :raises: ImageChecksumError if the downloaded image's checksum does not
             match the one reported in image_info.
    """
    starttime = time.time()
    image_location = _image_location(image_info)
    image_download = ImageDownload(image_info, time_obj=starttime)

    with open(image_location, 'wb') as f:
        try:
            for chunk in image_download:
                f.write(chunk)
        except Exception as e:
            msg = 'Unable to write image to {}. Error: {}'.format(
                image_location, str(e))
            raise errors.ImageDownloadError(image_info['id'], msg)

    totaltime = time.time() - starttime
    LOG.info("Image downloaded from {} in {} seconds".format(image_location,
                                                             totaltime))
    _verify_image(image_info, image_location, image_download.md5sum())


def _validate_image_info(ext, image_info=None, **kwargs):
    """Validates the image_info dictionary has all required information.

    :param ext: Object 'self'. Unused by this function directly, but left for
                compatibility with async_command validation.
    :param image_info: Image information dictionary.
    :param kwargs: Additional keyword arguments. Unused, but here for
                   compatibility with async_command validation.
    :raises: InvalidCommandParamsError if the data contained in image_info
             does not match type and key:value pair requirements and
             expectations.
    """
    image_info = image_info or {}

    for field in ['id', 'urls', 'checksum']:
        if field not in image_info:
            msg = 'Image is missing \'{}\' field.'.format(field)
            raise errors.InvalidCommandParamsError(msg)

    if type(image_info['urls']) != list or not image_info['urls']:
        raise errors.InvalidCommandParamsError(
            'Image \'urls\' must be a list with at least one element.')

    if (not isinstance(image_info['checksum'], six.string_types)
            or not image_info['checksum']):
        raise errors.InvalidCommandParamsError(
            'Image \'checksum\' must be a non-empty string.')


class StandbyExtension(base.BaseAgentExtension):
    """Extension which adds stand-by related functionality to agent."""
    def __init__(self, agent=None):
        """Constructs an instance of StandbyExtension.

        :param agent: An optional IronicPythonAgent object. Defaults to None.
        """
        super(StandbyExtension, self).__init__(agent=agent)

        self.cached_image_id = None
        self.partition_uuids = None

    def _cache_and_write_image(self, image_info, device):
        """Cache an image and write it to a local device.

        :param image_info: Image information dictionary.
        :param device: The disk name, as a string, on which to store the
                       image.  Example: '/dev/sda'

        :raises: ImageDownloadError if the image download fails for any reason.
        :raises: ImageChecksumError if the downloaded image's checksum does not
                  match the one reported in image_info.
        :raises: ImageWriteError if writing the image fails.
        """
        _download_image(image_info)
        self.partition_uuids = _write_image(image_info, device)
        self.cached_image_id = image_info['id']

    def _stream_raw_image_onto_device(self, image_info, device):
        """Streams raw image data to specified local device.

        :param image_info: Image information dictionary.
        :param device: The disk name, as a string, on which to store the
                       image.  Example: '/dev/sda'

        :raises: ImageDownloadError if the image download encounters an error.
        :raises: ImageChecksumError if the checksum of the local image does not
             match the checksum as reported by glance in image_info.
        """
        starttime = time.time()
        image_download = ImageDownload(image_info, time_obj=starttime)

        with open(device, 'wb+') as f:
            try:
                for chunk in image_download:
                    f.write(chunk)
            except Exception as e:
                msg = 'Unable to write image to device {}. Error: {}'.format(
                      device, str(e))
                raise errors.ImageDownloadError(image_info['id'], msg)

        totaltime = time.time() - starttime
        LOG.info("Image streamed onto device {} in {} "
                 "seconds".format(device, totaltime))
        # Verify if the checksum of the streamed image is correct
        _verify_image(image_info, device, image_download.md5sum())

    @base.async_command('cache_image', _validate_image_info)
    def cache_image(self, image_info=None, force=False):
        """Asynchronously caches specified image to the local OS device.

        :param image_info: Image information dictionary.
        :param force: Optional. If True forces cache_image to download and
                      cache image, even if the same image already exists on
                      the local OS install device. Defaults to False.

        :raises: ImageDownloadError if the image download fails for any reason.
        :raises: ImageChecksumError if the downloaded image's checksum does not
                  match the one reported in image_info.
        :raises: ImageWriteError if writing the image fails.
        """
        LOG.debug('Caching image %s', image_info['id'])
        device = hardware.dispatch_to_managers('get_os_install_device')

        msg = 'image ({}) already present on device {} '

        if self.cached_image_id != image_info['id'] or force:
            LOG.debug('Already had %s cached, overwriting',
                      self.cached_image_id)
            self._cache_and_write_image(image_info, device)
            msg = 'image ({}) cached to device {} '

        result_msg = _message_format(msg, image_info, device,
                                     self.partition_uuids)

        LOG.info(result_msg)
        return result_msg

    @base.async_command('prepare_image', _validate_image_info)
    def prepare_image(self,
                      image_info=None,
                      configdrive=None):
        """Asynchronously prepares specified image on local OS install device.

        In this case, 'prepare' means make local machine completely ready to
        reboot to the image specified by image_info.

        Downloads and writes an image to disk if necessary. Also writes a
        configdrive to disk if the configdrive parameter is specified.

        :param image_info: Image information dictionary.
        :param configdrive: A string containing the location of the config
                            drive as a URL OR the contents (as gzip/base64)
                            of the configdrive. Optional, defaults to None.

        :raises: ImageDownloadError if the image download encounters an error.
        :raises: ImageChecksumError if the checksum of the local image does not
             match the checksum as reported by glance in image_info.
        :raises: ImageWriteError if writing the image fails.
        :raises: InstanceDeployFailure if failed to create config drive.
             large to store on the given device.
        """
        LOG.debug('Preparing image %s', image_info['id'])
        device = hardware.dispatch_to_managers('get_os_install_device')

        disk_format = image_info.get('disk_format')
        stream_raw_images = image_info.get('stream_raw_images', False)
        # don't write image again if already cached
        if self.cached_image_id != image_info['id']:
            if self.cached_image_id is not None:
                LOG.debug('Already had %s cached, overwriting',
                          self.cached_image_id)

            if (stream_raw_images and disk_format == 'raw' and
                image_info.get('image_type') != 'partition'):
                self._stream_raw_image_onto_device(image_info, device)
            else:
                self._cache_and_write_image(image_info, device)

        # the configdrive creation is taken care by ironic-lib's
        # work_on_disk().
        if image_info.get('image_type') != 'partition':
            if configdrive is not None:
                # Will use dummy value of 'local' for 'node_uuid',
                # if it is not available. This is to handle scenario
                # wherein new IPA is being used with older version
                # of Ironic that did not pass 'node_uuid' in 'image_info'
                node_uuid = image_info.get('node_uuid', 'local')
                disk_utils.create_config_drive_partition(node_uuid,
                                                         device,
                                                         configdrive)
        msg = 'image ({}) written to device {} '
        result_msg = _message_format(msg, image_info, device,
                                     self.partition_uuids)
        LOG.info(result_msg)
        return result_msg

    def _run_shutdown_command(self, command):
        """Run the shutdown or reboot command

        :param command: A string having the command to be run.
        :raises: InvalidCommandParamsError if the passed command is not
            equal to poweroff or reboot.
        :raises: SystemRebootError if the command errors out with an
            unsuccessful exit code.
        """
        if command not in ('reboot', 'poweroff'):
            msg = (('Expected the command "poweroff" or "reboot" '
                    'but received "%s".') % command)
            raise errors.InvalidCommandParamsError(msg)
        try:
            self.sync()
        except errors.CommandExecutionError as e:
            LOG.warning('Failed to sync file system buffers: % s', e)
        try:
            _, stderr = utils.execute(command, use_standard_locale=True,
                                      check_exit_code=[0])
            if 'ignoring request.' in stderr:
                LOG.debug('%s command failed with error %s, '
                          'falling back to sysrq-trigger.', command, stderr)
                if command == 'poweroff':
                    utils.execute("echo o > /proc/sysrq-trigger", shell=True)
                elif command == 'reboot':
                    utils.execute("echo b > /proc/sysrq-trigger", shell=True)
        except processutils.ProcessExecutionError as e:
            raise errors.SystemRebootError(e.exit_code, e.stdout, e.stderr)

    @base.async_command('run_image')
    def run_image(self):
        """Runs image on agent's system via reboot."""
        LOG.info('Rebooting system')
        self._run_shutdown_command('reboot')

    @base.async_command('power_off')
    def power_off(self):
        """Powers off the agent's system."""
        LOG.info('Powering off system')
        self._run_shutdown_command('poweroff')

    @base.sync_command('sync')
    def sync(self):
        """Flush file system buffers forcing changed blocks to disk.

        :raises: CommandExecutionError if flushing file system buffers fails.
        """
        LOG.debug('Flushing file system buffers')
        try:
            utils.execute('sync')
        except processutils.ProcessExecutionError as e:
            error_msg = 'Flushing file system buffers failed. Error: %s' % e
            LOG.error(error_msg)
            raise errors.CommandExecutionError(error_msg)

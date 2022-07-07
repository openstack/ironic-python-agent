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
import tempfile
import time
from urllib import parse as urlparse

from ironic_lib import disk_utils
from ironic_lib import exception
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
import requests

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import partition_utils
from ironic_python_agent import utils

CONF = cfg.CONF
LOG = log.getLogger(__name__)

IMAGE_CHUNK_SIZE = 1024 * 1024  # 1MB


def _image_location(image_info):
    """Get the location of the image in the local file system.

    :param image_info: Image information dictionary.
    :returns: The full, absolute path to the image as a string.
    """
    return os.path.join(tempfile.gettempdir(), image_info['id'])


def _download_with_proxy(image_info, url, image_id):
    """Opens a download stream for the given URL.

    :param image_info: Image information dictionary.
    :param url: The URL string to request the image from.
    :param image_id: Image ID or URL for logging.

    :raises: ImageDownloadError if the download stream was not started
             properly.
    """
    no_proxy = image_info.get('no_proxy')
    if no_proxy:
        os.environ['no_proxy'] = no_proxy
    proxies = image_info.get('proxies', {})
    verify, cert = utils.get_ssl_client_options(CONF)
    resp = None
    for attempt in range(CONF.image_download_connection_retries + 1):
        try:
            # NOTE(TheJulia) The get request below does the following:
            # * Performs dns lookups, if necessary
            # * Opens the TCP socket to the remote host
            # * Negotiates TLS, if applicable
            # * Checks cert validity, if necessary, which may be
            #   more tcp socket connections.
            # * Issues the get request and then returns back to the caller the
            #   handler which is used to stream the data into the agent.
            # While this all may be at risk of transitory interrupts, most of
            # these socket will have timeouts applied to them, although not
            # exactly just as the timeout value exists. The risk in transitory
            # failure is more so once we've started the download and we are
            # processing the incoming data.
            resp = requests.get(url, stream=True, proxies=proxies,
                                verify=verify, cert=cert,
                                timeout=CONF.image_download_connection_timeout)
            if resp.status_code != 200:
                msg = ('Received status code {} from {}, expected 200. '
                       'Response body: {}').format(resp.status_code, url,
                                                   resp.text)
                raise errors.ImageDownloadError(image_id, msg)
        except (errors.ImageDownloadError, requests.RequestException) as e:
            if (attempt == CONF.image_download_connection_retries
                    # NOTE(dtantsur): do not retry 4xx status codes
                    or (resp and resp.status_code < 500)):
                raise
            else:
                LOG.warning('Unable to connect to %s, retrying. Error: %s',
                            url, e)
                time.sleep(CONF.image_download_connection_retry_interval)
        else:
            break
    return resp


def _fetch_checksum(checksum, image_info):
    """Fetch checksum from remote location, if needed."""
    if not (checksum.startswith('http://') or checksum.startswith('https://')):
        # Not a remote checksum, return as it is.
        return checksum

    LOG.debug('Downloading checksums file from %s', checksum)
    resp = _download_with_proxy(image_info, checksum, checksum).text
    lines = [line.strip() for line in resp.split('\n') if line.strip()]
    if not lines:
        raise errors.ImageDownloadError(checksum, "Empty checksum file")
    elif len(lines) == 1:
        # Special case - checksums file with only the checksum itself
        if ' ' not in lines[0]:
            return lines[0]

    # FIXME(dtantsur): can we assume the same name for all images?
    expected_fname = os.path.basename(urlparse.urlparse(
        image_info['urls'][0]).path)
    for line in lines:
        checksum, fname = line.strip().split(None, 1)
        # The star symbol designates binary mode, which is the same as text
        # mode on GNU systems.
        if fname.strip().lstrip('*') == expected_fname:
            return checksum.strip()

    raise errors.ImageDownloadError(
        checksum, "Checksum file does not contain name %s" % expected_fname)


def _write_partition_image(image, image_info, device, configdrive=None):
    """Call disk_util to create partition and write the partition image.

    :param image: Local path to image file to be written to the partition.
        If ``None``, the image is not populated.
    :param image_info: Image information dictionary.
    :param device: The device name, as a string, on which to store the image.
                   Example: '/dev/sda'
    :param configdrive: A string containing the location of the config
                        drive as a URL OR the contents (as gzip/base64)
                        of the configdrive. Optional, defaults to None.

    :raises: InvalidCommandParamsError if the partition is too small for the
             provided image.
    :raises: ImageWriteError if writing the image to disk encounters any error.
    """
    # Retrieve the cached node as it has the latest information
    # and allows us to also sanity check the deployment so we don't end
    # up writing MBR when we're in UEFI mode.
    cached_node = hardware.get_cached_node()

    node_uuid = image_info.get('node_uuid')
    preserve_ep = image_info['preserve_ephemeral']
    boot_mode = utils.get_node_boot_mode(cached_node)
    disk_label = utils.get_partition_table_type_from_specs(cached_node)
    root_mb = image_info['root_mb']

    cpu_arch = hardware.dispatch_to_managers('get_cpus').architecture

    if image is not None:
        image_mb = disk_utils.get_image_mb(image)
        if image_mb > int(root_mb):
            msg = ('Root partition is too small for requested image. Image '
                   'virtual size: {} MB, Root size: {} MB').format(image_mb,
                                                                   root_mb)
            raise errors.InvalidCommandParamsError(msg)

    try:
        return partition_utils.work_on_disk(device, root_mb,
                                            image_info['swap_mb'],
                                            image_info['ephemeral_mb'],
                                            image_info['ephemeral_format'],
                                            image, node_uuid,
                                            preserve_ephemeral=preserve_ep,
                                            configdrive=configdrive,
                                            boot_mode=boot_mode,
                                            disk_label=disk_label,
                                            cpu_arch=cpu_arch)
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
    # FIXME(dtantsur): pass the real node UUID for logging
    disk_utils.destroy_disk_metadata(device, '')
    disk_utils.udev_settle()

    command = ['qemu-img', 'convert',
               '-t', 'directsync', '-S', '0', '-O', 'host_device', '-W',
               image, device]
    LOG.info('Writing image with command: %s', ' '.join(command))
    try:
        disk_utils.convert_image(image, device, out_format='host_device',
                                 cache='directsync', out_of_order=True,
                                 sparse_size='0')
    except processutils.ProcessExecutionError as e:
        raise errors.ImageWriteError(device, e.exit_code, e.stdout, e.stderr)

    disk_utils.trigger_device_rescan(device)


def _write_image(image_info, device, configdrive=None):
    """Writes an image to the specified device.

    :param image_info: Image information dictionary.
    :param device: The disk name, as a string, on which to store the image.
                   Example: '/dev/sda'
    :param configdrive: A string containing the location of the config
                        drive as a URL OR the contents (as gzip/base64)
                        of the configdrive. Optional, defaults to None.
    :raises: ImageWriteError if the command to write the image encounters an
             error.
    """
    starttime = time.time()
    image = _image_location(image_info)
    uuids = {}
    if image_info.get('image_type') == 'partition':
        uuids = _write_partition_image(image, image_info, device, configdrive)
    else:
        _write_whole_disk_image(image, image_info, device)
    totaltime = time.time() - starttime
    LOG.info('Image %(image)s written to device %(device)s in %(totaltime)s '
             'seconds', {'image': image, 'device': device,
                         'totaltime': totaltime})
    try:
        disk_utils.fix_gpt_partition(device, node_uuid=None)
    except exception.InstanceDeployFailure:
        # Note: the catch internal to the helper method logs any errors.
        pass
    return uuids


def _message_format(msg, image_info, device, partition_uuids):
    """Helper method to get and populate different messages."""
    message = None
    result_msg = msg

    root_uuid = partition_uuids.get('root uuid')
    efi_system_partition_uuid = (
        partition_uuids.get('efi system partition uuid'))
    if (image_info.get('deploy_boot_mode') == 'uefi'
            and efi_system_partition_uuid):
        result_msg = msg + 'root_uuid={} efi_system_partition_uuid={}'
        message = result_msg.format(image_info['id'], device,
                                    root_uuid,
                                    efi_system_partition_uuid)
    else:
        result_msg = msg + 'root_uuid={}'
        message = result_msg.format(image_info['id'], device, root_uuid)

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
        self._time = time_obj or time.time()
        self._image_info = image_info
        self._request = None

        # Determine the hash algorithm and value will be used for calculation
        # and verification, fallback to md5 if algorithm is not set or not
        # supported.
        algo = image_info.get('os_hash_algo')
        if algo and algo in hashlib.algorithms_available:
            self._hash_algo = hashlib.new(algo)
            self._expected_hash_value = image_info.get('os_hash_value')
        elif image_info.get('checksum'):
            try:
                self._hash_algo = hashlib.md5()
            except ValueError as e:
                message = ('Unable to proceed with image {} as the legacy '
                           'checksum indicator has been used, which makes use '
                           'the MD5 algorithm. This algorithm failed to load '
                           'due to the underlying operating system. Error: '
                           '{}').format(image_info['id'], str(e))
                LOG.error(message)
                raise errors.RESTError(details=message)
            self._expected_hash_value = image_info['checksum']
        else:
            message = ('Unable to verify image {} with available checksums. '
                       'Please make sure the specified \'os_hash_algo\' '
                       '(currently {}) is supported by this ramdisk, or '
                       'provide a md5 checksum via the \'checksum\' '
                       'field'.format(image_info['id'],
                                      image_info.get('os_hash_algo')))
            LOG.error(message)
            raise errors.RESTError(details=message)

        self._expected_hash_value = _fetch_checksum(self._expected_hash_value,
                                                    image_info)

        details = []
        for url in image_info['urls']:
            try:
                LOG.info("Attempting to download image from %s", url)
                self._request = _download_with_proxy(image_info, url,
                                                     image_info['id'])
            except errors.ImageDownloadError as e:
                failtime = time.time() - self._time
                log_msg = ('URL: {}; time: {} '
                           'seconds. Error: {}').format(
                    url, failtime, e.secondary_message)
                LOG.warning(log_msg)
                details.append(log_msg)
                continue
            else:
                break
        else:
            details = '\n '.join(details)
            raise errors.ImageDownloadError(image_info['id'], details)

    def __iter__(self):
        """Downloads and returns the next chunk of the image.

        :returns: A chunk of the image. Size of chunk is IMAGE_CHUNK_SIZE
                  which is a constant in this module.
        """
        self._last_chunk_time = None
        for chunk in self._request.iter_content(IMAGE_CHUNK_SIZE):
            # Per requests forum posts/discussions, iter_content should
            # periodically yield to the caller for the client to do things
            # like stopwatch and potentially interrupt the download.
            # While this seems weird and doesn't exactly seem to match the
            # patterns in requests and urllib3, it does appear to be the
            # case. Field testing in environments where TCP sockets were
            # discovered in a read hanged state were navigated with
            # this code.
            if chunk:
                self._last_chunk_time = time.time()
                self._hash_algo.update(chunk)
                yield chunk
            elif (time.time() - self._last_chunk_time
                  > CONF.image_download_connection_timeout):
                LOG.error('Timeout reached waiting for a chunk of data from '
                          'a remote server.')
                raise errors.ImageDownloadError(
                    self._image_info['id'],
                    'Timed out reading next chunk from webserver')

    def verify_image(self, image_location):
        """Verifies the checksum of the local images matches expectations.

        If this function does not raise ImageChecksumError then it is very
        likely that the local copy of the image was transmitted and stored
        correctly.

        :param image_location: The location of the local image.
        :raises: ImageChecksumError if the checksum of the local image does
                 not match the checksum as reported by glance in image_info.
        """
        checksum = self._hash_algo.hexdigest()
        LOG.debug('Verifying image at %(image_location)s against '
                  '%(algo_name)s checksum %(checksum)s',
                  {'image_location': image_location,
                   'algo_name': self._hash_algo.name,
                   'checksum': checksum})
        if checksum != self._expected_hash_value:
            error_msg = errors.ImageChecksumError.details_str.format(
                image_location, self._image_info['id'],
                self._expected_hash_value, checksum)
            LOG.error(error_msg)
            raise errors.ImageChecksumError(image_location,
                                            self._image_info['id'],
                                            self._expected_hash_value,
                                            checksum)


def _download_image(image_info):
    """Downloads the specified image to the local file system.

    :param image_info: Image information dictionary.
    :raises: ImageDownloadError if the image download fails for any reason.
    :raises: ImageChecksumError if the downloaded image's checksum does not
             match the one reported in image_info.
    """
    starttime = time.time()
    image_location = _image_location(image_info)
    for attempt in range(CONF.image_download_connection_retries + 1):
        try:
            image_download = ImageDownload(image_info, time_obj=starttime)

            with open(image_location, 'wb') as f:
                try:
                    for chunk in image_download:
                        f.write(chunk)
                except Exception as e:
                    msg = 'Unable to write image to {}. Error: {}'.format(
                        image_location, str(e))
                    raise errors.ImageDownloadError(image_info['id'], msg)
        except errors.ImageDownloadError as e:
            if attempt == CONF.image_download_connection_retries:
                raise
            else:
                LOG.warning('Image download failed, %(attempt)s of %(total)s: '
                            '%(error)s',
                            {'attempt': attempt,
                             'total': CONF.image_download_connection_retries,
                             'error': e})
                time.sleep(CONF.image_download_connection_retry_interval)
        else:
            break

    totaltime = time.time() - starttime
    LOG.info("Image downloaded from %(image_location)s "
             "in %(totaltime)s seconds",
             {'image_location': image_location,
              'totaltime': totaltime})
    image_download.verify_image(image_location)


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

    md5sum_avail = False
    os_hash_checksum_avail = False

    for field in ['id', 'urls']:
        if field not in image_info:
            msg = 'Image is missing \'{}\' field.'.format(field)
            raise errors.InvalidCommandParamsError(msg)

    if type(image_info['urls']) != list or not image_info['urls']:
        raise errors.InvalidCommandParamsError(
            'Image \'urls\' must be a list with at least one element.')

    checksum = image_info.get('checksum')
    if checksum is not None:
        if (not isinstance(image_info['checksum'], str)
                or not image_info['checksum']):
            raise errors.InvalidCommandParamsError(
                'Image \'checksum\' must be a non-empty string.')
        md5sum_avail = True

    os_hash_algo = image_info.get('os_hash_algo')
    os_hash_value = image_info.get('os_hash_value')
    if os_hash_algo or os_hash_value:
        if (not isinstance(os_hash_algo, str)
                or not os_hash_algo):
            raise errors.InvalidCommandParamsError(
                'Image \'os_hash_algo\' must be a non-empty string.')
        if (not isinstance(os_hash_value, str)
                or not os_hash_value):
            raise errors.InvalidCommandParamsError(
                'Image \'os_hash_value\' must be a non-empty string.')
        os_hash_checksum_avail = True

    if not (md5sum_avail or os_hash_checksum_avail):
        raise errors.InvalidCommandParamsError(
            'Image checksum is not available, either the \'checksum\' field '
            'or the \'os_hash_algo\' and \'os_hash_value\' fields pair must '
            'be set for image verification.')


def _validate_partitioning(device):
    """Validate the final partition table.

    Check if after writing the image to disk we have a valid partition
    table by trying to read it. This will fail if the disk is junk.
    """
    try:
        # Ensure we re-read the partition table before we try to list
        # partitions
        utils.execute('partprobe', device, run_as_root=True,
                      attempts=CONF.disk_utils.partprobe_attempts)
    except (processutils.UnknownArgumentError,
            processutils.ProcessExecutionError, OSError) as e:
        LOG.warning("Unable to probe for partitions on device %(device)s "
                    "after writing the image, the partitioning table may "
                    "be broken. Error: %(error)s",
                    {'device': device, 'error': e})

    try:
        nparts = len(disk_utils.list_partitions(device))
    except (processutils.UnknownArgumentError,
            processutils.ProcessExecutionError, OSError) as e:
        msg = ("Unable to find a valid partition table on the disk after "
               f"writing the image. The image may be corrupted. Error: {e}")
        raise exception.InstanceDeployFailure(msg)

    # Check if there is at least one partition in the partition table after
    # deploy
    if not nparts:
        msg = ("No partitions found on the device {} after writing "
               "the image.".format(device))
        raise exception.InstanceDeployFailure(msg)


class StandbyExtension(base.BaseAgentExtension):
    """Extension which adds stand-by related functionality to agent."""
    def __init__(self, agent=None):
        """Constructs an instance of StandbyExtension.

        :param agent: An optional IronicPythonAgent object. Defaults to None.
        """
        super(StandbyExtension, self).__init__(agent=agent)

        self.cached_image_id = None
        self.partition_uuids = None

    def _cache_and_write_image(self, image_info, device, configdrive=None):
        """Cache an image and write it to a local device.

        :param image_info: Image information dictionary.
        :param device: The disk name, as a string, on which to store the
                       image.  Example: '/dev/sda'
        :param configdrive: A string containing the location of the config
                            drive as a URL OR the contents (as gzip/base64)
                            of the configdrive. Optional, defaults to None.

        :raises: ImageDownloadError if the image download fails for any reason.
        :raises: ImageChecksumError if the downloaded image's checksum does not
                  match the one reported in image_info.
        :raises: ImageWriteError if writing the image fails.
        """
        _download_image(image_info)
        self.partition_uuids = _write_image(image_info, device, configdrive)
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
        total_retries = CONF.image_download_connection_retries
        for attempt in range(total_retries + 1):
            try:
                image_download = ImageDownload(image_info, time_obj=starttime)

                with open(device, 'wb+') as f:
                    try:
                        for chunk in image_download:
                            f.write(chunk)
                    except Exception as e:
                        msg = ('Unable to write image to device {}. '
                               'Error: {}').format(device, str(e))
                        raise errors.ImageDownloadError(image_info['id'], msg)
            except errors.ImageDownloadError as e:
                if attempt == CONF.image_download_connection_retries:
                    raise
                else:
                    LOG.warning('Image download failed, %(attempt)s of '
                                '%(total)s: %(error)s',
                                {'attempt': attempt,
                                 'total': total_retries,
                                 'error': e})
                    time.sleep(CONF.image_download_connection_retry_interval)
            else:
                break

        totaltime = time.time() - starttime
        LOG.info("Image streamed onto device %(device)s in %(totaltime)s "
                 "seconds", {'device': device, 'totaltime': totaltime})
        # Verify if the checksum of the streamed image is correct
        image_download.verify_image(device)
        # Fix any gpt partition
        try:
            disk_utils.fix_gpt_partition(device, node_uuid=None)
        except exception.InstanceDeployFailure:
            # Note: the catch internal to the helper method logs any errors.
            pass
        # Fix the root partition UUID
        root_uuid = disk_utils.block_uuid(device)
        LOG.info("%(device)s UUID is now %(root_uuid)s",
                 {'device': device, 'root_uuid': root_uuid})
        self.partition_uuids['root uuid'] = root_uuid

    def _fix_up_partition_uuids(self, image_info, device):
        if self.partition_uuids is None:
            self.partition_uuids = {}

        if image_info.get('image_type') == 'partition':
            return

        try:
            root_uuid = disk_utils.get_disk_identifier(device)
        except OSError as e:
            LOG.warning('Failed to call get_disk_identifier: '
                        'Unable to obtain the root_uuid parameter: '
                        'The hexdump tool may be missing in IPA: %s', e)
        else:
            self.partition_uuids['root uuid'] = root_uuid

    @base.async_command('cache_image', _validate_image_info)
    def cache_image(self, image_info, force=False, configdrive=None):
        """Asynchronously caches specified image to the local OS device.

        :param image_info: Image information dictionary.
        :param force: Optional. If True forces cache_image to download and
                      cache image, even if the same image already exists on
                      the local OS install device. Defaults to False.
        :param configdrive: A string containing the location of the config
                            drive as a URL OR the contents (as gzip/base64)
                            of the configdrive. Optional, defaults to None.

        :raises: ImageDownloadError if the image download fails for any reason.
        :raises: ImageChecksumError if the downloaded image's checksum does not
                  match the one reported in image_info.
        :raises: ImageWriteError if writing the image fails.
        """
        LOG.debug('Caching image %s', image_info['id'])
        device = hardware.dispatch_to_managers('get_os_install_device',
                                               permit_refresh=True)

        msg = 'image ({}) already present on device {} '

        if self.cached_image_id != image_info['id'] or force:
            LOG.debug('Already had %s cached, overwriting',
                      self.cached_image_id)
            # NOTE(dtantsur): backward compatibility
            if configdrive is None:
                configdrive = image_info.pop('configdrive', None)
            self._cache_and_write_image(image_info, device, configdrive)
            msg = 'image ({}) cached to device {} '

        self._fix_up_partition_uuids(image_info, device)
        result_msg = _message_format(msg, image_info, device,
                                     self.partition_uuids)

        LOG.info(result_msg)
        return result_msg

    @base.async_command('prepare_image', _validate_image_info)
    def prepare_image(self, image_info, configdrive=None):
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
        # NOTE(dtantsur): backward compatibility
        if configdrive is None:
            configdrive = image_info.pop('configdrive', None)
        device = hardware.dispatch_to_managers('get_os_install_device',
                                               permit_refresh=True)

        disk_format = image_info.get('disk_format')
        stream_raw_images = image_info.get('stream_raw_images', False)
        # don't write image again if already cached
        if self.cached_image_id != image_info['id']:
            if self.cached_image_id is not None:
                LOG.debug('Already had %s cached, overwriting',
                          self.cached_image_id)

            if stream_raw_images and disk_format == 'raw':
                if image_info.get('image_type') == 'partition':
                    self.partition_uuids = _write_partition_image(None,
                                                                  image_info,
                                                                  device,
                                                                  configdrive)
                    stream_to = self.partition_uuids['partitions']['root']
                else:
                    self.partition_uuids = {}
                    stream_to = device

                self._stream_raw_image_onto_device(image_info, stream_to)
            else:
                self._cache_and_write_image(image_info, device, configdrive)

        _validate_partitioning(device)

        # For partition images the configdrive creation is taken care by
        # partition_utils.work_on_disk(), invoked from either
        # _write_partition_image or _cache_and_write_image above.
        # Handle whole disk images explicitly now.
        if image_info.get('image_type') != 'partition':
            if configdrive is not None:
                # Will use dummy value of 'local' for 'node_uuid',
                # if it is not available. This is to handle scenario
                # wherein new IPA is being used with older version
                # of Ironic that did not pass 'node_uuid' in 'image_info'
                node_uuid = image_info.get('node_uuid', 'local')
                partition_utils.create_config_drive_partition(node_uuid,
                                                              device,
                                                              configdrive)

        self._fix_up_partition_uuids(image_info, device)
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
        # TODO(TheJulia): When we have deploy/clean steps, we should remove
        # this upon shutdown. The clock sync deploy step can run before
        # completing other operations.
        self._sync_clock(ignore_errors=True)

        if command not in ('reboot', 'poweroff'):
            msg = (('Expected the command "poweroff" or "reboot" '
                    'but received "%s".') % command)
            raise errors.InvalidCommandParamsError(msg)
        try:
            self.sync()
        except errors.CommandExecutionError as e:
            LOG.warning('Failed to sync file system buffers: % s', e)

        try:
            _, stderr = utils.execute(command, use_standard_locale=True)
        except processutils.ProcessExecutionError as e:
            LOG.warning('%s command failed with error %s, '
                        'falling back to sysrq-trigger', command, e)
        else:
            if 'ignoring request' in stderr:
                LOG.warning('%s command has been ignored, '
                            'falling back to sysrq-trigger', command)
            else:
                return

        try:
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

    @base.sync_command('get_partition_uuids')
    def get_partition_uuids(self):
        """Return partition UUIDs."""
        # NOTE(dtantsur): None means prepare_image hasn't been called (an empty
        # dict is used for whole disk images).
        if self.partition_uuids is None:
            LOG.warning('No partition UUIDs recorded yet, prepare_image '
                        'has to be called before get_partition_uuids')
        return self.partition_uuids or {}

    # TODO(TheJulia): Once we have deploy/clean steps, this should
    # become a step, which we ideally have enabled by default.
    def _sync_clock(self, ignore_errors=False):
        """Sync the clock to a configured NTP server.

        :param ignore_errors: Boolean option to indicate if the
                              errors should be fatal. This option
                              does not override the fail_if_clock_not_set
                              configuration option.
        :raises: ClockSyncError if a failure is encountered and
                 errors are not ignored.
        """
        try:
            utils.sync_clock(ignore_errors=ignore_errors)
            # Sync the system hardware clock from the software clock,
            # as they are independent and the HW clock can still drift
            # with long running ramdisks.
            utils.execute('hwclock', '-v', '--systohc')
        except (processutils.ProcessExecutionError,
                errors.CommandExecutionError) as e:
            msg = 'Failed to sync hardware clock: %s' % e
            LOG.error(msg)
            if CONF.fail_if_clock_not_set or not ignore_errors:
                raise errors.ClockSyncError(msg)

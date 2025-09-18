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

import base64
import errno
import hashlib
import json
import os
import re
import tempfile
import time
from urllib import parse as urlparse

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
from oslo_utils import units
import requests

from ironic_python_agent import disk_utils
from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import partition_utils
from ironic_python_agent import utils

CONF = cfg.CONF
LOG = log.getLogger(__name__)

IMAGE_CHUNK_SIZE = 1024 * 1024  # 1MB


def _execute_configdrive_hook(configdrive, device, image_info, stage):
    """Execute configdrive deployment hook.

    :param configdrive: Configdrive data
    :param device: Target device path
    :param image_info: Image information dictionary
    :param stage: Deployment stage ('pre' or 'post')
    :raises: DeploymentError if hook execution fails
    """
    if not configdrive:
        return

    confdrive_file = None
    try:
        node_uuid = image_info.get('node_uuid', 'local')
        _, confdrive_file = partition_utils.get_configdrive(
            configdrive, node_uuid)
        partition_utils.execute_configdrive_deploy_hook(
            confdrive_file, device, stage)
    except errors.DeploymentError:
        raise
    except processutils.ProcessExecutionError as e:
        LOG.error('%s-deployment hook execution failed: %s',
                  stage.capitalize(), e)
        raise errors.DeploymentError(
            f'{stage.capitalize()}-deployment hook execution failed') from e
    except Exception as e:
        LOG.error('Failed to process configdrive for %s-deployment '
                  'hook execution: %s', stage, e)
        raise errors.DeploymentError(
            f'Failed to process configdrive for {stage}-deployment hook') from e
    finally:
        if confdrive_file:
            utils.unlink_without_raise(confdrive_file)


def _image_location(image_info):
    """Get the location of the image in the local file system.

    :param image_info: Image information dictionary.
    :returns: The full, absolute path to the image as a string.
    """
    return os.path.join(tempfile.gettempdir(), image_info['id'])


def _verify_basic_auth_creds(user, password, image_id):
    """Verify the basic auth credentials used for image download are present.

    :param user: Basic auth username
    :param password: Basic auth password
    :param image_id: id of the image that is being acted upon

    :raises ImageDownloadError if the credentials are not present
    """
    expected_creds = {'user': user, 'password': password}
    missing_creds = []
    for key, value in expected_creds.items():
        if not value:
            missing_creds.append(key)
    if missing_creds:
        raise errors.ImageDownloadError(
            image_id,
            "Missing {} fields from HTTP(S) "
            "basic auth config".format(missing_creds)
        )


class SuppliedAuth(requests.auth.HTTPBasicAuth):

    def __init__(self, authorization):
        self.authorization = authorization

    def __call__(self, r):
        r.headers["Authorization"] = self.authorization
        return r

    def __eq__(self, other):
        return all(
            [
                self.authorization == getattr(other, "authorization", None)
            ]
        )

    def __ne__(self, other):
        return not self == other


def _load_supplied_authorization(image_info):

    req_auth = image_info.get('image_request_authorization')
    if req_auth:
        req_auth = base64.standard_b64decode(req_auth).decode()
        return SuppliedAuth(req_auth)
    else:
        return None


def _gen_auth_from_image_info_user_pass(image_info, image_id):
    """This function is used to pass the credentials to the chosen

       credential verifier and in case the verification is successful
       generate the compatible authentication object that will be used
       with the request(s). This function handles the authentication object
       generation for authentication strategies that are username+password
       based. Credentials are collected via image_info.

    :param image_info: Image information dictionary.
    :param image_id: id of the image that is being acted upon

    :return: Authentication object used directly by the request library
    :rtype: requests.auth.HTTPBasicAuth
    """
    image_server_user = None
    image_server_password = None

    if image_info.get('image_server_auth_strategy') == 'http_basic':
        image_server_user = image_info.get('image_server_user')
        image_server_password = image_info.get('image_server_password')
        _verify_basic_auth_creds(
            image_server_user,
            image_server_password,
            image_id
        )
    else:
        return None

    return requests.auth.HTTPBasicAuth(image_server_user,
                                       image_server_password)


def _gen_auth_from_oslo_conf_user_pass(image_id):
    """This function is used to pass the credentials to the chosen

       credential verifier and in case the verification is successful
       generate the compatible authentication object that will be used
       with the request(s). This function handles the authentication object
       generation for authentication strategies that are username+password
       based. Credentials are collected from the oslo.config framework.

    :param image_id: id of the image that is being acted upon

    :return: Authentication object used directly by the request library
    :rtype: requests.auth.HTTPBasicAuth
    """

    image_server_user = None
    image_server_password = None

    if CONF.image_server_auth_strategy == 'http_basic':
        _verify_basic_auth_creds(
            CONF.image_server_user,
            CONF.image_server_password,
            image_id)
        image_server_user = CONF.image_server_user
        image_server_password = CONF.image_server_password
    else:
        return None

    return requests.auth.HTTPBasicAuth(image_server_user,
                                       image_server_password)


def _download_with_proxy(image_info, url, image_id):
    """Opens a download stream for the given URL.

    :param image_info: Image information dictionary.
    :param url: The URL string to request the image from.
    :param image_id: Image ID or URL for logging.

    :raises: ImageDownloadError if the download stream was not started
             properly.

    :return: HTTP(s) server response for the image/hash download request
    :rtype: requests.Response
    """

    no_proxy = image_info.get('no_proxy')
    if no_proxy:
        os.environ['no_proxy'] = no_proxy
    proxies = image_info.get('proxies', {})
    verify, cert = utils.get_ssl_client_options(CONF)
    resp = None
    image_download_attributes = {
        "stream": True,
        "proxies": proxies,
        "verify": verify,
        "cert": cert,
        "timeout": CONF.image_download_connection_timeout
    }
    # NOTE(Adam) `image_info` is prioritized over `oslo.conf` for credential
    # collection and auth strategy selection
    auth_object = _load_supplied_authorization(image_info)
    if auth_object is None:
        auth_object = _gen_auth_from_image_info_user_pass(image_info, image_id)
    if auth_object is None:
        auth_object = _gen_auth_from_oslo_conf_user_pass(image_id)
    if auth_object is not None:
        image_download_attributes['auth'] = auth_object
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
            # B113 issue is covered is the image_download_attributs list
            resp = requests.get(url, **image_download_attributes)  # nosec
            if resp.status_code != 200:
                msg = ('Received status code {} from {}, expected 200. '
                       'Response body: {} Response headers: {}').format(
                    resp.status_code, url, resp.text, resp.headers)
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


def _is_checksum_url(checksum):
    """Identify if checksum is not a url"""
    if (checksum.startswith('http://') or checksum.startswith('https://')):
        return True
    else:
        return False


MD5_MATCH = r"^([a-fA-F\d]{32})\s"  # MD5 at beginning of line
MD5_MATCH_END = r"\s([a-fA-F\d]{32})$"  # MD5 at end of line
MD5_MATCH_ONLY = r"^([a-fA-F\d]{32})$"  # MD5 only
SHA256_MATCH = r"^([a-fA-F\d]{64})\s"  # SHA256 at beginning of line
SHA256_MATCH_END = r"\s([a-fA-F\d]{64})$"  # SHA256 at end of line
SHA256_MATCH_ONLY = r"^([a-fA-F\d]{64})$"  # SHA256 only
SHA512_MATCH = r"^([a-fA-F\d]{128})\s"  # SHA512 at beginning of line
SHA512_MATCH_END = r"\s([a-fA-F\d]{128})$"  # SHA512 at end of line
SHA512_MATCH_ONLY = r"^([a-fA-F\d]{128})$"  # SHA512 only
FILENAME_MATCH_END = r"\s[*]?{filename}$"  # Filename binary/text end of line
FILENAME_MATCH_PARENTHESES = r"\s\({filename}\)\s"  # CentOS images

CHECKSUM_MATCHERS = (MD5_MATCH, MD5_MATCH_END, SHA256_MATCH, SHA256_MATCH_END,
                     SHA512_MATCH, SHA512_MATCH_END)
CHECKSUM_ONLY_MATCHERS = (MD5_MATCH_ONLY, SHA256_MATCH_ONLY, SHA512_MATCH_ONLY)
FILENAME_MATCHERS = (FILENAME_MATCH_END, FILENAME_MATCH_PARENTHESES)


def _fetch_checksum(checksum, image_info):
    """Fetch checksum from remote location, if needed."""
    if not _is_checksum_url(checksum):
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
            for matcher in CHECKSUM_ONLY_MATCHERS:
                checksum = re.findall(matcher, lines[0])
                if checksum:
                    return checksum[0]
            raise errors.ImageDownloadError(
                checksum, ("Invalid checksum file (No valid checksum found) %s"
                           % lines))

    # FIXME(dtantsur): can we assume the same name for all images?
    expected_fname = os.path.basename(urlparse.urlparse(
        image_info['urls'][0]).path)
    for line in lines:
        # Ignore comment lines
        if line.startswith("#"):
            continue

        # Ignore checksums for other files
        for matcher in FILENAME_MATCHERS:
            if re.findall(matcher.format(filename=expected_fname), line):
                break
        else:
            continue

        for matcher in CHECKSUM_MATCHERS:
            checksum = re.findall(matcher, line)
            if checksum:
                return checksum[0]

    raise errors.ImageDownloadError(
        checksum, "Checksum file does not contain name %s" % expected_fname)


def _write_partition_image(image, image_info, device, configdrive=None,
                           source_format=None, is_raw=False, size=0):
    """Call disk_util to create partition and write the partition image.

    :param image: Local path to image file to be written to the partition.
        If ``None``, the image is not populated.
    :param image_info: Image information dictionary.
    :param device: The device name, as a string, on which to store the image.
                   Example: '/dev/sda'
    :param configdrive: A string containing the location of the config
                        drive as a URL OR the contents (as gzip/base64)
                        of the configdrive. Optional, defaults to None.
    :param source_format: The actual format of the partition image.
                         Must be provided if deep image inspection is enabled.
    :param is_raw: Ironic indicates the image is raw; do not convert it
    :param size: Virtual size, in MB, of provided image.

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
        if size > int(root_mb):
            msg = ('Root partition is too small for requested image. Image '
                   'virtual size: {} MB, Root size: {} MB').format(size,
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
                                            cpu_arch=cpu_arch,
                                            source_format=source_format,
                                            is_raw=is_raw)
    except processutils.ProcessExecutionError as e:
        raise errors.ImageWriteError(device, e.exit_code, e.stdout, e.stderr)


def _write_whole_disk_image(image, image_info, device, source_format=None,
                            is_raw=False):
    """Writes a whole disk image to the specified device.

    :param image: Local path to image file to be written to the disk.
    :param image_info: Image information dictionary.
                       This parameter is currently unused by the function.
    :param device: The device name, as a string, on which to store the image.
                   Example: '/dev/sda'
    :param source_format: The format of the whole disk image to be written.
    :param is_raw: Ironic indicates the image is raw; do not convert it
    :raises: ImageWriteError if the command to write the image encounters an
             error.
    :raises: InvalidImage if asked to write an image without a format when
                          not permitted
    """
    # FIXME(dtantsur): pass the real node UUID for logging
    disk_utils.destroy_disk_metadata(device, '')
    disk_utils.udev_settle()
    disk_utils.populate_image(image, device,
                              is_raw=is_raw,
                              source_format=source_format,
                              out_format='host_device',
                              cache='directsync',
                              out_of_order=True)
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
    :raises: InvalidImage if the image does not pass security inspection
    """
    starttime = time.time()
    image = _image_location(image_info)
    ironic_disk_format = image_info.get('disk_format')
    is_raw = ironic_disk_format == 'raw'
    # NOTE(JayF): The below method call performs a required security check
    #             and must remain in place. See bug #2071740
    source_format, size = disk_utils.get_and_validate_image_format(
        image, ironic_disk_format)
    size_mb = int((size + units.Mi - 1) / units.Mi)

    uuids = {}
    if image_info.get('image_type') == 'partition':
        uuids = _write_partition_image(image, image_info, device,
                                       configdrive,
                                       source_format=source_format,
                                       is_raw=is_raw, size=size_mb)
    else:
        _write_whole_disk_image(image, image_info, device,
                                source_format=source_format,
                                is_raw=is_raw)
    totaltime = time.time() - starttime
    LOG.info('Image %(image)s written to device %(device)s in %(totaltime)s '
             'seconds', {'image': image, 'device': device,
                         'totaltime': totaltime})
    try:
        disk_utils.fix_gpt_partition(device, node_uuid=None)
    except errors.DeploymentError:
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


def _get_algorithm_by_length(checksum):
    """Determine the SHA-2 algorithm by checksum length.

    :param checksum: The requested checksum.
    :returns: A hashlib object based upon the checksum
              or ValueError if the algorithm could not be
              identified.
    """
    # NOTE(TheJulia): This is all based on SHA-2 lengths.
    # SHA-3 would require a hint, thus ValueError because
    # it may not be a fixed length. That said, SHA-2 is not
    # as of this not being added, being withdrawn standards wise.
    checksum_len = len(checksum)
    if checksum_len == 128:
        # Sha512 is 512 bits, or 128 characters
        return hashlib.new('sha512')
    elif checksum_len == 64:
        # SHA256 is 256 bits, or 64 characters
        return hashlib.new('sha256')
    elif checksum_len == 32:
        check_md5_enabled()
        # This is not super great, but opt-in only.
        return hashlib.new('md5')  # nosec
    else:
        # Previously, we would have just assumed the value was
        # md5 by default. This way we are a little smarter and
        # gracefully handle things better when md5 is explicitly
        # disabled.
        raise ValueError('Unable to identify checksum algorithm '
                         'used, and a value is not specified in '
                         'the os_hash_algo setting.')


def check_md5_enabled():
    """Checks if md5 is permitted, otherwise raises ValueError."""
    if not CONF.md5_enabled:
        raise ValueError('MD5 support is disabled, and support '
                         'will be removed in a 2024 version of '
                         'Ironic.')


class ImageDownload(object):
    """Helper class that opens a HTTP connection to download an image.

    This class opens a HTTP connection to download an image from a URL
    and create an iterator so the image can be downloaded in chunks. The
    MD5 hash of the image being downloaded is calculated on-the-fly.
    """

    def __init__(self, image_info, time_obj=None):
        """Initialize an instance of the ImageDownload class.

        Tries each URL in image_info successively until a URL returns a
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
        self._bytes_transferred = 0
        self._expected_size = None
        checksum = image_info.get('checksum')
        retrieved_checksum = False

        # Determine the hash algorithm and value will be used for calculation
        # and verification, fallback to md5 if algorithm is not set or not
        # supported.
        algo = image_info.get('os_hash_algo')
        if algo and algo in hashlib.algorithms_available:
            self._hash_algo = hashlib.new(algo)
            self._expected_hash_value = image_info.get('os_hash_value')
        elif checksum and _is_checksum_url(checksum):
            # Treat checksum urls as first class request citizens, else
            # fallback to legacy handling.
            self._expected_hash_value = _fetch_checksum(
                checksum,
                image_info)
            retrieved_checksum = True
            if not algo:
                # Override algorithm not supplied as os_hash_algo
                self._hash_algo = _get_algorithm_by_length(
                    self._expected_hash_value)
        elif checksum:
            # Fallback to md5 path.
            try:
                new_algo = _get_algorithm_by_length(checksum)

                if not new_algo:
                    # Realistically, this should never happen, but for
                    # compatibility...
                    # TODO(TheJulia): Remove for a 2024 release.
                    self._hash_algo = hashlib.new('md5')  # nosec
                else:
                    self._hash_algo = new_algo
            except ValueError as e:
                message = ('Unable to proceed with image {} as the '
                           'checksum indicator has been used but the '
                           'algorithm could not be identified. Error: '
                           '{}').format(image_info['id'], str(e))
                LOG.error(message)
                raise errors.RESTError(details=message)
            self._expected_hash_value = checksum
        else:
            message = ('Unable to verify image {} with available checksums. '
                       'Please make sure the specified \'os_hash_algo\' '
                       '(currently {}) is supported by this ramdisk, or '
                       'provide a md5 checksum via the \'checksum\' '
                       'field'.format(image_info['id'],
                                      image_info.get('os_hash_algo')))
            LOG.error(message)
            raise errors.RESTError(details=message)

        if not retrieved_checksum:
            # Fallback to retrieve the checksum if we didn't retrieve it
            # earlier on.
            self._expected_hash_value = _fetch_checksum(
                self._expected_hash_value,
                image_info)

        # NOTE(dtantsur): verify that the user's input does not obviously
        # contradict the actual value. It is especially easy to make such
        # a mistake when providing a checksum URL.
        if algo:
            try:
                detected_algo = _get_algorithm_by_length(
                    self._expected_hash_value)
            except ValueError:
                pass  # an exotic algorithm?
            else:
                if detected_algo.name != algo:
                    LOG.warning("Provided checksum algorithm %(provided)s "
                                "does not match the detected algorithm "
                                "%(detected)s. It may be a sign of a user "
                                "error when providing the algorithm or the "
                                "checksum URL.",
                                {'provided': algo,
                                 'detected': detected_algo.name})

        details = []
        for url in image_info['urls']:
            try:
                LOG.info("Attempting to download image from %s", url)
                self._request = _download_with_proxy(image_info, url,
                                                     image_info['id'])
                self._expected_size = self._request.headers.get(
                    'Content-Length')
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
        start_time = self._time

        for chunk in self._request.iter_content(IMAGE_CHUNK_SIZE):

            max_download_duration = CONF.image_download_max_duration
            if max_download_duration:
                elapsed = time.time() - start_time
                if elapsed > max_download_duration:
                    LOG.error('Total download timeout (%s seconds) exceeded',
                              max_download_duration)
                    raise errors.ImageDownloadTimeoutError(
                        self._image_info['id'],
                        'Download exceeded max allowed time (%s seconds)' %
                        max_download_duration)

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
                if isinstance(chunk, str):
                    encoded_data = chunk.encode()
                    self._hash_algo.update(encoded_data)
                    self._bytes_transferred += len(encoded_data)
                else:
                    self._hash_algo.update(chunk)
                    self._bytes_transferred += len(chunk)
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

    @property
    def bytes_transferred(self):
        """Property value to return the number of bytes transferred."""
        return self._bytes_transferred

    @property
    def content_length(self):
        """Property value to return the server indicated length."""
        # If none, there is nothing we can do, the server didn't have
        # a response.
        return self._expected_size


def _download_image(image_info):
    """Downloads the specified image to the local file system.

    :param image_info: Image information dictionary.
    :raises: ImageDownloadError if the image download fails for any reason.
    :raises: ImageDownloadOutofSpaceError if the image download fails
             due to insufficient storage space.
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
                        try:
                            f.write(chunk)
                        except OSError as e:
                            if e.errno == errno.ENOSPC:
                                msg = ('Unable to write image to {}. Error: {}'
                                       ).format(image_location, e)
                                raise errors.ImageDownloadOutofSpaceError(
                                    image_info['id'], msg)
                            raise
                except errors.ImageDownloadOutofSpaceError:
                    raise
                except Exception as e:
                    msg = 'Unable to write image to {}. Error: {}'.format(
                        image_location, str(e))
                    raise errors.ImageDownloadError(image_info['id'], msg)
            image_download.verify_image(image_location)
        except errors.ImageDownloadOutofSpaceError:
            raise
        except (errors.ImageDownloadError,
                errors.ImageChecksumError) as e:
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
             "in %(totaltime)s seconds. Transferred %(size)s bytes. "
             "Server originally reported: %(reported)s.",
             {'image_location': image_location,
              'totaltime': totaltime,
              'size': image_download.bytes_transferred,
              'reported': image_download.content_length})


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

    checksum_avail = False
    md5sum_avail = False
    os_hash_checksum_avail = False

    for field in ['id', 'urls']:
        if field not in image_info:
            msg = 'Image is missing \'{}\' field.'.format(field)
            raise errors.InvalidCommandParamsError(msg)

    if not isinstance(image_info['urls'], list) or not image_info['urls']:
        raise errors.InvalidCommandParamsError(
            'Image \'urls\' must be a list with at least one element.')

    checksum = image_info.get('checksum')
    if checksum is not None:
        if (not isinstance(image_info['checksum'], str)
                or not image_info['checksum']):
            raise errors.InvalidCommandParamsError(
                'Image \'checksum\' must be a non-empty string.')
        if _is_checksum_url(checksum) or len(checksum) > 32:
            # Checksum is a URL *or* a greater than 32 characters,
            # putting it into the realm of sha256 or sha512 and not
            # the MD5 algorithm.
            checksum_avail = True
        elif CONF.md5_enabled:
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

    if not (checksum_avail or md5sum_avail or os_hash_checksum_avail):
        raise errors.InvalidCommandParamsError(
            'Image checksum is not available, either the \'checksum\' field '
            'or the \'os_hash_algo\' and \'os_hash_value\' fields pair must '
            'be set for image verification.')


def _validate_partitioning(device):
    """Validate the final partition table.

    Check if after writing the image to disk we have a valid partition
    table by trying to read it. This will fail if the disk is junk.
    """
    disk_utils.partprobe(device)

    try:
        nparts = len(disk_utils.list_partitions(device))
    except (processutils.UnknownArgumentError,
            processutils.ProcessExecutionError, OSError) as e:
        msg = ("Unable to find a valid partition table on the disk after "
               "writing the image. The image may be corrupted or it uses a "
               f"different sector size than the device. Error: {e}")
        raise errors.DeploymentError(msg)

    # Check if there is at least one partition in the partition table after
    # deploy
    if not nparts:
        msg = ("No partitions found on the device {} after writing "
               "the image.".format(device))
        raise errors.DeploymentError(msg)


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
                # Verify the checksum of the streamed image is correct while
                # still in the retry loop, so we can retry should a checksum
                # failure be detected.
                image_download.verify_image(device)
            except (errors.ImageDownloadError,
                    errors.ImageChecksumError) as e:
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
                 "seconds for %(size)s bytes. Server originally reported "
                 "%(reported)s.",
                 {'device': device, 'totaltime': totaltime,
                  'size': image_download.bytes_transferred,
                  'reported': image_download.content_length})
        # Fix any gpt partition
        try:
            disk_utils.fix_gpt_partition(device, node_uuid=None)
        except errors.DeploymentError:
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

        # Execute pre-deployment hook before any disk operations
        _execute_configdrive_hook(configdrive, device, image_info, 'pre')

        requested_disk_format = image_info.get('disk_format')

        stream_raw_images = image_info.get('stream_raw_images', False)

        # don't write image again if already cached
        if self.cached_image_id != image_info['id']:
            if self.cached_image_id is not None:
                LOG.debug('Already had %s cached, overwriting',
                          self.cached_image_id)

            if stream_raw_images and requested_disk_format == 'raw':
                if image_info.get('image_type') == 'partition':
                    # NOTE(JayF): This only creates partitions due to image
                    #             being None
                    self.partition_uuids = _write_partition_image(None,
                                                                  image_info,
                                                                  device,
                                                                  configdrive)
                    stream_to = self.partition_uuids['partitions']['root']
                else:
                    self.partition_uuids = {}
                    stream_to = device

                # NOTE(JayF): Images that claim to be raw are not inspected at
                #             all, as they never interact with qemu-img and are
                #             streamed directly to disk unmodified.
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

        # Execute post-deployment hook after all disk operations
        _execute_configdrive_hook(configdrive, device, image_info, 'post')

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
            hardware.dispatch_to_all_managers('full_sync')
        except Exception as e:
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
        hardware.dispatch_to_all_managers('full_sync')

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

    @base.async_command('execute_bootc_install')
    def execute_bootc_install(self, image_source, instance_info={},
                              pull_secret=None, configdrive=None):
        """Asynchronously prepares specified image on local OS install device.

        Identifies target disk device to deploy onto, and extracts necessary
        configuration data to trigger podman, triggers podman, verifies
        partitioning changes were made, and finally executes configuration
        drive write-out.

        :param image_source: The OCI Container registry URL supplied by Ironic.
        :param instance_info: An Ironic Node's instance_info filed for user
            requested specific configuration details be extracted.
        :param pull_secret: The user requested or system required pull secret
            to authenticate to remote container image registries.
        :param configdrive: The user requested configuration drive content
            supplied by Ironic's step execution command.

        :raises: ImageDownloadError if the image download encounters an error.
        :raises: ImageChecksumError if the checksum of the local image does not
             match the checksum as reported by glance in image_info.
        :raises: ImageWriteError if writing the image fails.
        :raises: InstanceDeployFailure if failed to create config drive.
             large to store on the given device.
        """
        LOG.debug('Preparing container %s for bootc.', image_source)
        if CONF.disable_bootc_deploy:
            LOG.error('A bootc based deployment was requested for %s, '
                      'however bootc based deployment is disabled.',
                      image_source)
            raise errors.CommandExecutionError(
                details=("The bootc deploy interface is administratively "
                         "disable. Deployment cannot proceed."))
        device = hardware.dispatch_to_managers('get_os_install_device',
                                               permit_refresh=True)
        authorized_keys = instance_info.get('bootc_authorized_keys', None)
        tpm2_luks = instance_info.get('bootc_tpm2_luks', False)
        self._download_container_and_bootc_install(image_source, device,
                                                   pull_secret, tpm2_luks,
                                                   authorized_keys)

        _validate_partitioning(device)

        # For partition images the configdrive creation is taken care by
        # partition_utils.work_on_disk(), invoked from either
        # _write_partition_image or _cache_and_write_image above.
        # Handle whole disk images explicitly now.
        if configdrive:
            partition_utils.create_config_drive_partition('local',
                                                          device,
                                                          configdrive)

        msg = f'Container image ({image_source}) written to device {device}'
        LOG.info(msg)
        return msg

    def _download_container_and_bootc_install(self, image_source,
                                              device, pull_secret,
                                              tpm2_luks, authorized_keys):
        """Downloads container and triggers bootc install.

        :param image_source: The user requested image_source to
            deploy to the hard disk.
        :param device: The device to deploy to.
        :param pull_secret: A pull secret to interact with a remote
            container image registry.
        :param tpm2_luks: Boolean value if LUKS should be requested.
        :param authorized_keys: The authorized keys string data
            to supply to podman, if applicable.
        :raises: ImageDownloadError If the downloaded container
                 lacks the ``bootc`` command.
        :raises: ImageWriteError If the execution of podman fails.
        """
        # First, disable pivot_root in podman because it cannot be
        # performed on top of a ramdisk filesystem.
        self._write_no_pivot_root()

        # Identify the URL, specifically so we drop
        url = urlparse.urlparse(image_source)

        # This works because the path is maintained.
        container_url = url.netloc + url.path

        if pull_secret:
            self._write_container_auth(pull_secret, url.netloc)

        # Get the disk size, and convert it to megabtyes.
        disk_size = disk_utils.get_dev_byte_size(device) // 1024 // 1024

        # Ensure we leave enough space for a configuration drive,
        # and ESP partition.
        # NOTE(TheJulia): bootc leans towards a 512 MB EFI partition.
        disk_size = disk_size - 768
        # Convert from a float to string.
        disk_size = str(disk_size)

        # Determine the status of selinux.
        selinux = False
        try:
            stdout, _ = utils.execute("getenforce", use_standard_locale=True)
            if stdout.startswith('Enforcing'):
                selinux = True
        except (processutils.ProcessExecutionError,
                errors.CommandExecutionError,
                OSError):
            pass

        # Execute Podman to run bootc from the container.
        #
        # This has to run as a privileged operation, mapping the container
        # assets from the runtime to inside of the container environment,
        # and pass the device through.
        #
        # As for bootc itself...
        # --skip-fetch-check disables an internal check to bootc to make sure
        # it can retrieve updates from the remote registry, which is fine if
        # credentials are already in the container or we embed the credentials,
        # but that is not the best idea.
        # --disable-selinux is alternatively needed if selinux is *not*
        # enabled on the host.
        command = [
            'podman',
            '--log-level=debug',
            'run', '--rm', '--privileged', '--pid=host',
            '-v', '/var/lib/containers:/var/lib/containers',
            '-v', '/dev:/dev',
            # By default, podman's retry starts at 3s and extends
            # expentionally, which can lead to podman appearing
            # to hang when downloading. This pins it so it just
            # retires in relatively short order.
            '--retry-delay=5s',
        ]
        if pull_secret:
            command.append('--authfile=/root/.config/containers/auth.json')
        if authorized_keys:
            # NOTE(TheJulia): Bandit flags on this, but we need a folder which
            # should exist in the container *and* locally to the ramdisk.
            # As such, flagging with nosec.
            command.extend(['-v', '/tmp:/tmp'])  # nosec B108
        if selinux:
            command.extend([
                '--security-opt', 'label=type:unconfined_t'
            ])
        command.extend([
            container_url,
            'bootc', 'install', 'to-disk',
            '--wipe', '--skip-fetch-check',
            '--root-size=' + disk_size + 'M'
        ])
        if tpm2_luks:
            command.append('--block-setup=tpm2-luks')
        if authorized_keys:
            key_file = self._write_authorized_keys(authorized_keys)
            command.append(f'--root-ssh-authorized-keys={key_file}')

        if not selinux:
            # For SELinux to be applied, per the bootc docs, you must have
            # SELinux enabled on the host system.
            command.append('--disable-selinux')

        command.append(device)

        try:
            stdout, stderr = utils.execute(*command, use_standard_locale=True)
        except processutils.ProcessExecutionError as e:
            LOG.debug('Failed to execute podman: %s', e)
            raise errors.ImageWriteError(device, e.exit_code, e.stdout,
                                         e.stderr)
        for output in [stdout, stderr]:
            if 'executable file `bootc` not found' in output:
                # This is the case where the container doesn't actually
                # support bootc, because it lacks the bootc tool.
                # This should be stderr, but appears in stdout. Check both
                # just on the safe side.
                raise errors.ImageDownloadError(
                    image_source,
                    "Container does not contain the required bootc binary "
                    "and thus cannot be deployed."
                )

    def _write_no_pivot_root(self):
        """Writes a podman no-pivot configuration."""
        # This method writes a configuration to tell podman
        # to *don't* attempt to pivot_root on the ramdisk, because
        # it won't work. In essence, just setting the environment,
        # to actually execute a container.
        path = '/etc/containers/containers.conf.d'
        os.makedirs(path, exist_ok=True)
        file_path = os.path.join(path, '01-ipa.conf')
        file_content = '[engine]\nno_pivot_root = true\n'
        with open(file_path, 'w') as file:
            file.write(file_content)

    def _write_container_auth(self, pull_secret, netloc):
        """Write authentication configuration for container registry auth.

        :param pull_secret: The authorization pull secret string for
                            interacting with a remote container registry.
        :param netloc: The FQDN, or network location portion of the URL
                       used to access the container registry.
        """
        # extract secret
        decoded_pull_secret = base64.standard_b64decode(
            pull_secret
        ).decode()

        # Generate a dict which will emulate our container auth
        # configuration.
        auth_dict = {
            "auths": {netloc: {"auth": decoded_pull_secret}}}

        # Make the folders to $HOME/.config/containers/auth.json
        # which would normally be generated by podman login, but
        # we don't need to actually do that as we have a secret.
        # Default to root, as we don't launch IPA with a HOME
        # folder in most cases.
        home = '/root'
        folder = os.path.join(home, '.config/containers')
        os.makedirs(folder, mode=0o700, exist_ok=True)
        auth_path = os.path.join(folder, 'auth.json')

        # Save the pull secret
        with open(auth_path, 'w') as file:
            json.dump(auth_dict, file)

    def _write_authorized_keys(self, authorized_keys):
        """Write a temporary authorized keys file for bootc use."""
        # Write authorized_keys content to a temporary file
        # on the temporary folder path structure which can be
        # accessed by podman. On linux in our ramdisks, this
        # should always be /tmp. We then return the absolute
        # file path for podman to leverage.
        fd, file_path = tempfile.mkstemp(text=True)
        os.write(fd, authorized_keys.encode())
        os.close(fd)
        return file_path

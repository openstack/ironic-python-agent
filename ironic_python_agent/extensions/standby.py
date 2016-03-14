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
import gzip
import hashlib
import os
import requests
import six
import time

from oslo_concurrency import processutils
from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import utils

LOG = log.getLogger(__name__)

IMAGE_CHUNK_SIZE = 1024 * 1024  # 1MB


def _configdrive_location():
    return '/tmp/configdrive'


def _image_location(image_info):
    return '/tmp/{0}'.format(image_info['id'])


def _path_to_script(script):
    cwd = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(cwd, '..', script)


def _write_image(image_info, device):
    starttime = time.time()
    image = _image_location(image_info)

    script = _path_to_script('shell/write_image.sh')
    command = ['/bin/bash', script, image, device]
    LOG.info('Writing image with command: {0}'.format(' '.join(command)))
    try:
        stdout, stderr = utils.execute(*command, check_exit_code=[0])
    except processutils.ProcessExecutionError as e:
        raise errors.ImageWriteError(device, e.exit_code, e.stdout, e.stderr)
    totaltime = time.time() - starttime
    LOG.info('Image {0} written to device {1} in {2} seconds'.format(
             image, device, totaltime))


def _configdrive_is_url(configdrive):
    return (configdrive.startswith('http://')
            or configdrive.startswith('https://'))


def _download_configdrive_to_file(configdrive, filename):
    content = requests.get(configdrive).content
    _write_configdrive_to_file(content, filename)


def _write_configdrive_to_file(configdrive, filename):
    LOG.debug('Writing configdrive to {0}'.format(filename))
    # configdrive data is base64'd, decode it first
    data = six.StringIO(base64.b64decode(configdrive))
    gunzipped = gzip.GzipFile('configdrive', 'rb', 9, data)
    with open(filename, 'wb') as f:
        f.write(gunzipped.read())
    gunzipped.close()


def _write_configdrive_to_partition(configdrive, device):
    filename = _configdrive_location()
    if _configdrive_is_url(configdrive):
        _download_configdrive_to_file(configdrive, filename)
    else:
        _write_configdrive_to_file(configdrive, filename)

    # check configdrive size before writing it
    filesize = os.stat(filename).st_size
    if filesize > (64 * 1024 * 1024):
        raise errors.ConfigDriveTooLargeError(filename, filesize)

    starttime = time.time()
    script = _path_to_script('shell/copy_configdrive_to_disk.sh')
    command = ['/bin/bash', script, filename, device]
    LOG.info('copying configdrive to disk with command {0}'.format(
             ' '.join(command)))

    try:
        stdout, stderr = utils.execute(*command, check_exit_code=[0])
    except processutils.ProcessExecutionError as e:
        raise errors.ConfigDriveWriteError(device,
                                           e.exit_code,
                                           e.stdout,
                                           e.stderr)

    totaltime = time.time() - starttime
    LOG.info('configdrive copied from {0} to {1} in {2} seconds'.format(
             filename,
             device,
             totaltime))


class ImageDownload(object):
    """Helper class that opens a HTTP connection to download an image.

    This class opens a HTTP connection to download an image from a URL
    and create an iterator so the image can be downloaded in chunks. The
    MD5 hash of the image being downloaded is calculated on-the-fly.
    """

    def __init__(self, image_info, time_obj=None):
        self._md5checksum = hashlib.md5()
        self._time = time_obj or time.time()
        self._request = None

        for url in image_info['urls']:
            try:
                LOG.info("Attempting to download image from {0}".format(url))
                self._request = self._download_file(image_info, url)
            except errors.ImageDownloadError as e:
                failtime = time.time() - self._time
                log_msg = ('Image download failed. URL: {0}; time: {1} '
                           'seconds. Error: {2}')
                LOG.warning(log_msg.format(url, failtime, e.details))
                continue
            else:
                break
        else:
            msg = 'Image download failed for all URLs.'
            raise errors.ImageDownloadError(image_info['id'], msg)

    def _download_file(self, image_info, url):
        no_proxy = image_info.get('no_proxy')
        if no_proxy:
            os.environ['no_proxy'] = no_proxy
        proxies = image_info.get('proxies', {})
        resp = requests.get(url, stream=True, proxies=proxies)
        if resp.status_code != 200:
            msg = ('Received status code {0} from {1}, expected 200. Response '
                   'body: {2}').format(resp.status_code, url, resp.text)
            raise errors.ImageDownloadError(image_info['id'], msg)
        return resp

    def __iter__(self):
        for chunk in self._request.iter_content(IMAGE_CHUNK_SIZE):
            self._md5checksum.update(chunk)
            yield chunk

    def md5sum(self):
        return self._md5checksum.hexdigest()


def _verify_image(image_info, image_location, checksum):
    LOG.debug('Verifying image at {0} against MD5 checksum '
              '{1}'.format(image_location, checksum))
    if checksum != image_info['checksum']:
        LOG.error(errors.ImageChecksumError.details_str.format(
            image_location, image_info['id'],
            image_info['checksum'], checksum))
        raise errors.ImageChecksumError(image_location, image_info['id'],
                                        image_info['checksum'], checksum)


def _download_image(image_info):
    starttime = time.time()
    image_location = _image_location(image_info)
    image_download = ImageDownload(image_info, time_obj=starttime)

    with open(image_location, 'wb') as f:
        try:
            for chunk in image_download:
                f.write(chunk)
        except Exception as e:
            msg = 'Unable to write image to {0}. Error: {1}'.format(
                image_location, str(e))
            raise errors.ImageDownloadError(image_info['id'], msg)

    totaltime = time.time() - starttime
    LOG.info("Image downloaded from {0} in {1} seconds".format(image_location,
                                                               totaltime))
    _verify_image(image_info, image_location, image_download.md5sum())


def _validate_image_info(ext, image_info=None, **kwargs):
    image_info = image_info or {}

    for field in ['id', 'urls', 'checksum']:
        if field not in image_info:
            msg = 'Image is missing \'{0}\' field.'.format(field)
            raise errors.InvalidCommandParamsError(msg)

    if type(image_info['urls']) != list or not image_info['urls']:
        raise errors.InvalidCommandParamsError(
            'Image \'urls\' must be a list with at least one element.')

    if (not isinstance(image_info['checksum'], six.string_types)
            or not image_info['checksum']):
        raise errors.InvalidCommandParamsError(
            'Image \'checksum\' must be a non-empty string.')


class StandbyExtension(base.BaseAgentExtension):
    def __init__(self, agent=None):
        super(StandbyExtension, self).__init__(agent=agent)

        self.cached_image_id = None

    def _cache_and_write_image(self, image_info, device):
        _download_image(image_info)
        _write_image(image_info, device)
        self.cached_image_id = image_info['id']

    def _stream_raw_image_onto_device(self, image_info, device):
        starttime = time.time()
        image_download = ImageDownload(image_info, time_obj=starttime)

        with open(device, 'wb+') as f:
            try:
                for chunk in image_download:
                    f.write(chunk)
            except Exception as e:
                msg = 'Unable to write image to device {0}. Error: {1}'.format(
                      device, str(e))
                raise errors.ImageDownloadError(image_info['id'], msg)

        totaltime = time.time() - starttime
        LOG.info("Image streamed onto device {0} in {1} "
                 "seconds".format(device, totaltime))
        # Verify if the checksum of the streamed image is correct
        _verify_image(image_info, device, image_download.md5sum())

    @base.async_command('cache_image', _validate_image_info)
    def cache_image(self, image_info=None, force=False):
        LOG.debug('Caching image %s', image_info['id'])
        device = hardware.dispatch_to_managers('get_os_install_device')

        result_msg = 'image ({0}) already present on device {1}'

        if self.cached_image_id != image_info['id'] or force:
            LOG.debug('Already had %s cached, overwriting',
                      self.cached_image_id)
            self._cache_and_write_image(image_info, device)
            result_msg = 'image ({0}) cached to device {1}'

        msg = result_msg.format(image_info['id'], device)
        LOG.info(msg)
        return msg

    @base.async_command('prepare_image', _validate_image_info)
    def prepare_image(self,
                      image_info=None,
                      configdrive=None):
        LOG.debug('Preparing image %s', image_info['id'])
        device = hardware.dispatch_to_managers('get_os_install_device')

        disk_format = image_info.get('disk_format')
        stream_raw_images = image_info.get('stream_raw_images', False)
        # don't write image again if already cached
        if self.cached_image_id != image_info['id']:

            if self.cached_image_id is not None:
                LOG.debug('Already had %s cached, overwriting',
                          self.cached_image_id)

            if stream_raw_images and disk_format == 'raw':
                self._stream_raw_image_onto_device(image_info, device)
            else:
                self._cache_and_write_image(image_info, device)

        if configdrive is not None:
            _write_configdrive_to_partition(configdrive, device)

        msg = ('image ({0}) written to device {1}'.format(
            image_info['id'], device))
        LOG.info(msg)
        return msg

    def _run_shutdown_script(self, parameter):
        script = _path_to_script('shell/shutdown.sh')
        command = ['/bin/bash', script, parameter]
        # this should never return if successful
        try:
            stdout, stderr = utils.execute(*command, check_exit_code=[0])
        except processutils.ProcessExecutionError as e:
            raise errors.SystemRebootError(e.exit_code, e.stdout, e.stderr)

    @base.async_command('run_image')
    def run_image(self):
        LOG.info('Rebooting system')
        self._run_shutdown_script('-r')

    @base.async_command('power_off')
    def power_off(self):
        LOG.info('Powering off system')
        self._run_shutdown_script('-h')

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

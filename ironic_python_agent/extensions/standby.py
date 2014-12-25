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
import StringIO
import time

from oslo_concurrency import processutils

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent.openstack.common import log
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
    data = StringIO.StringIO(base64.b64decode(configdrive))
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


def _request_url(image_info, url):
    resp = requests.get(url, stream=True)
    if resp.status_code != 200:
        raise errors.ImageDownloadError(image_info['id'])
    return resp


def _download_image(image_info):
    starttime = time.time()
    resp = None
    for url in image_info['urls']:
        try:
            LOG.info("Attempting to download image from {0}".format(url))
            resp = _request_url(image_info, url)
        except errors.ImageDownloadError:
            failtime = time.time() - starttime
            log_msg = "Image download failed. URL: {0}; time: {1} seconds"
            LOG.warning(log_msg.format(url, failtime))
            continue
        else:
            break
    if resp is None:
        raise errors.ImageDownloadError(image_info['id'])

    image_location = _image_location(image_info)
    with open(image_location, 'wb') as f:
        try:
            for chunk in resp.iter_content(IMAGE_CHUNK_SIZE):
                f.write(chunk)
        except Exception:
            raise errors.ImageDownloadError(image_info['id'])

    totaltime = time.time() - starttime
    LOG.info("Image downloaded from {0} in {1} seconds".format(image_location,
                                                               totaltime))

    if not _verify_image(image_info, image_location):
        raise errors.ImageChecksumError(image_info['id'])


def _verify_image(image_info, image_location):
    checksum = image_info['checksum']
    log_msg = 'Verifying image at {0} against MD5 checksum {1}'
    LOG.debug(log_msg.format(image_location, checksum))
    hash_ = hashlib.md5()
    with open(image_location) as image:
        while True:
            data = image.read(IMAGE_CHUNK_SIZE)
            if not data:
                break
            hash_.update(data)
    hash_digest = hash_.hexdigest()
    if hash_digest == checksum:
        return True
    log_msg = ('Image verification failed. Location: {0};'
               'image hash: {1}; verification hash: {2}')
    LOG.warning(log_msg.format(image_location, checksum, hash_digest))
    return False


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

    @base.async_command('cache_image', _validate_image_info)
    def cache_image(self, image_info=None, force=False):
        device = hardware.get_manager().get_os_install_device()

        if self.cached_image_id != image_info['id'] or force:
            _download_image(image_info)
            _write_image(image_info, device)
            self.cached_image_id = image_info['id']

    @base.async_command('prepare_image', _validate_image_info)
    def prepare_image(self,
                      image_info=None,
                      configdrive=None):
        device = hardware.get_manager().get_os_install_device()

        # don't write image again if already cached
        if self.cached_image_id != image_info['id']:
            _download_image(image_info)
            _write_image(image_info, device)
            self.cached_image_id = image_info['id']

        if configdrive is not None:
            _write_configdrive_to_partition(configdrive, device)

    @base.async_command('run_image')
    def run_image(self):
        script = _path_to_script('shell/reboot.sh')
        LOG.info('Rebooting system')
        command = ['/bin/bash', script]
        # this should never return if successful
        try:
            stdout, stderr = utils.execute(*command, check_exit_code=[0])
        except processutils.ProcessExecutionError as e:
            raise errors.SystemRebootError(e.exit_code, e.stdout, e.stderr)

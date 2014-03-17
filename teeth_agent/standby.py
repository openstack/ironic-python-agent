"""
Copyright 2013 Rackspace, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import hashlib
import os
import requests
import subprocess
import time

from teeth_agent import base
from teeth_agent import configdrive
from teeth_agent import decorators
from teeth_agent import errors
from teeth_agent import hardware
from teeth_agent.openstack.common import log

LOG = log.getLogger(__name__)


def _configdrive_location():
    return '/tmp/configdrive'


def _image_location(image_info):
    return '/tmp/{}'.format(image_info['id'])


def _path_to_script(script):
    cwd = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(cwd, script)


def _write_image(image_info, device):
    starttime = time.time()
    image = _image_location(image_info)

    script = _path_to_script('shell/write_image.sh')
    command = ['/bin/bash', script, image, device]
    LOG.info('Writing image with command: {0}'.format(' '.join(command)))
    exit_code = subprocess.call(command)
    if exit_code != 0:
        raise errors.ImageWriteError(exit_code, device)
    totaltime = time.time() - starttime
    LOG.info('Image {0} written to device {1} in {2} seconds'.format(
             image, device, totaltime))


def _copy_configdrive_to_disk(configdrive_dir, device):
    starttime = time.time()
    script = _path_to_script('shell/copy_configdrive_to_disk.sh')
    command = ['/bin/bash', script, configdrive_dir, device]
    LOG.info('copying configdrive to disk with command {0}'.format(
             ' '.join(command)))
    exit_code = subprocess.call(command)

    if exit_code != 0:
        raise errors.ConfigDriveWriteError(exit_code, device)

    totaltime = time.time() - starttime
    LOG.info('configdrive copied from {0} to {1} in {2} seconds'.format(
             configdrive_dir,
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
            for chunk in resp.iter_content(1024 * 1024):
                f.write(chunk)
        except Exception:
            raise errors.ImageDownloadError(image_info['id'])

    totaltime = time.time() - starttime
    LOG.info("Image downloaded from {0} in {1} seconds".format(image_location,
                                                               totaltime))

    if not _verify_image(image_info, image_location):
        raise errors.ImageChecksumError(image_info['id'])


def _verify_image(image_info, image_location):
    hashes = image_info['hashes']
    for k, v in hashes.iteritems():
        algo = getattr(hashlib, k, None)
        if algo is None:
            continue
        log_msg = 'Verifying image at {0} with algorithm {1} against hash {2}'
        LOG.debug(log_msg.format(image_location, k, v))
        hash_ = algo(open(image_location).read()).hexdigest()
        if hash_ == v:
            return True
        else:
            log_msg = ('Image verification failed. Location: {0};'
                       'algorithm: {1}; image hash: {2};'
                       'verification hash: {3}')
            LOG.warning(log_msg.format(image_location, k, hash_, v))
    return False


def _validate_image_info(image_info=None, **kwargs):
    image_info = image_info or {}

    for field in ['id', 'urls', 'hashes']:
        if field not in image_info:
            msg = 'Image is missing \'{}\' field.'.format(field)
            raise errors.InvalidCommandParamsError(msg)

    if type(image_info['urls']) != list or not image_info['urls']:
        raise errors.InvalidCommandParamsError(
            'Image \'urls\' must be a list with at least one element.')

    if type(image_info['hashes']) != dict or not image_info['hashes']:
        raise errors.InvalidCommandParamsError(
            'Image \'hashes\' must be a dictionary with at least one '
            'element.')


class StandbyMode(base.BaseAgentMode):
    def __init__(self):
        super(StandbyMode, self).__init__('STANDBY')
        self.command_map['cache_image'] = self.cache_image
        self.command_map['prepare_image'] = self.prepare_image
        self.command_map['run_image'] = self.run_image

        self.cached_image_id = None

    @decorators.async_command(_validate_image_info)
    def cache_image(self, command_name, image_info=None, force=False):
        device = hardware.get_manager().get_os_install_device()

        if self.cached_image_id != image_info['id'] or force:
            _download_image(image_info)
            _write_image(image_info, device)
            self.cached_image_id = image_info['id']

    @decorators.async_command(_validate_image_info)
    def prepare_image(self,
                      command_name,
                      image_info=None,
                      metadata=None,
                      files=None):
        location = _configdrive_location()
        device = hardware.get_manager().get_os_install_device()

        # don't write image again if already cached
        if self.cached_image_id != image_info['id']:
            _download_image(image_info)
            _write_image(image_info, device)
            self.cached_image_id = image_info['id']

        LOG.debug('Writing configdrive to {0}'.format(location))
        configdrive.write_configdrive(location, metadata, files)
        _copy_configdrive_to_disk(location, device)

    @decorators.async_command()
    def run_image(self, command_name):
        script = _path_to_script('shell/reboot.sh')
        LOG.info('Rebooting system')
        command = ['/bin/bash', script]
        # this should never return if successful
        exit_code = subprocess.call(command)
        if exit_code != 0:
            raise errors.SystemRebootError(exit_code)

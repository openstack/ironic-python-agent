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
import structlog
import subprocess
import time

from teeth_agent import base
from teeth_agent import configdrive
from teeth_agent import decorators
from teeth_agent import errors
from teeth_agent import hardware

log = structlog.get_logger()


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
    log.info('Writing image', command=' '.join(command))
    exit_code = subprocess.call(command)
    if exit_code != 0:
        raise errors.ImageWriteError(exit_code, device)
    totaltime = time.time() - starttime
    log.info('Image written', device=device, seconds=totaltime, image=image)


def _copy_configdrive_to_disk(configdrive_dir, device):
    starttime = time.time()
    script = _path_to_script('shell/copy_configdrive_to_disk.sh')
    command = ['/bin/bash', script, configdrive_dir, device]
    log.info('copying configdrive to disk', command=' '.join(command))
    exit_code = subprocess.call(command)

    if exit_code != 0:
        raise errors.ConfigDriveWriteError(exit_code, device)

    totaltime = time.time() - starttime
    log.info('configdrive copied',
             from_directory=configdrive_dir,
             device=device,
             seconds=totaltime)


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
            log.info("Attempting to download image", url=url)
            resp = _request_url(image_info, url)
        except errors.ImageDownloadError:
            failtime = time.time() - starttime
            log.warning("Image download failed", url=url, seconds=failtime)
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
    log.info("Image downloaded", image=image_location, seconds=totaltime)

    if not _verify_image(image_info, image_location):
        raise errors.ImageChecksumError(image_info['id'])


def _verify_image(image_info, image_location):
    hashes = image_info['hashes']
    for k, v in hashes.iteritems():
        algo = getattr(hashlib, k, None)
        if algo is None:
            continue
        log.debug('Verifying image',
                  image=image_location,
                  algo=k,
                  passed_hash=v)
        hash_ = algo(open(image_location).read()).hexdigest()
        if hash_ == v:
            return True
        else:
            log.warning('Image verification failed',
                        image=image_location,
                        algo=k,
                        imagehash=hash_,
                        passed_hash=v)
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

    @decorators.async_command(_validate_image_info)
    def cache_image(self, command_name, image_info=None):
        device = hardware.get_manager().get_os_install_device()

        _download_image(image_info)
        _write_image(image_info, device)

    @decorators.async_command(_validate_image_info)
    def prepare_image(self,
                      command_name,
                      image_info=None,
                      metadata=None,
                      files=None):
        location = _configdrive_location()
        device = hardware.get_manager().get_os_install_device()

        _download_image(image_info)
        _write_image(image_info, device)

        log.debug('Writing configdrive', location=location)
        configdrive.write_configdrive(location, metadata, files)
        _copy_configdrive_to_disk(location, device)

    @decorators.async_command()
    def run_image(self, command_name):
        script = _path_to_script('shell/reboot.sh')
        log.info('Rebooting system')
        command = ['/bin/bash', script]
        # this should never return if successful
        exit_code = subprocess.call(command)
        if exit_code != 0:
            raise errors.SystemRebootError(exit_code)

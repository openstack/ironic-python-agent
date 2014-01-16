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
import json
import os
import subprocess

import requests

from teeth_agent import base
from teeth_agent import errors


def _image_location(image_info):
    return '/tmp/{}'.format(image_info['id'])


def _write_local_config_drive(location, data):
    """Writes a config_drive directory at `location`."""
    if not os.path.exists(location):
        os.makedirs(location)

    filename = os.path.join(location, 'meta_data.json')
    with open(filename, 'w') as f:
        json_data = json.dumps(data)
        f.write(json_data)


def _write_image(image_info, configdrive_dir, device):
    image = _image_location(image_info)

    cwd = os.path.dirname(os.path.realpath(__file__))
    script = os.path.join(cwd, 'shell/makefs.sh')
    command = ['/bin/bash', script, configdrive_dir, image, device]

    exit_code = subprocess.call(command)
    if exit_code != 0:
        raise errors.ImageWriteError(exit_code, device)


def _request_url(image_info, url):
    resp = requests.get(url, stream=True)
    if resp.status_code != 200:
        raise errors.ImageDownloadError(image_info['id'])
    return resp


def _download_image(image_info):
    resp = None
    for url in image_info['urls']:
        try:
            resp = _request_url(image_info, url)
        except errors.ImageDownloadError:
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

    if not _verify_image(image_info, image_location):
        raise errors.ImageChecksumError(image_info['id'])


def _verify_image(image_info, image_location):
    hashes = image_info['hashes']
    for k, v in hashes.iteritems():
        algo = getattr(hashlib, k, None)
        if algo is None:
            continue
        hash_ = algo(open(image_location).read())
        if hash_ == v:
            return True
    return False


class CacheImagesCommand(base.AsyncCommandResult):
    def execute(self):
        # TODO(russellhaering): Actually cache images
        pass


class PrepareImageCommand(base.AsyncCommandResult):
    """Downloads and writes an image and configdrive to a device."""
    def execute(self):
        image_info = self.command_params['image_info']
        location = self.command_params['configdrive']['location']
        data = self.command_params['configdrive']['data']
        device = self.command_params['device']

        _download_image(image_info)
        _write_local_config_drive(location, data)
        _write_image(image_info, location, device)


class RunImageCommand(base.AsyncCommandResult):
    def execute(self):
        # TODO(jimrollenhagen): Actually run image, reboot/kexec/whatever
        pass


class StandbyAgent(base.BaseTeethAgent):
    def __init__(self,
                 listen_host,
                 listen_port,
                 advertise_host,
                 advertise_port,
                 api_url):
        super(StandbyAgent, self).__init__(listen_host,
                                           listen_port,
                                           advertise_host,
                                           advertise_port,
                                           api_url,
                                           'STANDBY')

        self.command_map = {
            'cache_images': self.cache_images,
            'prepare_image': self.prepare_image,
            'run_image': self.run_image,
        }

    def _validate_image_info(self, image_info):
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

    def cache_images(self, command_name, image_infos):
        if type(image_infos) != list:
            raise errors.InvalidCommandParamsError(
                '\'image_infos\' parameter must be a list.')

        for image_info in image_infos:
            self._validate_image_info(image_info)

        return CacheImagesCommand(command_name, image_infos).start()

    def prepare_image(self, command_name, **command_params):
        self._validate_image_info(command_params['image_info'])

        return PrepareImageCommand(command_name, command_params).start()

    def run_image(self, command_name, image_info):
        self._validate_image_info(image_info)

        return RunImageCommand(command_name, image_info).start()

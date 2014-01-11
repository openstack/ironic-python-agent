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

import json
import subprocess
import uuid

import requests

from teeth_agent import base
from teeth_agent import errors


def _image_location(image_info):
    return '/tmp/{}'.format(image_info['id'])


def _write_image(image_info, configdrive='configdrive', device='/dev/sda'):
    # TODO(jimrollenhagen) don't hardcode these kwargs
    image = _image_location(image_info)
    filename = '{}/meta_data.json'.format(configdrive)
    with open(filename, 'w') as f:
        data = {
            'uuid': str(uuid.uuid4()),
            'admin_pass': 'password',
            'name': 'teeth',
            'random_seed': str(uuid.uuid4()).encode('base64'),
            'hostname': 'teeth-test',
            'availability_zone': 'teeth',
            'launch_index': 0,
        }
        data = json.dumps(data)
        f.write(data)

    command = ['sh', 'shell/makefs.sh', configdrive, image, device]
    return subprocess.call(command)


def _download_image(image_info):
    resp = requests.get(image_info['urls'][0], stream=True)
    if resp.status_code != 200:
        # TODO(jimrollenhagen) define a better exception
        raise Exception
    image_location = _image_location(image_info)
    with open(image_location, 'wb') as f:
        for chunk in resp.iter_content():
            f.write(chunk)

    if not _verify_image(image_info, image_location):
        # TODO(jimrollenhagen) better exception
        # TODO(jimrollenhagen) retry?
        raise Exception


def _verify_image(image_info, image_location):
    # TODO(jimrollenhagen) verify the image checksum
    return True


class CacheImagesCommand(base.AsyncCommandResult):
    def execute(self):
        # TODO(russellhaering): Actually cache images
        pass


class PrepareImageCommand(base.AsyncCommandResult):
    """Downloads and writes an image and configdrive to a device."""
    def execute(self):
        image_info = self.command_params
        _download_image(image_info)
        _write_image(image_info)


class RunImageCommand(base.AsyncCommandResult):
    def execute(self):
        # TODO(jimrollenhagen): Actually run image, reboot/kexec/whatever
        pass


class StandbyAgent(base.BaseTeethAgent):
    def __init__(self, listen_host, listen_port, api_url):
        super(StandbyAgent, self).__init__(listen_host,
                                           listen_port,
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

        if type(image_info['urls']) != list:
            raise errors.InvalidCommandParamsError(
                'Image \'urls\' must be a list.')

        if type(image_info['hashes']) != dict:
            raise errors.InvalidCommandParamsError(
                'Image \'hashes\' must be a dictionary.')

    def cache_images(self, command_name, image_infos):
        if type(image_infos) != list:
            raise errors.InvalidCommandParamsError(
                '\'image_infos\' parameter must be a list.')

        for image_info in image_infos:
            self._validate_image_info(image_info)

        return CacheImagesCommand(command_name, image_infos).start()

    def prepare_image(self, command_name, image_info):
        self._validate_image_info(image_info)

        return PrepareImageCommand(command_name, image_info).start()

    def run_image(self, command_name, image_info):
        self._validate_image_info(image_info)

        return RunImageCommand(command_name, image_info).start()

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

from teeth_agent import base
from teeth_agent import errors


class CacheImagesCommand(base.AsyncCommandResult):
    def execute(self):
        # TODO(russellhaering): Actually cache images
        pass


class StandbyAgent(base.BaseTeethAgent):
    def __init__(self, listen_host, listen_port, api_url):
        super(StandbyAgent, self).__init__(listen_host,
                                           listen_port,
                                           api_url,
                                           'STANDBY')

        self.command_map = {
            'standby.cache_images': self.cache_images,
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

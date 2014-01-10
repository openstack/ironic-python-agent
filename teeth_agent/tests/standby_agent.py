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

import unittest

from teeth_agent import errors
from teeth_agent import standby


class TestBaseTeethAgent(unittest.TestCase):
    def setUp(self):
        self.agent = standby.StandbyAgent('fake_host', 'fake_port', 'fake_api')

    def test_standby_mode(self):
        self.assertEqual(self.agent.mode, 'STANDBY')

    def _build_fake_image_info(self):
        return {
            'id': 'fake_id',
            'urls': [
                'http://example.org',
            ],
            'hashes': {
                'md5': 'abc123',
            },
        }

    def test_validate_image_info_success(self):
        self.agent._validate_image_info(self._build_fake_image_info())

    def test_validate_image_info_missing_field(self):
        for field in ['id', 'urls', 'hashes']:
            invalid_info = self._build_fake_image_info()
            del invalid_info[field]

            self.assertRaises(errors.InvalidCommandParamsError,
                              self.agent._validate_image_info,
                              invalid_info)

    def test_validate_image_info_invalid_urls(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['urls'] = 'this_is_not_a_list'

        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent._validate_image_info,
                          invalid_info)

    def test_validate_image_info_invalid_hashes(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['hashes'] = 'this_is_not_a_dict'

        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent._validate_image_info,
                          invalid_info)

    def test_cache_images_success(self):
        result = self.agent.cache_images('cache_images',
                                         [self._build_fake_image_info()])
        result.join()

    def test_cache_images_invalid_image_list(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent.cache_images,
                          'cache_images',
                          {'foo': 'bar'})

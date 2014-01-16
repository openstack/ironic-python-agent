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
import mock
import os
import unittest

from teeth_agent import errors
from teeth_agent import standby


class TestBaseTeethAgent(unittest.TestCase):
    def setUp(self):
        self.agent = standby.StandbyAgent(None, 9999, None, 9999, 'fake_api')

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

    def test_validate_image_info_empty_urls(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['urls'] = []

        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent._validate_image_info,
                          invalid_info)

    def test_validate_image_info_invalid_hashes(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['hashes'] = 'this_is_not_a_dict'

        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent._validate_image_info,
                          invalid_info)

    def test_validate_image_info_empty_hashes(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['hashes'] = {}

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

    def test_image_location(self):
        image_info = self._build_fake_image_info()
        location = standby._image_location(image_info)
        self.assertEqual(location, '/tmp/fake_id')

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('os.makedirs', autospec=True)
    @mock.patch('os.path', autospec=True)
    def test_write_local_config_drive(self, path_mock, makedirs_mock,
                                      open_mock):
        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        write_mock = open_mock.return_value.write
        path_mock.exists.return_value = True
        path_mock.join.return_value = '/tmp/configdrive/meta_data.json'

        location = '/tmp/configdrive'
        filename = '{}/meta_data.json'.format(location)
        data = {'uuid': 'test', 'hostname': 'teeth-test'}

        standby._write_local_config_drive(location, data)
        path_mock.exists.assert_called_once_with(location)
        self.assertEqual(makedirs_mock.call_count, 0)
        open_mock.assert_called_once_with(filename, 'w')
        write_mock.assert_called_once_with(json.dumps(data))

        path_mock.exists.return_value = False
        standby._write_local_config_drive(location, data)
        self.assertEqual(makedirs_mock.call_count, 1)

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('subprocess.call', autospec=True)
    def test_write_image(self, call_mock, open_mock):
        image_info = self._build_fake_image_info()
        configdrive = 'configdrive'
        device = '/dev/sda'
        location = standby._image_location(image_info)
        standby_dir = os.path.dirname(os.path.realpath(standby.__file__))
        script = os.path.join(standby_dir, 'shell/makefs.sh')
        command = ['/bin/bash', script, configdrive, location, device]
        call_mock.return_value = 0

        standby._write_image(image_info,
                             configdrive,
                             device)
        call_mock.assert_called_once_with(command)

        call_mock.reset_mock()
        call_mock.return_value = 1

        self.assertRaises(errors.ImageWriteError,
                          standby._write_image,
                          image_info,
                          configdrive,
                          device)

        call_mock.assert_called_once_with(command)

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image(self, requests_mock, open_mock, md5_mock):
        image_info = self._build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        read_mock = open_mock.return_value.read
        read_mock.return_value = 'content'
        md5_mock.return_value = image_info['hashes'].values()[0]

        standby._download_image(image_info)
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              stream=True)
        write = open_mock.return_value.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(write.call_count, 2)

    @mock.patch('requests.get', autospec=True)
    def test_download_image_bad_status(self, requests_mock):
        image_info = self._build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 404
        self.assertRaises(errors.ImageDownloadError,
                          standby._download_image,
                          image_info)

    @mock.patch('teeth_agent.standby._verify_image', autospec=True)
    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image_verify_fails(self, requests_mock, open_mock,
                                         verify_mock):
        image_info = self._build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        verify_mock.return_value = False
        self.assertRaises(errors.ImageChecksumError,
                          standby._download_image,
                          image_info)

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('hashlib.sha1', autospec=True)
    @mock.patch('hashlib.md5', autospec=True)
    def test_verify_image_success(self, md5_mock, sha1_mock, open_mock):
        image_info = self._build_fake_image_info()
        image_info['hashes']['sha1'] = image_info['hashes']['md5']
        md5_mock.return_value = image_info['hashes']['md5']
        sha1_mock.return_value = image_info['hashes']['sha1']
        image_location = '/foo/bar'

        verified = standby._verify_image(image_info, image_location)
        self.assertTrue(verified)
        # make sure we only check one hash, even though both are valid
        self.assertEqual(md5_mock.call_count + sha1_mock.call_count, 1)

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('hashlib.md5', autospec=True)
    def test_verify_image_failure(self, md5_mock, open_mock):
        image_info = self._build_fake_image_info()
        md5_mock.return_value = 'wrong hash'
        image_location = '/foo/bar'

        verified = standby._verify_image(image_info, image_location)
        self.assertFalse(verified)
        self.assertEqual(md5_mock.call_count, 1)

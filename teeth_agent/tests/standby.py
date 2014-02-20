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

import mock
import unittest

from teeth_agent import errors
from teeth_agent import standby


class TestStandbyMode(unittest.TestCase):
    def setUp(self):
        self.agent_mode = standby.StandbyMode()

    def test_standby_mode(self):
        self.assertEqual(self.agent_mode.name, 'STANDBY')

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
        standby._validate_image_info(self._build_fake_image_info())

    def test_validate_image_info_missing_field(self):
        for field in ['id', 'urls', 'hashes']:
            invalid_info = self._build_fake_image_info()
            del invalid_info[field]

            self.assertRaises(errors.InvalidCommandParamsError,
                              standby._validate_image_info,
                              invalid_info)

    def test_validate_image_info_invalid_urls(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['urls'] = 'this_is_not_a_list'

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_empty_urls(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['urls'] = []

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_invalid_hashes(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['hashes'] = 'this_is_not_a_dict'

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_empty_hashes(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['hashes'] = {}

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_cache_image_success(self):
        result = self.agent_mode.cache_image(
            'cache_image',
            image_info=self._build_fake_image_info())
        result.join()

    def test_cache_image_invalid_image_list(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent_mode.cache_image,
                          'cache_image',
                          image_info={'foo': 'bar'})

    def test_image_location(self):
        image_info = self._build_fake_image_info()
        location = standby._image_location(image_info)
        self.assertEqual(location, '/tmp/fake_id')

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('subprocess.call', autospec=True)
    def test_write_image(self, call_mock, open_mock):
        image_info = self._build_fake_image_info()
        device = '/dev/sda'
        location = standby._image_location(image_info)
        script = standby._path_to_script('shell/write_image.sh')
        command = ['/bin/bash', script, location, device]
        call_mock.return_value = 0

        standby._write_image(image_info, device)
        call_mock.assert_called_once_with(command)

        call_mock.reset_mock()
        call_mock.return_value = 1

        self.assertRaises(errors.ImageWriteError,
                          standby._write_image,
                          image_info,
                          device)

        call_mock.assert_called_once_with(command)

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('subprocess.call', autospec=True)
    def test_copy_configdrive_to_disk(self, call_mock, open_mock):
        device = '/dev/sda'
        configdrive = 'configdrive'
        script = standby._path_to_script('shell/copy_configdrive_to_disk.sh')
        command = ['/bin/bash', script, configdrive, device]
        call_mock.return_value = 0

        standby._copy_configdrive_to_disk(configdrive, device)
        call_mock.assert_called_once_with(command)

        call_mock.reset_mock()
        call_mock.return_value = 1

        self.assertRaises(errors.ConfigDriveWriteError,
                          standby._copy_configdrive_to_disk,
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
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['hashes'].values()[0]

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
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['hashes']['md5']
        hexdigest_mock = sha1_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['hashes']['sha1']
        image_location = '/foo/bar'

        verified = standby._verify_image(image_info, image_location)
        self.assertTrue(verified)
        # make sure we only check one hash, even though both are valid
        self.assertEqual(md5_mock.call_count + sha1_mock.call_count, 1)

    @mock.patch('__builtin__.open', autospec=True)
    @mock.patch('hashlib.md5', autospec=True)
    def test_verify_image_failure(self, md5_mock, open_mock):
        image_info = self._build_fake_image_info()
        md5_mock.return_value.hexdigest.return_value = 'wrong hash'
        image_location = '/foo/bar'

        verified = standby._verify_image(image_info, image_location)
        self.assertFalse(verified)
        self.assertEqual(md5_mock.call_count, 1)

    @mock.patch('teeth_agent.standby._write_image', autospec=True)
    @mock.patch('teeth_agent.standby._download_image', autospec=True)
    def test_cache_image(self, download_mock, write_mock):
        image_info = self._build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        async_result = self.agent_mode.cache_image('cache_image',
                                                   image_info=image_info)
        async_result.join()
        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, None)
        self.assertEqual(self.agent_mode.cached_image_id, image_info['id'])
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertEqual(None, async_result.command_result)

    @mock.patch('teeth_agent.standby._copy_configdrive_to_disk', autospec=True)
    @mock.patch('teeth_agent.standby.configdrive.write_configdrive',
                autospec=True)
    @mock.patch('teeth_agent.hardware.get_manager', autospec=True)
    @mock.patch('teeth_agent.standby._write_image', autospec=True)
    @mock.patch('teeth_agent.standby._download_image', autospec=True)
    @mock.patch('teeth_agent.standby._configdrive_location', autospec=True)
    def test_prepare_image(self,
                           location_mock,
                           download_mock,
                           write_mock,
                           hardware_mock,
                           configdrive_mock,
                           configdrive_copy_mock):
        image_info = self._build_fake_image_info()
        location_mock.return_value = 'THE CLOUD'
        download_mock.return_value = None
        write_mock.return_value = None
        manager_mock = hardware_mock.return_value
        manager_mock.get_os_install_device.return_value = 'manager'
        configdrive_mock.return_value = None
        configdrive_copy_mock.return_value = None

        async_result = self.agent_mode.prepare_image('prepare_image',
                                                     image_info=image_info,
                                                     metadata={},
                                                     files=[])
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        configdrive_mock.assert_called_once_with('THE CLOUD', {}, [])
        configdrive_copy_mock.assert_called_once_with('THE CLOUD', 'manager')

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertEqual(None, async_result.command_result)

        download_mock.reset_mock()
        write_mock.reset_mock()
        configdrive_mock.reset_mock()
        configdrive_copy_mock.reset_mock()
        # image is now cached, make sure download/write doesn't happen
        async_result = self.agent_mode.prepare_image('prepare_image',
                                                     image_info=image_info,
                                                     metadata={},
                                                     files=[])
        async_result.join()

        self.assertEqual(download_mock.call_count, 0)
        self.assertEqual(write_mock.call_count, 0)
        configdrive_mock.assert_called_once_with('THE CLOUD', {}, [])
        configdrive_copy_mock.assert_called_once_with('THE CLOUD', 'manager')

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertEqual(None, async_result.command_result)

    @mock.patch('subprocess.call', autospec=True)
    def test_run_image(self, call_mock):
        script = standby._path_to_script('shell/reboot.sh')
        command = ['/bin/bash', script]
        call_mock.return_value = 0

        success_result = self.agent_mode.run_image('run_image')
        success_result.join()
        call_mock.assert_called_once_with(command)

        call_mock.reset_mock()
        call_mock.return_value = 1

        failed_result = self.agent_mode.run_image('run_image')
        failed_result.join()

        call_mock.assert_called_once_with(command)
        self.assertEqual('FAILED', failed_result.command_status)

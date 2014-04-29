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

import mock
from oslotest import base as test_base
import six

from ironic_python_agent import errors
from ironic_python_agent.extensions import standby

if six.PY2:
    OPEN_FUNCTION_NAME = '__builtin__.open'
else:
    OPEN_FUNCTION_NAME = 'builtins.open'


class TestStandbyExtension(test_base.BaseTestCase):
    def setUp(self):
        super(TestStandbyExtension, self).setUp()
        self.agent_extension = standby.StandbyExtension()

    def _build_fake_image_info(self):
        return {
            'id': 'fake_id',
            'urls': [
                'http://example.org',
            ],
            'checksum': 'abc123'
        }

    def test_validate_image_info_success(self):
        standby._validate_image_info(None, self._build_fake_image_info())

    def test_validate_image_info_missing_field(self):
        for field in ['id', 'urls', 'checksum']:
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

    def test_validate_image_info_invalid_checksum(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['checksum'] = {'not': 'a string'}

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_empty_checksum(self):
        invalid_info = self._build_fake_image_info()
        invalid_info['checksum'] = ''

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_cache_image_success(self):
        result = self.agent_extension.cache_image(
            'cache_image',
            image_info=self._build_fake_image_info())
        result.join()

    def test_cache_image_invalid_image_list(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent_extension.cache_image,
                          'cache_image',
                          image_info={'foo': 'bar'})

    def test_image_location(self):
        image_info = self._build_fake_image_info()
        location = standby._image_location(image_info)
        self.assertEqual(location, '/tmp/fake_id')

    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_write_image(self, execute_mock, open_mock):
        image_info = self._build_fake_image_info()
        device = '/dev/sda'
        location = standby._image_location(image_info)
        script = standby._path_to_script('shell/write_image.sh')
        command = ['/bin/bash', script, location, device]
        execute_mock.return_value = 0

        standby._write_image(image_info, device)
        execute_mock.assert_called_once_with(*command)

        execute_mock.reset_mock()
        execute_mock.return_value = 1

        self.assertRaises(errors.ImageWriteError,
                          standby._write_image,
                          image_info,
                          device)

        execute_mock.assert_called_once_with(*command)

    @mock.patch('gzip.GzipFile', autospec=True)
    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
    @mock.patch('base64.b64decode', autospec=True)
    def test_write_configdrive_to_file(self, b64_mock, open_mock, gzip_mock):
        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        write_mock = open_mock.return_value.write
        gzip_read_mock = gzip_mock.return_value.read
        gzip_read_mock.return_value = 'ungzipped'
        b64_mock.return_value = 'configdrive_data'
        filename = standby._configdrive_location()

        standby._write_configdrive_to_file('b64data', filename)
        open_mock.assert_called_once_with(filename, 'wb')
        gzip_read_mock.assert_called_once_with()
        write_mock.assert_called_once_with('ungzipped')

    @mock.patch('os.stat', autospec=True)
    @mock.patch(('ironic_python_agent.extensions.standby.'
                 '_write_configdrive_to_file'),
                autospec=True)
    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_write_configdrive_to_partition(self, execute_mock, open_mock,
                                            configdrive_mock, stat_mock):
        device = '/dev/sda'
        configdrive = standby._configdrive_location()
        script = standby._path_to_script('shell/copy_configdrive_to_disk.sh')
        command = ['/bin/bash', script, configdrive, device]
        execute_mock.return_value = 0
        stat_mock.return_value.st_size = 5

        standby._write_configdrive_to_partition(configdrive, device)
        execute_mock.assert_called_once_with(*command)

        execute_mock.reset_mock()
        execute_mock.return_value = 1

        self.assertRaises(errors.ConfigDriveWriteError,
                          standby._write_configdrive_to_partition,
                          configdrive,
                          device)

        execute_mock.assert_called_once_with(*command)

    @mock.patch('os.stat', autospec=True)
    @mock.patch(('ironic_python_agent.extensions.standby.'
                 '_write_configdrive_to_file'),
                autospec=True)
    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_write_configdrive_too_large(self, execute_mock, open_mock,
                                         configdrive_mock, stat_mock):
        device = '/dev/sda'
        configdrive = standby._configdrive_location()
        stat_mock.return_value.st_size = 65 * 1024 * 1024

        self.assertRaises(errors.ConfigDriveTooLargeError,
                          standby._write_configdrive_to_partition,
                          configdrive,
                          device)

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
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
        hexdigest_mock.return_value = image_info['checksum']

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

    @mock.patch('ironic_python_agent.extensions.standby._verify_image',
                autospec=True)
    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
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

    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
    @mock.patch('hashlib.md5', autospec=True)
    def test_verify_image_success(self, md5_mock, open_mock):
        image_info = self._build_fake_image_info()
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['checksum']
        image_location = '/foo/bar'

        verified = standby._verify_image(image_info, image_location)
        self.assertTrue(verified)
        self.assertEqual(1, md5_mock.call_count)

    @mock.patch(OPEN_FUNCTION_NAME, autospec=True)
    @mock.patch('hashlib.md5', autospec=True)
    def test_verify_image_failure(self, md5_mock, open_mock):
        image_info = self._build_fake_image_info()
        md5_mock.return_value.hexdigest.return_value = 'wrong hash'
        image_location = '/foo/bar'

        verified = standby._verify_image(image_info, image_location)
        self.assertFalse(verified)
        self.assertEqual(md5_mock.call_count, 1)

    @mock.patch('ironic_python_agent.hardware.get_manager', autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_cache_image(self, download_mock, write_mock, hardware_mock):
        image_info = self._build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        manager_mock = hardware_mock.return_value
        manager_mock.get_os_install_device.return_value = 'manager'
        async_result = self.agent_extension.cache_image('cache_image',
                                                   image_info=image_info)
        async_result.join()
        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        self.assertEqual(self.agent_extension.cached_image_id,
                         image_info['id'])
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertEqual(None, async_result.command_result)

    @mock.patch(('ironic_python_agent.extensions.standby.'
                 '_write_configdrive_to_partition'),
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.get_manager', autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._configdrive_location',
                autospec=True)
    def test_prepare_image(self,
                           location_mock,
                           download_mock,
                           write_mock,
                           hardware_mock,
                           configdrive_copy_mock):
        image_info = self._build_fake_image_info()
        location_mock.return_value = '/tmp/configdrive'
        download_mock.return_value = None
        write_mock.return_value = None
        manager_mock = hardware_mock.return_value
        manager_mock.get_os_install_device.return_value = 'manager'
        configdrive_copy_mock.return_value = None

        async_result = self.agent_extension.prepare_image('prepare_image',
                image_info=image_info,
                configdrive='configdrive_data')
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        configdrive_copy_mock.assert_called_once_with('configdrive_data',
                                                      'manager')

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertEqual(None, async_result.command_result)

        download_mock.reset_mock()
        write_mock.reset_mock()
        configdrive_copy_mock.reset_mock()
        # image is now cached, make sure download/write doesn't happen
        async_result = self.agent_extension.prepare_image('prepare_image',
                image_info=image_info,
                configdrive='configdrive_data')
        async_result.join()

        self.assertEqual(download_mock.call_count, 0)
        self.assertEqual(write_mock.call_count, 0)
        configdrive_copy_mock.assert_called_once_with('configdrive_data',
                                                      'manager')

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertEqual(None, async_result.command_result)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_image(self, execute_mock):
        script = standby._path_to_script('shell/reboot.sh')
        command = ['/bin/bash', script]
        execute_mock.return_value = 0

        success_result = self.agent_extension.run_image('run_image')
        success_result.join()
        execute_mock.assert_called_once_with(*command)

        execute_mock.reset_mock()
        execute_mock.return_value = 1

        failed_result = self.agent_extension.run_image('run_image')
        failed_result.join()

        execute_mock.assert_called_once_with(*command)
        self.assertEqual('FAILED', failed_result.command_status)

    def test_path_to_script(self):
        script = standby._path_to_script('shell/reboot.sh')
        self.assertTrue(script.endswith('extensions/../shell/reboot.sh'))

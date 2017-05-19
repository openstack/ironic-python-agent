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

import os

import mock
from oslo_concurrency import processutils
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent.extensions import standby


def _build_fake_image_info():
    return {
        'id': 'fake_id',
        'node_uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
        'urls': [
            'http://example.org',
        ],
        'checksum': 'abc123'
    }


def _build_fake_partition_image_info():
    return {
        'id': 'fake_id',
        'urls': [
            'http://example.org',
        ],
        'node_uuid': 'node_uuid',
        'checksum': 'abc123',
        'root_mb': '10',
        'swap_mb': '10',
        'ephemeral_mb': '10',
        'ephemeral_format': 'abc',
        'preserve_ephemeral': 'False',
        'configdrive': 'configdrive',
        'image_type': 'partition',
        'boot_option': 'netboot',
        'disk_label': 'msdos',
        'deploy_boot_mode': 'bios'}


class TestStandbyExtension(test_base.BaseTestCase):
    def setUp(self):
        super(TestStandbyExtension, self).setUp()
        self.agent_extension = standby.StandbyExtension()

    def test_validate_image_info_success(self):
        standby._validate_image_info(None, _build_fake_image_info())

    def test_validate_image_info_missing_field(self):
        for field in ['id', 'urls', 'checksum']:
            invalid_info = _build_fake_image_info()
            del invalid_info[field]

            self.assertRaises(errors.InvalidCommandParamsError,
                              standby._validate_image_info,
                              invalid_info)

    def test_validate_image_info_invalid_urls(self):
        invalid_info = _build_fake_image_info()
        invalid_info['urls'] = 'this_is_not_a_list'

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_empty_urls(self):
        invalid_info = _build_fake_image_info()
        invalid_info['urls'] = []

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_invalid_checksum(self):
        invalid_info = _build_fake_image_info()
        invalid_info['checksum'] = {'not': 'a string'}

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_empty_checksum(self):
        invalid_info = _build_fake_image_info()
        invalid_info['checksum'] = ''

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_cache_image_invalid_image_list(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent_extension.cache_image,
                          image_info={'foo': 'bar'})

    def test_image_location(self):
        image_info = _build_fake_image_info()
        location = standby._image_location(image_info)
        self.assertEqual('/tmp/fake_id', location)

    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_write_image(self, execute_mock, open_mock):
        image_info = _build_fake_image_info()
        device = '/dev/sda'
        location = standby._image_location(image_info)
        script = standby._path_to_script('shell/write_image.sh')
        command = ['/bin/bash', script, location, device]
        execute_mock.return_value = ('', '')

        standby._write_image(image_info, device)
        execute_mock.assert_called_once_with(*command, check_exit_code=[0])

        execute_mock.reset_mock()
        execute_mock.return_value = ('', '')
        execute_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(errors.ImageWriteError,
                          standby._write_image,
                          image_info,
                          device)

        execute_mock.assert_called_once_with(*command, check_exit_code=[0])

    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch('ironic_lib.disk_utils.get_image_mb', autospec=True)
    @mock.patch('ironic_lib.disk_utils.work_on_disk', autospec=True)
    def test_write_partition_image_exception(self, work_on_disk_mock,
                                             image_mb_mock,
                                             execute_mock, open_mock):
        image_info = _build_fake_partition_image_info()
        device = '/dev/sda'
        root_mb = image_info['root_mb']
        swap_mb = image_info['swap_mb']
        ephemeral_mb = image_info['ephemeral_mb']
        ephemeral_format = image_info['ephemeral_format']
        node_uuid = image_info['node_uuid']
        pr_ep = image_info['preserve_ephemeral']
        configdrive = image_info['configdrive']
        boot_mode = image_info['deploy_boot_mode']
        boot_option = image_info['boot_option']
        disk_label = image_info['disk_label']

        image_path = standby._image_location(image_info)

        image_mb_mock.return_value = 1
        exc = errors.ImageWriteError
        Exception_returned = processutils.ProcessExecutionError
        work_on_disk_mock.side_effect = Exception_returned

        self.assertRaises(exc, standby._write_image, image_info,
                          device)
        image_mb_mock.assert_called_once_with(image_path)
        work_on_disk_mock.assert_called_once_with(device, root_mb, swap_mb,
                                                  ephemeral_mb,
                                                  ephemeral_format,
                                                  image_path,
                                                  node_uuid,
                                                  configdrive=configdrive,
                                                  preserve_ephemeral=pr_ep,
                                                  boot_mode=boot_mode,
                                                  boot_option=boot_option,
                                                  disk_label=disk_label)

    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch('ironic_lib.disk_utils.get_image_mb', autospec=True)
    @mock.patch('ironic_lib.disk_utils.work_on_disk', autospec=True)
    def test_write_partition_image_no_node_uuid(self, work_on_disk_mock,
                                                image_mb_mock,
                                                execute_mock, open_mock):
        image_info = _build_fake_partition_image_info()
        image_info['node_uuid'] = None
        device = '/dev/sda'
        root_mb = image_info['root_mb']
        swap_mb = image_info['swap_mb']
        ephemeral_mb = image_info['ephemeral_mb']
        ephemeral_format = image_info['ephemeral_format']
        node_uuid = image_info['node_uuid']
        pr_ep = image_info['preserve_ephemeral']
        configdrive = image_info['configdrive']
        boot_mode = image_info['deploy_boot_mode']
        boot_option = image_info['boot_option']
        disk_label = image_info['disk_label']

        image_path = standby._image_location(image_info)

        image_mb_mock.return_value = 1
        uuids = {'root uuid': 'root_uuid'}
        expected_uuid = {'root uuid': 'root_uuid'}
        image_mb_mock.return_value = 1
        work_on_disk_mock.return_value = uuids

        standby._write_image(image_info, device)
        image_mb_mock.assert_called_once_with(image_path)
        work_on_disk_mock.assert_called_once_with(device, root_mb, swap_mb,
                                                  ephemeral_mb,
                                                  ephemeral_format,
                                                  image_path,
                                                  node_uuid,
                                                  configdrive=configdrive,
                                                  preserve_ephemeral=pr_ep,
                                                  boot_mode=boot_mode,
                                                  boot_option=boot_option,
                                                  disk_label=disk_label)

        self.assertEqual(expected_uuid, work_on_disk_mock.return_value)
        self.assertIsNone(node_uuid)

    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch('ironic_lib.disk_utils.get_image_mb', autospec=True)
    @mock.patch('ironic_lib.disk_utils.work_on_disk', autospec=True)
    def test_write_partition_image_exception_image_mb(self,
                                                      work_on_disk_mock,
                                                      image_mb_mock,
                                                      execute_mock,
                                                      open_mock):
        image_info = _build_fake_partition_image_info()
        device = '/dev/sda'
        image_path = standby._image_location(image_info)

        image_mb_mock.return_value = 20
        exc = errors.InvalidCommandParamsError

        self.assertRaises(exc, standby._write_image, image_info,
                          device)
        image_mb_mock.assert_called_once_with(image_path)
        self.assertFalse(work_on_disk_mock.called)

    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch('ironic_lib.disk_utils.work_on_disk', autospec=True)
    @mock.patch('ironic_lib.disk_utils.get_image_mb', autospec=True)
    def test_write_partition_image(self, image_mb_mock, work_on_disk_mock,
                                   execute_mock, open_mock):
        image_info = _build_fake_partition_image_info()
        device = '/dev/sda'
        root_mb = image_info['root_mb']
        swap_mb = image_info['swap_mb']
        ephemeral_mb = image_info['ephemeral_mb']
        ephemeral_format = image_info['ephemeral_format']
        node_uuid = image_info['node_uuid']
        pr_ep = image_info['preserve_ephemeral']
        configdrive = image_info['configdrive']
        boot_mode = image_info['deploy_boot_mode']
        boot_option = image_info['boot_option']
        disk_label = image_info['disk_label']

        image_path = standby._image_location(image_info)
        uuids = {'root uuid': 'root_uuid'}
        expected_uuid = {'root uuid': 'root_uuid'}
        image_mb_mock.return_value = 1
        work_on_disk_mock.return_value = uuids

        standby._write_image(image_info, device)
        image_mb_mock.assert_called_once_with(image_path)
        work_on_disk_mock.assert_called_once_with(device, root_mb, swap_mb,
                                                  ephemeral_mb,
                                                  ephemeral_format,
                                                  image_path,
                                                  node_uuid,
                                                  configdrive=configdrive,
                                                  preserve_ephemeral=pr_ep,
                                                  boot_mode=boot_mode,
                                                  boot_option=boot_option,
                                                  disk_label=disk_label)

        self.assertEqual(expected_uuid, work_on_disk_mock.return_value)

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image(self, requests_mock, open_mock, md5_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['checksum']

        standby._download_image(image_info)
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={})
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    @mock.patch.dict(os.environ, {})
    def test_download_image_proxy(
            self, requests_mock, open_mock, md5_mock):
        image_info = _build_fake_image_info()
        proxies = {'http': 'http://a.b.com',
                   'https': 'https://secure.a.b.com'}
        no_proxy = '.example.org,.b.com'
        image_info['proxies'] = proxies
        image_info['no_proxy'] = no_proxy
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['checksum']

        standby._download_image(image_info)
        self.assertEqual(no_proxy, os.environ['no_proxy'])
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies=proxies)
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)

    @mock.patch('requests.get', autospec=True)
    def test_download_image_bad_status(self, requests_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 404
        self.assertRaises(errors.ImageDownloadError,
                          standby._download_image,
                          image_info)

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image_verify_fails(self, requests_mock, open_mock,
                                         md5_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = 'invalid-checksum'
        self.assertRaises(errors.ImageChecksumError,
                          standby._download_image,
                          image_info)

    def test_verify_image_success(self):
        image_info = _build_fake_image_info()
        image_location = '/foo/bar'
        checksum = image_info['checksum']
        standby._verify_image(image_info, image_location, checksum)

    def test_verify_image_failure(self):
        image_info = _build_fake_image_info()
        image_location = '/foo/bar'
        checksum = 'invalid-checksum'
        self.assertRaises(errors.ImageChecksumError,
                          standby._verify_image,
                          image_info, image_location, checksum)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_cache_image(self, download_mock, write_mock,
                         dispatch_mock):
        image_info = _build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        async_result = self.agent_extension.cache_image(image_info=image_info)
        async_result.join()
        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        dispatch_mock.assert_called_once_with('get_os_install_device')
        self.assertEqual(image_info['id'],
                         self.agent_extension.cached_image_id)
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('cache_image: image ({}) cached to device '
                      '{} ').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_cache_partition_image(self, download_mock, write_mock,
                                   dispatch_mock):
        image_info = _build_fake_partition_image_info()
        download_mock.return_value = None
        write_mock.return_value = {'root uuid': 'root_uuid'}
        dispatch_mock.return_value = 'manager'
        async_result = self.agent_extension.cache_image(image_info=image_info)
        async_result.join()
        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        dispatch_mock.assert_called_once_with('get_os_install_device')
        self.assertEqual(image_info['id'],
                         self.agent_extension.cached_image_id)
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('cache_image: image ({}) cached to device {} '
                      'root_uuid={}').format(image_info['id'], 'manager',
                                             'root_uuid')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_cache_image_force(self, download_mock, write_mock,
                               dispatch_mock):
        image_info = _build_fake_image_info()
        self.agent_extension.cached_image_id = image_info['id']
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        async_result = self.agent_extension.cache_image(
            image_info=image_info, force=True
        )
        async_result.join()
        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        dispatch_mock.assert_called_once_with('get_os_install_device')
        self.assertEqual(image_info['id'],
                         self.agent_extension.cached_image_id)
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('cache_image: image ({}) cached to device '
                      '{} ').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_cache_image_cached(self, download_mock, write_mock,
                                dispatch_mock):
        image_info = _build_fake_image_info()
        self.agent_extension.cached_image_id = image_info['id']
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        async_result = self.agent_extension.cache_image(image_info=image_info)
        async_result.join()
        self.assertFalse(download_mock.called)
        self.assertFalse(write_mock.called)
        dispatch_mock.assert_called_once_with('get_os_install_device')
        self.assertEqual(image_info['id'],
                         self.agent_extension.cached_image_id)
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('cache_image: image ({}) already present on device '
                      '{} ').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_lib.disk_utils.create_config_drive_partition',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_prepare_image(self,
                           download_mock,
                           write_mock,
                           dispatch_mock,
                           configdrive_copy_mock):
        image_info = _build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive='configdrive_data'
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        dispatch_mock.assert_called_once_with('get_os_install_device')
        configdrive_copy_mock.assert_called_once_with(image_info['node_uuid'],
                                                      'manager',
                                                      'configdrive_data')

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('prepare_image: image ({}) written to device '
                      '{} ').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_lib.disk_utils.create_config_drive_partition',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_prepare_partition_image(self,
                                     download_mock,
                                     write_mock,
                                     dispatch_mock,
                                     configdrive_copy_mock):
        image_info = _build_fake_partition_image_info()
        download_mock.return_value = None
        write_mock.return_value = {'root uuid': 'root_uuid'}
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive='configdrive_data'
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        dispatch_mock.assert_called_once_with('get_os_install_device')
        self.assertFalse(configdrive_copy_mock.called)

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('prepare_image: image ({}) written to device {} '
                      'root_uuid={}').format(
            image_info['id'], 'manager', 'root_uuid')
        self.assertEqual(cmd_result, async_result.command_result['result'])

        download_mock.reset_mock()
        write_mock.reset_mock()
        configdrive_copy_mock.reset_mock()
        # image is now cached, make sure download/write doesn't happen
        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive='configdrive_data'
        )
        async_result.join()

        self.assertEqual(0, download_mock.call_count)
        self.assertEqual(0, write_mock.call_count)
        self.assertFalse(configdrive_copy_mock.called)

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('prepare_image: image ({}) written to device {} '
                      'root_uuid={}').format(
            image_info['id'], 'manager', 'root_uuid')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_lib.disk_utils.create_config_drive_partition',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_prepare_image_no_configdrive(self,
                                          download_mock,
                                          write_mock,
                                          dispatch_mock,
                                          configdrive_copy_mock):
        image_info = _build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive=None
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager')
        dispatch_mock.assert_called_once_with('get_os_install_device')

        self.assertEqual(0, configdrive_copy_mock.call_count)
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('prepare_image: image ({}) written to device '
                      '{} ').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_lib.disk_utils.create_config_drive_partition',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby.StandbyExtension'
                '._cache_and_write_image', autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby.StandbyExtension'
                '._stream_raw_image_onto_device', autospec=True)
    def _test_prepare_image_raw(self, image_info, stream_mock,
                                cache_write_mock, dispatch_mock,
                                configdrive_copy_mock):
        dispatch_mock.return_value = '/dev/foo'
        configdrive_copy_mock.return_value = None

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive=None
        )
        async_result.join()

        dispatch_mock.assert_called_once_with('get_os_install_device')
        self.assertFalse(configdrive_copy_mock.called)

        # Assert we've streamed the image or not
        if image_info['stream_raw_images']:
            stream_mock.assert_called_once_with(mock.ANY, image_info,
                                                '/dev/foo')
            self.assertFalse(cache_write_mock.called)
        else:
            cache_write_mock.assert_called_once_with(mock.ANY, image_info,
                                                     '/dev/foo')
            self.assertFalse(stream_mock.called)

    def test_prepare_image_raw_stream_true(self):
        image_info = _build_fake_image_info()
        image_info['disk_format'] = 'raw'
        image_info['stream_raw_images'] = True
        self._test_prepare_image_raw(image_info)

    def test_prepare_image_raw_and_stream_false(self):
        image_info = _build_fake_image_info()
        image_info['disk_format'] = 'raw'
        image_info['stream_raw_images'] = False
        self._test_prepare_image_raw(image_info)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_shutdown_command_invalid(self, execute_mock):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.agent_extension._run_shutdown_command, 'boot')

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_shutdown_command_fails(self, execute_mock):
        execute_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(errors.SystemRebootError,
                          self.agent_extension._run_shutdown_command, 'reboot')

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_shutdown_command_valid(self, execute_mock):
        execute_mock.return_value = ('', '')

        self.agent_extension._run_shutdown_command('poweroff')
        calls = [mock.call('sync'),
                 mock.call('poweroff', use_standard_locale=True,
                           check_exit_code=[0])]
        execute_mock.assert_has_calls(calls)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_shutdown_command_valid_poweroff_sysrq(self, execute_mock):
        execute_mock.side_effect = [('', ''), ('',
                                    'Running in chroot, ignoring request.'),
                                    ('', '')]

        self.agent_extension._run_shutdown_command('poweroff')
        calls = [mock.call('sync'),
                 mock.call('poweroff', use_standard_locale=True,
                           check_exit_code=[0]),
                 mock.call("echo o > /proc/sysrq-trigger", shell=True)]
        execute_mock.assert_has_calls(calls)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_shutdown_command_valid_reboot_sysrq(self, execute_mock):
        execute_mock.side_effect = [('', ''), ('',
                                    'Running in chroot, ignoring request.'),
                                    ('', '')]

        self.agent_extension._run_shutdown_command('reboot')
        calls = [mock.call('sync'),
                 mock.call('reboot', use_standard_locale=True,
                           check_exit_code=[0]),
                 mock.call("echo b > /proc/sysrq-trigger", shell=True)]
        execute_mock.assert_has_calls(calls)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_image(self, execute_mock):
        execute_mock.return_value = ('', '')

        success_result = self.agent_extension.run_image()
        success_result.join()
        calls = [mock.call('sync'),
                 mock.call('reboot', use_standard_locale=True,
                           check_exit_code=[0])]
        execute_mock.assert_has_calls(calls)
        self.assertEqual('SUCCEEDED', success_result.command_status)

        execute_mock.reset_mock()
        execute_mock.return_value = ('', '')
        execute_mock.side_effect = processutils.ProcessExecutionError

        failed_result = self.agent_extension.run_image()
        failed_result.join()

        execute_mock.assert_any_call('sync')
        self.assertEqual('FAILED', failed_result.command_status)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_power_off(self, execute_mock):
        execute_mock.return_value = ('', '')

        success_result = self.agent_extension.power_off()
        success_result.join()

        calls = [mock.call('sync'),
                 mock.call('poweroff', use_standard_locale=True,
                           check_exit_code=[0])]
        execute_mock.assert_has_calls(calls)
        self.assertEqual('SUCCEEDED', success_result.command_status)

        execute_mock.reset_mock()
        execute_mock.return_value = ('', '')
        execute_mock.side_effect = processutils.ProcessExecutionError

        failed_result = self.agent_extension.power_off()
        failed_result.join()

        execute_mock.assert_any_call('sync')
        self.assertEqual('FAILED', failed_result.command_status)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_sync(self, execute_mock):
        result = self.agent_extension.sync()
        execute_mock.assert_called_once_with('sync')
        self.assertEqual('SUCCEEDED', result.command_status)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_sync_error(self, execute_mock):
        execute_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(
            errors.CommandExecutionError, self.agent_extension.sync)
        execute_mock.assert_called_once_with('sync')

    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_cache_and_write_image(self, download_mock, write_mock):
        image_info = _build_fake_image_info()
        device = '/dev/foo'
        self.agent_extension._cache_and_write_image(image_info, device)
        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, device)

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_stream_raw_image_onto_device(self, requests_mock, open_mock,
                                          md5_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['checksum']

        self.agent_extension._stream_raw_image_onto_device(image_info,
                                                           '/dev/foo')
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={})
        expected_calls = [mock.call('some'), mock.call('content')]
        file_mock.write.assert_has_calls(expected_calls)

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_stream_raw_image_onto_device_write_error(self, requests_mock,
                                                      open_mock, md5_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.write.side_effect = Exception('Surprise!!!1!')
        hexdigest_mock = md5_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['checksum']

        self.assertRaises(errors.ImageDownloadError,
                          self.agent_extension._stream_raw_image_onto_device,
                          image_info, '/dev/foo')
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={})
        # Assert write was only called once and failed!
        file_mock.write.assert_called_once_with('some')

    def test__message_format_whole_disk(self):
        image_info = _build_fake_image_info()
        msg = 'image ({}) already present on device {}'
        device = '/dev/fake'
        partition_uuids = {}
        result_msg = standby._message_format(msg, image_info,
                                             device, partition_uuids)
        expected_msg = ('image (fake_id) already present on device '
                        '/dev/fake')
        self.assertEqual(expected_msg, result_msg)

    def test__message_format_partition_bios(self):
        image_info = _build_fake_partition_image_info()
        msg = ('image ({}) already present on device {} ')
        device = '/dev/fake'
        partition_uuids = {'root uuid': 'root_uuid',
                           'efi system partition uuid': None}
        result_msg = standby._message_format(msg, image_info,
                                             device, partition_uuids)
        expected_msg = ('image (fake_id) already present on device '
                        '/dev/fake root_uuid=root_uuid')
        self.assertEqual(expected_msg, result_msg)

    def test__message_format_partition_uefi_netboot(self):
        image_info = _build_fake_partition_image_info()
        image_info['deploy_boot_mode'] = 'uefi'
        image_info['boot_option'] = 'netboot'
        msg = ('image ({}) already present on device {} ')
        device = '/dev/fake'
        partition_uuids = {'root uuid': 'root_uuid',
                           'efi system partition uuid': None}
        result_msg = standby._message_format(msg, image_info,
                                             device, partition_uuids)
        expected_msg = ('image (fake_id) already present on device '
                        '/dev/fake root_uuid=root_uuid')
        self.assertEqual(expected_msg, result_msg)

    def test__message_format_partition_uefi_localboot(self):
        image_info = _build_fake_partition_image_info()
        image_info['deploy_boot_mode'] = 'uefi'
        image_info['boot_option'] = 'local'
        msg = ('image ({}) already present on device {} ')
        device = '/dev/fake'
        partition_uuids = {'root uuid': 'root_uuid',
                           'efi system partition uuid': 'efi_id'}
        result_msg = standby._message_format(msg, image_info,
                                             device, partition_uuids)
        expected_msg = ('image (fake_id) already present on device '
                        '/dev/fake root_uuid=root_uuid '
                        'efi_system_partition_uuid=efi_id')
        self.assertEqual(expected_msg, result_msg)


class TestImageDownload(test_base.BaseTestCase):

    @mock.patch('hashlib.md5', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image(self, requests_mock, md5_mock):
        content = ['SpongeBob', 'SquarePants']
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = content

        image_info = _build_fake_image_info()
        md5_mock.return_value.hexdigest.return_value = image_info['checksum']
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={})
        self.assertEqual(image_info['checksum'], image_download.md5sum())

    @mock.patch('time.time', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image_fail(self, requests_mock, time_mock):
        response = requests_mock.return_value
        response.status_code = 401
        response.text = 'Unauthorized'
        time_mock.return_value = 0.0
        image_info = _build_fake_image_info()
        msg = ('Error downloading image: Download of image id fake_id failed: '
               'URL: http://example.org; time: 0.0 seconds. Error: '
               'Received status code 401 from http://example.org, expected '
               '200. Response body: Unauthorized')
        self.assertRaisesRegex(errors.ImageDownloadError, msg,
                               standby.ImageDownload, image_info)
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={})

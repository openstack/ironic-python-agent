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
import tempfile
import time
from unittest import mock

from ironic_lib import exception
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import units
import requests

from ironic_python_agent import errors
from ironic_python_agent.extensions import standby
from ironic_python_agent import hardware
from ironic_python_agent import partition_utils
from ironic_python_agent.tests.unit import base
from ironic_python_agent import utils


CONF = cfg.CONF


def _virtual_size(size=1):
    """Convert a virtual size in mb to bytes"""
    return (size * units.Mi) + 1 - units.Mi


def _build_fake_image_info(url='http://example.org'):
    return {
        'id': 'fake_id',
        'node_uuid': '1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
        'urls': [url],
        'image_type': 'whole-disk-image',
        'os_hash_algo': 'sha256',
        'os_hash_value': 'fake-checksum',
        'disk_format': 'qcow2'
    }


def _build_fake_partition_image_info():
    return {
        'id': 'fake_id',
        'urls': [
            'http://example.org',
        ],
        'node_uuid': 'node_uuid',
        'root_mb': '10',
        'swap_mb': '10',
        'ephemeral_mb': '10',
        'ephemeral_format': 'abc',
        'preserve_ephemeral': 'False',
        'image_type': 'partition',
        'disk_label': 'msdos',
        'deploy_boot_mode': 'bios',
        'os_hash_algo': 'sha256',
        'os_hash_value': 'fake-checksum',
        'disk_format': 'qcow2'
    }


class TestStandbyExtension(base.IronicAgentTest):
    def setUp(self):
        super(TestStandbyExtension, self).setUp()
        self.agent_extension = standby.StandbyExtension()
        self.fake_cpu = hardware.CPU(model_name='fuzzypickles',
                                     frequency=1024,
                                     count=1,
                                     architecture='generic',
                                     flags='')
        with mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                        autospec=True):
            hardware.cache_node(
                {'uuid': '1-2-3-4',
                 'instance_info': {}})

    def test_validate_image_info_success(self):
        standby._validate_image_info(None, _build_fake_image_info())

    def test_validate_image_info_success_with_new_hash_fields(self):
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'md5'
        image_info['os_hash_value'] = 'fake-checksum'
        standby._validate_image_info(None, image_info)

    def test_validate_image_info_success_without_md5(self):
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'fake-checksum'
        standby._validate_image_info(None, image_info)

    def test_validate_image_info_success_ignore_none_md5(self):
        image_info = _build_fake_image_info()
        image_info['checksum'] = None
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'fake-checksum'
        standby._validate_image_info(None, image_info)

    def test_validate_image_info_legacy_md5_checksum_enabled(self):
        image_info = _build_fake_image_info()
        CONF.set_override('md5_enabled', True)
        image_info['checksum'] = 'fake-checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        standby._validate_image_info(None, image_info)

    def test_validate_image_info_url(self):
        image_info = _build_fake_image_info()
        image_info['checksum'] = 'https://fake.url'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        standby._validate_image_info(None, image_info)

    def test_validate_image_info_sha256(self):
        image_info = _build_fake_image_info()
        image_info['checksum'] = 'a' * 64
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        standby._validate_image_info(None, image_info)

    def test_validate_image_info_legacy_md5_checksum(self):
        CONF.set_override('md5_enabled', False)
        image_info = _build_fake_image_info()
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        image_info['checksum'] = 'fake-checksum'
        self.assertRaisesRegex(errors.InvalidCommandParamsError,
                               'Image checksum is not',
                               standby._validate_image_info,
                               None,
                               image_info)

    def test_validate_image_info_missing_field(self):
        for field in ['id', 'urls', 'os_hash_value']:
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

    def test_validate_image_info_no_hash_value(self):
        invalid_info = _build_fake_image_info()
        invalid_info['os_hash_algo'] = 'sha512'

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_validate_image_info_no_hash_algo(self):
        invalid_info = _build_fake_image_info()
        invalid_info['os_hash_value'] = 'fake-checksum'

        self.assertRaises(errors.InvalidCommandParamsError,
                          standby._validate_image_info,
                          invalid_info)

    def test_image_location(self):
        image_info = _build_fake_image_info()
        location = standby._image_location(image_info)
        # Can't hardcode /tmp here, each test is running in an isolated
        # tempdir
        expected_loc = os.path.join(tempfile.gettempdir(), 'fake_id')
        self.assertEqual(expected_loc, location)

    def test_verify_basic_auth_creds(self):
        image_info = _build_fake_image_info()
        self.assertIsNone(standby._verify_basic_auth_creds("SpongeBob",
                                                           "SquarePants",
                                                           image_info['id']))

    def test_gen_auth_from_image_info_user_pass_success(self):
        image_info = _build_fake_image_info()
        image_info['image_server_auth_strategy'] = 'http_basic'
        image_info['image_server_user'] = 'SpongeBob'
        image_info['image_server_password'] = 'SquarePants'
        exp_auth = requests.auth.HTTPBasicAuth('SpongeBob', 'SquarePants')
        return_auth = \
            standby._gen_auth_from_image_info_user_pass(image_info,
                                                        image_info['id'])
        self.assertEqual(exp_auth, return_auth)

    def test_gen_auth_from_image_info_user_pass_none(self):
        image_info = _build_fake_image_info()
        image_info['image_server_auth_strategy'] = ''
        image_info['image_server_user'] = 'SpongeBob'
        image_info['image_server_password'] = 'SquarePants'
        return_auth = \
            standby._gen_auth_from_image_info_user_pass(image_info,
                                                        image_info['id'])
        self.assertIsNone(return_auth)

    def test_gen_auth_from_oslo_conf_user_pass_success(self):
        image_info = _build_fake_image_info()
        CONF.set_override('image_server_auth_strategy', 'http_basic')
        CONF.set_override('image_server_password', 'SpongeBob')
        CONF.set_override('image_server_user', 'SquarePants')
        correct_auth = \
            requests.auth.HTTPBasicAuth(CONF['image_server_user'],
                                        CONF['image_server_password'])
        return_auth = \
            standby._gen_auth_from_oslo_conf_user_pass(image_info['id'])
        self.assertEqual(correct_auth, return_auth)

    def test_gen_auth_from_oslo_conf_user_pass_none(self):
        image_info = _build_fake_image_info()
        CONF.set_override('image_server_auth_strategy', 'noauth')
        CONF.set_override('image_server_password', 'SpongeBob')
        CONF.set_override('image_server_user', 'SquarePants')
        return_auth = \
            standby._gen_auth_from_oslo_conf_user_pass(image_info['id'])
        self.assertIsNone(return_auth)

    def test_verify_basic_auth_creds_empty_user(self):
        image_info = _build_fake_image_info()
        self.assertRaises(errors.ImageDownloadError,
                          standby._verify_basic_auth_creds,
                          "",
                          "SquarePants",
                          image_info['id'])

    def test_verify_basic_auth_creds_empty_password(self):
        image_info = _build_fake_image_info()
        self.assertRaises(errors.ImageDownloadError,
                          standby._verify_basic_auth_creds,
                          "SpongeBob",
                          "",
                          image_info['id'])

    def test_verify_basic_auth_creds_none_user(self):
        image_info = _build_fake_image_info()
        self.assertRaises(errors.ImageDownloadError,
                          standby._verify_basic_auth_creds,
                          None,
                          "SquarePants",
                          image_info['id'])

    def test_verify_basic_auth_creds_none_password(self):
        image_info = _build_fake_image_info()
        self.assertRaises(errors.ImageDownloadError,
                          standby._verify_basic_auth_creds,
                          "SpongeBob",
                          None,
                          image_info['id'])

    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.fix_gpt_partition',
                autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.trigger_device_rescan',
                autospec=True)
    @mock.patch('ironic_python_agent.qemu_img.convert_image', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.udev_settle', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.destroy_disk_metadata',
                autospec=True)
    def test_write_image(self, wipe_mock, udev_mock, convert_mock,
                         rescan_mock, fix_gpt_mock, validate_mock):
        image_info = _build_fake_image_info()
        device = '/dev/sda'
        source_format = image_info['disk_format']
        validate_mock.return_value = (source_format, 0)
        location = standby._image_location(image_info)

        standby._write_image(image_info, device)

        convert_mock.assert_called_once_with(location, device,
                                             out_format='host_device',
                                             cache='directsync',
                                             out_of_order=True,
                                             sparse_size='0',
                                             source_format=source_format)
        validate_mock.assert_called_once_with(location, source_format)
        wipe_mock.assert_called_once_with(device, '')
        udev_mock.assert_called_once_with()
        rescan_mock.assert_called_once_with(device)
        fix_gpt_mock.assert_called_once_with(device, node_uuid=None)

    @mock.patch('ironic_python_agent.disk_utils.fix_gpt_partition',
                autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.trigger_device_rescan',
                autospec=True)
    @mock.patch('ironic_python_agent.qemu_img.convert_image', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.udev_settle', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.destroy_disk_metadata',
                autospec=True)
    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    def test_write_image_gpt_fails(self, validate_mock, wipe_mock, udev_mock,
                                   convert_mock, rescan_mock, fix_gpt_mock):
        device = '/dev/sda'
        image_info = _build_fake_image_info()
        validate_mock.return_value = (image_info['disk_format'], 0)

        fix_gpt_mock.side_effect = exception.InstanceDeployFailure
        standby._write_image(image_info, device)

    @mock.patch('ironic_python_agent.qemu_img.convert_image', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.udev_settle', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.destroy_disk_metadata',
                autospec=True)
    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    def test_write_image_fails(self, validate_mock, wipe_mock, udev_mock,
                               convert_mock):
        image_info = _build_fake_image_info()
        validate_mock.return_value = (image_info['disk_format'], 0)
        device = '/dev/sda'
        convert_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(errors.ImageWriteError,
                          standby._write_image,
                          image_info,
                          device)

    @mock.patch.object(utils, 'get_node_boot_mode', lambda self: 'bios')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    @mock.patch.object(partition_utils, 'work_on_disk', autospec=True)
    def test_write_partition_image_exception(self, work_on_disk_mock,
                                             validate_mock,
                                             execute_mock, open_mock,
                                             dispatch_mock):
        image_info = _build_fake_partition_image_info()
        device = '/dev/sda'
        root_mb = image_info['root_mb']
        swap_mb = image_info['swap_mb']
        ephemeral_mb = image_info['ephemeral_mb']
        ephemeral_format = image_info['ephemeral_format']
        node_uuid = image_info['node_uuid']
        pr_ep = image_info['preserve_ephemeral']
        boot_mode = image_info['deploy_boot_mode']
        disk_label = image_info['disk_label']
        source_format = image_info['disk_format']
        cpu_arch = self.fake_cpu.architecture

        image_path = standby._image_location(image_info)

        validate_mock.return_value = (image_info['disk_format'],
                                      _virtual_size(1))
        dispatch_mock.return_value = self.fake_cpu
        exc = errors.ImageWriteError
        Exception_returned = processutils.ProcessExecutionError
        work_on_disk_mock.side_effect = Exception_returned

        self.assertRaises(exc, standby._write_image, image_info,
                          device, 'configdrive')
        validate_mock.assert_called_once_with(image_path, source_format)
        work_on_disk_mock.assert_called_once_with(device, root_mb, swap_mb,
                                                  ephemeral_mb,
                                                  ephemeral_format,
                                                  image_path,
                                                  node_uuid,
                                                  configdrive='configdrive',
                                                  preserve_ephemeral=pr_ep,
                                                  boot_mode=boot_mode,
                                                  disk_label=disk_label,
                                                  cpu_arch=cpu_arch,
                                                  source_format=source_format,
                                                  is_raw=False)

    @mock.patch.object(utils, 'get_node_boot_mode', lambda self: 'bios')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    @mock.patch.object(partition_utils, 'work_on_disk', autospec=True)
    def test_write_partition_image_no_node_uuid(self, work_on_disk_mock,
                                                validate_mock,
                                                execute_mock, open_mock,
                                                dispatch_mock):
        image_info = _build_fake_partition_image_info()
        image_info['node_uuid'] = None
        device = '/dev/sda'
        root_mb = image_info['root_mb']
        swap_mb = image_info['swap_mb']
        ephemeral_mb = image_info['ephemeral_mb']
        ephemeral_format = image_info['ephemeral_format']
        node_uuid = image_info['node_uuid']
        pr_ep = image_info['preserve_ephemeral']
        boot_mode = image_info['deploy_boot_mode']
        disk_label = image_info['disk_label']
        source_format = image_info['disk_format']
        cpu_arch = self.fake_cpu.architecture

        image_path = standby._image_location(image_info)

        validate_mock.return_value = (source_format, _virtual_size(1))
        dispatch_mock.return_value = self.fake_cpu
        uuids = {'root uuid': 'root_uuid'}
        expected_uuid = {'root uuid': 'root_uuid'}
        work_on_disk_mock.return_value = uuids

        standby._write_image(image_info, device, 'configdrive')
        validate_mock.assert_called_once_with(image_path, source_format)
        work_on_disk_mock.assert_called_once_with(device, root_mb, swap_mb,
                                                  ephemeral_mb,
                                                  ephemeral_format,
                                                  image_path,
                                                  node_uuid,
                                                  configdrive='configdrive',
                                                  preserve_ephemeral=pr_ep,
                                                  boot_mode=boot_mode,
                                                  disk_label=disk_label,
                                                  cpu_arch=cpu_arch,
                                                  source_format=source_format,
                                                  is_raw=False)

        self.assertEqual(expected_uuid, work_on_disk_mock.return_value)
        self.assertIsNone(node_uuid)

    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    @mock.patch.object(partition_utils, 'work_on_disk', autospec=True)
    def test_write_partition_image_exception_image_mb(self,
                                                      work_on_disk_mock,
                                                      validate_mock,
                                                      execute_mock,
                                                      open_mock,
                                                      dispatch_mock):
        dispatch_mock.return_value = self.fake_cpu
        image_info = _build_fake_partition_image_info()
        device = '/dev/sda'
        source_format = image_info['disk_format']
        image_path = standby._image_location(image_info)

        validate_mock.return_value = (source_format, _virtual_size(20))

        exc = errors.InvalidCommandParamsError

        self.assertRaises(exc, standby._write_image, image_info,
                          device)
        validate_mock.assert_called_once_with(image_path, source_format)
        self.assertFalse(work_on_disk_mock.called)

    @mock.patch.object(utils, 'get_node_boot_mode', lambda self: 'bios')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch.object(partition_utils, 'work_on_disk', autospec=True)
    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    def test_write_partition_image(self, validate_mock, work_on_disk_mock,
                                   execute_mock, open_mock, dispatch_mock):
        image_info = _build_fake_partition_image_info()
        device = '/dev/sda'
        root_mb = image_info['root_mb']
        swap_mb = image_info['swap_mb']
        ephemeral_mb = image_info['ephemeral_mb']
        ephemeral_format = image_info['ephemeral_format']
        node_uuid = image_info['node_uuid']
        pr_ep = image_info['preserve_ephemeral']
        boot_mode = image_info['deploy_boot_mode']
        disk_label = image_info['disk_label']
        source_format = image_info['disk_format']
        cpu_arch = self.fake_cpu.architecture

        image_path = standby._image_location(image_info)
        uuids = {'root uuid': 'root_uuid'}
        expected_uuid = {'root uuid': 'root_uuid'}
        validate_mock.return_value = (source_format, _virtual_size(1))
        dispatch_mock.return_value = self.fake_cpu
        work_on_disk_mock.return_value = uuids

        standby._write_image(image_info, device, 'configdrive')
        validate_mock.assert_called_once_with(image_path, source_format)
        work_on_disk_mock.assert_called_once_with(device, root_mb, swap_mb,
                                                  ephemeral_mb,
                                                  ephemeral_format,
                                                  image_path,
                                                  node_uuid,
                                                  configdrive='configdrive',
                                                  preserve_ephemeral=pr_ep,
                                                  boot_mode=boot_mode,
                                                  disk_label=disk_label,
                                                  cpu_arch=cpu_arch,
                                                  source_format=source_format,
                                                  is_raw=False)

        self.assertEqual(expected_uuid, work_on_disk_mock.return_value)

    @mock.patch('ironic_python_agent.extensions.standby.LOG', autospec=True)
    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image(self, requests_mock, open_mock, hash_mock,
                            log_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        response.headers = {}
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']

        standby._download_image(image_info)
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={},
                                              timeout=60)
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)
        log_mock_calls = [
            mock.call.info('Attempting to download image from %s',
                           'http://example.org'),
            mock.call.debug('Verifying image at %(image_location)s against '
                            '%(algo_name)s checksum %(checksum)s',
                            {'image_location': mock.ANY,
                             'algo_name': mock.ANY,
                             'checksum': 'fake-checksum'}),
            mock.call.info('Image downloaded from %(image_location)s in '
                           '%(totaltime)s seconds. Transferred %(size)s '
                           'bytes. Server originally reported: %(reported)s.',
                           {'image_location': mock.ANY,
                            'totaltime': mock.ANY,
                            'size': 11,
                            'reported': None}),
        ]
        log_mock.assert_has_calls(log_mock_calls)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    @mock.patch.dict(os.environ, {})
    def test_download_image_proxy(
            self, requests_mock, open_mock, hash_mock):
        image_info = _build_fake_image_info()
        proxies = {'http': 'http://a.b.com',
                   'https': 'https://secure.a.b.com'}
        no_proxy = '.example.org,.b.com'
        image_info['proxies'] = proxies
        image_info['no_proxy'] = no_proxy
        image_info['os_hash_value'] = 'fake-checksum'
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = 'fake-checksum'

        standby._download_image(image_info)
        self.assertEqual(no_proxy, os.environ['no_proxy'])
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies=proxies,
                                              timeout=60)
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)
        hash_mock.assert_has_calls([
            mock.call('sha256'),
            mock.call().update(b'some'),
            mock.call().update(b'content'),
            mock.call().hexdigest()])

    @mock.patch('requests.get', autospec=True)
    def test_download_image_bad_status(self, requests_mock):
        self.config(image_download_connection_retry_interval=0)
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 404
        self.assertRaises(errors.ImageDownloadError,
                          standby._download_image,
                          image_info)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image_basic_auth_conf_success(self, requests_mock,
                                                    open_mock, hash_mock):
        image_info = _build_fake_image_info()
        CONF.set_override('image_server_auth_strategy', 'http_basic')
        CONF.set_override('image_server_password', 'SpongeBob')
        CONF.set_override('image_server_user', 'SquarePants')
        user = CONF.image_server_user
        password = CONF.image_server_password
        correct_auth = requests.auth.HTTPBasicAuth(user, password)
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']

        standby._download_image(image_info)
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={},
                                              timeout=60, auth=correct_auth)
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image_basic_auth_image_info_success(self,
                                                          requests_mock,
                                                          open_mock,
                                                          hash_mock):
        image_info = _build_fake_image_info()
        image_info['image_server_auth_strategy'] = 'http_basic'
        image_info['image_server_password'] = 'SpongeBob'
        image_info['image_server_user'] = 'SquarePants'
        user = image_info['image_server_user']
        password = image_info['image_server_password']
        correct_auth = requests.auth.HTTPBasicAuth(user, password)
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']

        standby._download_image(image_info)
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={},
                                              timeout=60, auth=correct_auth)
        write = file_mock.write
        write.assert_any_call('some')
        write.assert_any_call('content')
        self.assertEqual(2, write.call_count)

    def test_download_image_bad_basic_auth_conf_credential(self):
        self.config(image_download_connection_retry_interval=0)
        image_info = _build_fake_image_info()
        CONF.set_override('image_server_auth_strategy', 'http_basic')
        self.assertRaises(errors.ImageDownloadError,
                          standby._download_image,
                          image_info)

    def test_download_image_bad_basic_auth_image_info_credential(self):
        self.config(image_download_connection_retry_interval=0)
        image_info = _build_fake_image_info()
        image_info['image_server_auth_strategy'] = 'http_basic'
        self.assertRaises(errors.ImageDownloadError,
                          standby._download_image,
                          image_info)

    def test_download_image_bad_basic_auth_mixed_credential(self):
        self.config(image_download_connection_retry_interval=0)
        image_info = _build_fake_image_info()
        image_info['image_server_auth_strategy'] = 'http_basic'
        CONF.set_override('image_server_password', 'SpongeBob')
        CONF.set_override('image_server_user', 'SquarePants')
        self.assertRaises(errors.ImageDownloadError,
                          standby._download_image,
                          image_info)

    def test_download_image_bad_basic_auth_mixed_credential_second(self):
        self.config(image_download_connection_retry_interval=0)
        image_info = _build_fake_image_info()
        CONF.set_override('image_server_auth_strategy', 'http_basic')
        image_info['image_server_password'] = 'SpongeBob'
        image_info['image_server_user'] = 'SquarePants'
        self.assertRaises(errors.ImageDownloadError,
                          standby._download_image,
                          image_info)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_download_image_verify_fails(self, requests_mock, open_mock,
                                         hash_mock):
        # Set the config to 0 retries, so we don't retry in this case
        # and cause the test download to loop multiple times.
        self.config(image_download_connection_retries=0)
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = 'invalid-checksum'
        self.assertRaises(errors.ImageChecksumError,
                          standby._download_image,
                          image_info)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_success(self, requests_mock, open_mock, hash_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']
        image_location = '/foo/bar'
        image_download = standby.ImageDownload(image_info)
        image_download.verify_image(image_location)
        self.assertEqual(0, image_download.bytes_transferred)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_success_with_new_hash_fields(self, requests_mock,
                                                       open_mock,
                                                       hashlib_mock):
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'fake-sha512-value'
        response = requests_mock.return_value
        response.status_code = 200
        hexdigest_mock = hashlib_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']
        image_location = '/foo/bar'
        image_download = standby.ImageDownload(image_info)
        image_download.verify_image(image_location)
        hashlib_mock.assert_called_with('sha512')

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_success_without_md5(self, requests_mock,
                                              open_mock, hashlib_mock):
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'fake-sha512-value'
        response = requests_mock.return_value
        response.status_code = 200
        hexdigest_mock = hashlib_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']
        image_location = '/foo/bar'
        image_download = standby.ImageDownload(image_info)
        image_download.verify_image(image_location)
        hashlib_mock.assert_called_with('sha512')

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_success_with_md5_fallback(self, requests_mock,
                                                    open_mock, hash_mock):
        CONF.set_override('md5_enabled', True)
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'algo-beyond-milky-way'
        image_info['os_hash_value'] = 'mysterious-alien-codes'
        image_info['checksum'] = 'd41d8cd98f00b204e9800998ecf8427e'
        response = requests_mock.return_value
        response.status_code = 200
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['checksum']
        image_location = '/foo/bar'
        image_download = standby.ImageDownload(image_info)
        image_download.verify_image(image_location)
        # NOTE(TheJulia): This is the one test which falls all the
        # way back to md5 as the default, legacy logic because it
        # got bad input to start with.
        hash_mock.assert_has_calls([
            mock.call('md5'),
            mock.call().__bool__(),
            mock.call().hexdigest()])

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_fails_if_unknown_is_used(self, requests_mock,
                                                   open_mock, hash_mock):
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'algo-beyond-milky-way'
        image_info['os_hash_value'] = 'mysterious-alien-codes'
        self.assertRaisesRegex(
            errors.RESTError,
            'An error occurred: Unable to verify image fake_id with '
            'available checksums.',
            standby.ImageDownload,
            image_info)
        hash_mock.assert_not_called()

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_failure_with_new_hash_fields(self, requests_mock,
                                                       open_mock,
                                                       hashlib_mock):
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'fake-sha512-value'
        response = requests_mock.return_value
        response.status_code = 200
        image_download = standby.ImageDownload(image_info)
        image_location = '/foo/bar'
        hexdigest_mock = hashlib_mock.return_value.hexdigest
        hexdigest_mock.return_value = 'invalid-checksum'
        self.assertRaises(errors.ImageChecksumError,
                          image_download.verify_image,
                          image_location)
        hashlib_mock.assert_called_with('sha512')

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_failure(self, requests_mock, open_mock, hash_mock):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        image_download = standby.ImageDownload(image_info)
        image_location = '/foo/bar'
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = 'invalid-checksum'
        self.assertRaises(errors.ImageChecksumError,
                          image_download.verify_image,
                          image_location)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_verify_image_failure_without_fallback(self, requests_mock,
                                                   open_mock, hashlib_mock):
        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'unsupported-algorithm'
        image_info['os_hash_value'] = 'fake-value'
        response = requests_mock.return_value
        response.status_code = 200
        self.assertRaisesRegex(errors.RESTError,
                               'Unable to verify image.*'
                               'unsupported-algorithm',
                               standby.ImageDownload,
                               image_info)

    @mock.patch('ironic_python_agent.disk_utils.get_disk_identifier',
                lambda dev: 'ROOT')
    @mock.patch('ironic_lib.utils.execute', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.list_partitions',
                autospec=True)
    @mock.patch.object(partition_utils, 'create_config_drive_partition',
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
                           configdrive_copy_mock,
                           list_part_mock,
                           execute_mock):
        image_info = _build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None
        list_part_mock.return_value = [mock.MagicMock()]

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive='configdrive_data'
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager',
                                           'configdrive_data')
        dispatch_mock.assert_called_once_with('get_os_install_device',
                                              permit_refresh=True)
        configdrive_copy_mock.assert_called_once_with(image_info['node_uuid'],
                                                      'manager',
                                                      'configdrive_data')

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('prepare_image: image ({}) written to device {} '
                      'root_uuid=ROOT').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])
        list_part_mock.assert_called_with('manager')
        execute_mock.assert_called_with('partprobe', 'manager',
                                        attempts=mock.ANY)
        self.assertEqual({'root uuid': 'ROOT'},
                         self.agent_extension.partition_uuids)

    @mock.patch('ironic_lib.utils.execute', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.list_partitions',
                autospec=True)
    @mock.patch.object(partition_utils, 'create_config_drive_partition',
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
                                     configdrive_copy_mock,
                                     list_part_mock,
                                     execute_mock):
        image_info = _build_fake_partition_image_info()
        download_mock.return_value = None
        write_mock.return_value = {'root uuid': 'root_uuid'}
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None
        list_part_mock.return_value = [mock.MagicMock()]

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive='configdrive_data'
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager',
                                           'configdrive_data')
        dispatch_mock.assert_called_once_with('get_os_install_device',
                                              permit_refresh=True)
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
        list_part_mock.assert_called_with('manager')
        execute_mock.assert_called_with('partprobe', 'manager',
                                        attempts=mock.ANY)
        self.assertEqual({'root uuid': 'root_uuid'},
                         self.agent_extension.partition_uuids)

    @mock.patch('ironic_python_agent.disk_utils.get_disk_identifier',
                lambda dev: 'ROOT')
    @mock.patch('ironic_lib.utils.execute', autospec=True)
    @mock.patch.object(partition_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.list_partitions',
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
                                          list_part_mock,
                                          configdrive_copy_mock,
                                          execute_mock):
        image_info = _build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None
        list_part_mock.return_value = [mock.MagicMock()]

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive=None
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager', None)
        dispatch_mock.assert_called_once_with('get_os_install_device',
                                              permit_refresh=True)

        self.assertEqual(0, configdrive_copy_mock.call_count)
        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('prepare_image: image ({}) written to device {} '
                      'root_uuid=ROOT').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])

    @mock.patch('ironic_python_agent.disk_utils.get_disk_identifier',
                lambda dev: 'ROOT')
    @mock.patch.object(partition_utils, 'work_on_disk', autospec=True)
    @mock.patch.object(partition_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.list_partitions',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_prepare_image_bad_partition(self,
                                         download_mock,
                                         write_mock,
                                         dispatch_mock,
                                         list_part_mock,
                                         configdrive_copy_mock,
                                         work_on_disk_mock):
        list_part_mock.side_effect = processutils.ProcessExecutionError
        image_info = _build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None
        work_on_disk_mock.return_value = {
            'root uuid': 'a318821b-2a60-40e5-a011-7ac07fce342b',
            'partitions': {
                'root': '/dev/foo-part1',
            }
        }

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive=None
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager', None)
        dispatch_mock.assert_called_once_with('get_os_install_device',
                                              permit_refresh=True)

        self.assertFalse(configdrive_copy_mock.called)
        self.assertEqual('FAILED', async_result.command_status)

    @mock.patch('ironic_python_agent.disk_utils.get_disk_identifier',
                side_effect=OSError, autospec=True)
    @mock.patch('ironic_lib.utils.execute',
                autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.list_partitions',
                autospec=True)
    @mock.patch.object(partition_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_prepare_image_no_hexdump(self,
                                      download_mock,
                                      write_mock,
                                      dispatch_mock,
                                      configdrive_copy_mock,
                                      list_part_mock,
                                      execute_mock,
                                      disk_id_mock):
        image_info = _build_fake_image_info()
        download_mock.return_value = None
        write_mock.return_value = None
        dispatch_mock.return_value = 'manager'
        configdrive_copy_mock.return_value = None
        list_part_mock.return_value = [mock.MagicMock()]

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive='configdrive_data'
        )
        async_result.join()

        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, 'manager',
                                           'configdrive_data')
        dispatch_mock.assert_called_once_with('get_os_install_device',
                                              permit_refresh=True)
        configdrive_copy_mock.assert_called_once_with(image_info['node_uuid'],
                                                      'manager',
                                                      'configdrive_data')

        self.assertEqual('SUCCEEDED', async_result.command_status)
        self.assertIn('result', async_result.command_result)
        cmd_result = ('prepare_image: image ({}) written to device {} '
                      'root_uuid=None').format(image_info['id'], 'manager')
        self.assertEqual(cmd_result, async_result.command_result['result'])
        list_part_mock.assert_called_with('manager')
        execute_mock.assert_called_with('partprobe', 'manager',
                                        attempts=mock.ANY)
        self.assertEqual({}, self.agent_extension.partition_uuids)

    @mock.patch('ironic_lib.utils.execute', mock.Mock())
    @mock.patch('ironic_python_agent.disk_utils.list_partitions',
                lambda _dev: [mock.Mock()])
    @mock.patch('ironic_python_agent.disk_utils.get_disk_identifier',
                lambda dev: 'ROOT')
    @mock.patch.object(partition_utils, 'work_on_disk', autospec=True)
    @mock.patch.object(partition_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby.StandbyExtension'
                '._cache_and_write_image', autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby.StandbyExtension'
                '._stream_raw_image_onto_device', autospec=True)
    def _test_prepare_image_raw(self, image_info, stream_mock,
                                cache_write_mock, dispatch_mock,
                                configdrive_copy_mock, work_on_disk_mock,
                                partition=False):
        # Calls get_cpus().architecture with partition images
        dispatch_mock.side_effect = ['/dev/foo', self.fake_cpu]
        configdrive_copy_mock.return_value = None
        work_on_disk_mock.return_value = {
            'root uuid': 'a318821b-2a60-40e5-a011-7ac07fce342b',
            'partitions': {
                'root': '/dev/foo-part1',
            }
        }
        if partition:
            expected_device = '/dev/foo-part1'
        else:
            expected_device = '/dev/foo'

        async_result = self.agent_extension.prepare_image(
            image_info=image_info,
            configdrive=None
        )
        async_result.join()

        dispatch_mock.assert_any_call('get_os_install_device',
                                      permit_refresh=True)
        self.assertFalse(configdrive_copy_mock.called)

        # Assert we've streamed the image or not
        if image_info['stream_raw_images']:
            stream_mock.assert_called_once_with(mock.ANY, image_info,
                                                expected_device)
            self.assertFalse(cache_write_mock.called)
            self.assertIs(partition, work_on_disk_mock.called)
        else:
            cache_write_mock.assert_called_once_with(mock.ANY, image_info,
                                                     '/dev/foo', None)
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

    def test_prepare_partition_image_raw_stream_true(self):
        image_info = _build_fake_partition_image_info()
        image_info['disk_format'] = 'raw'
        image_info['stream_raw_images'] = True
        self._test_prepare_image_raw(image_info, partition=True)
        self.assertEqual({'root uuid': 'a318821b-2a60-40e5-a011-7ac07fce342b',
                          'partitions': {'root': '/dev/foo-part1'}},
                         self.agent_extension.partition_uuids)

    def test_prepare_partition_image_raw_and_stream_false(self):
        image_info = _build_fake_partition_image_info()
        image_info['disk_format'] = 'raw'
        image_info['stream_raw_images'] = False
        self._test_prepare_image_raw(image_info, partition=True)

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
                 mock.call('poweroff', use_standard_locale=True)]
        execute_mock.assert_has_calls(calls)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_shutdown_command_valid_poweroff_sysrq(self, execute_mock):
        execute_mock.side_effect = [
            ('', ''), ('', ''),
            processutils.ProcessExecutionError(''),
            ('', '')]

        self.agent_extension._run_shutdown_command('poweroff')
        calls = [mock.call('hwclock', '-v', '--systohc'),
                 mock.call('sync'),
                 mock.call('poweroff', use_standard_locale=True),
                 mock.call("echo o > /proc/sysrq-trigger", shell=True)]
        execute_mock.assert_has_calls(calls)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_shutdown_command_valid_reboot_sysrq(self, execute_mock):
        execute_mock.side_effect = [('', ''), ('', ''), ('',
                                    'Running in chroot, ignoring request.'),
                                    ('', '')]

        self.agent_extension._run_shutdown_command('reboot')
        calls = [mock.call('sync'),
                 mock.call('reboot', use_standard_locale=True),
                 mock.call("echo b > /proc/sysrq-trigger", shell=True)]
        execute_mock.assert_has_calls(calls)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_run_image(self, execute_mock):
        execute_mock.return_value = ('', '')

        success_result = self.agent_extension.run_image()
        success_result.join()
        calls = [mock.call('sync'),
                 mock.call('reboot', use_standard_locale=True)]
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
                 mock.call('poweroff', use_standard_locale=True)]
        execute_mock.assert_has_calls(calls)
        self.assertEqual('SUCCEEDED', success_result.command_status)

        execute_mock.reset_mock()
        execute_mock.return_value = ('', '')
        execute_mock.side_effect = processutils.ProcessExecutionError

        failed_result = self.agent_extension.power_off()
        failed_result.join()

        execute_mock.assert_any_call('sync')
        self.assertEqual('FAILED', failed_result.command_status)

    @mock.patch('ironic_python_agent.utils.determine_time_method',
                autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_power_off_with_ntp_server(self, execute_mock, mock_timemethod):
        self.config(fail_if_clock_not_set=False)
        self.config(ntp_server='192.168.1.1')
        execute_mock.return_value = ('', '')
        mock_timemethod.return_value = 'ntpdate'

        success_result = self.agent_extension.power_off()
        success_result.join()

        calls = [mock.call('ntpdate', '192.168.1.1'),
                 mock.call('hwclock', '-v', '--systohc'),
                 mock.call('sync'),
                 mock.call('poweroff', use_standard_locale=True)]
        execute_mock.assert_has_calls(calls)
        self.assertEqual('SUCCEEDED', success_result.command_status)

        self.config(fail_if_clock_not_set=True)
        execute_mock.reset_mock()
        execute_mock.return_value = ('', '')
        execute_mock.side_effect = processutils.ProcessExecutionError

        failed_result = self.agent_extension.power_off()
        failed_result.join()

        execute_mock.assert_any_call('ntpdate', '192.168.1.1')
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
        write_mock.assert_called_once_with(image_info, device, None)

    @mock.patch('ironic_python_agent.extensions.standby._write_image',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.standby._download_image',
                autospec=True)
    def test_cache_and_write_image_configdirve(self, download_mock,
                                               write_mock):
        image_info = _build_fake_image_info()
        device = '/dev/foo'
        self.agent_extension._cache_and_write_image(image_info, device,
                                                    'configdrive_data')
        download_mock.assert_called_once_with(image_info)
        write_mock.assert_called_once_with(image_info, device,
                                           'configdrive_data')

    @mock.patch('ironic_python_agent.extensions.standby.LOG', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.block_uuid', autospec=True)
    @mock.patch('ironic_python_agent.disk_utils.fix_gpt_partition',
                autospec=True)
    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_stream_raw_image_onto_device(self, requests_mock, open_mock,
                                          hash_mock, fix_gpt_mock,
                                          block_uuid_mock,
                                          mock_log):
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.headers = {'Content-Length': 11}
        response.status_code = 200
        response.iter_content.return_value = ['some', 'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']
        self.agent_extension.partition_uuids = {}

        block_uuid_mock.return_value = 'aaaabbbb'
        self.agent_extension._stream_raw_image_onto_device(image_info,
                                                           '/dev/foo')
        hash_mock.assert_has_calls([
            mock.call('sha256'),
            mock.call().update(b'some'),
            mock.call().update(b'content'),
            mock.call().hexdigest()])

        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={},
                                              timeout=60)
        expected_calls = [mock.call('some'), mock.call('content')]
        file_mock.write.assert_has_calls(expected_calls)
        fix_gpt_mock.assert_called_once_with('/dev/foo', node_uuid=None)
        block_uuid_mock.assert_called_once_with('/dev/foo')
        self.assertEqual(
            'aaaabbbb',
            self.agent_extension.partition_uuids['root uuid']
        )
        mock_log_calls = [
            mock.call.info('Attempting to download image from %s',
                           'http://example.org'),
            mock.call.debug('Verifying image at %(image_location)s '
                            'against %(algo_name)s checksum %(checksum)s',
                            {'image_location': '/dev/foo',
                             'algo_name': mock.ANY,
                             'checksum': 'fake-checksum'}),
            mock.call.info('Image streamed onto device %(device)s in '
                           '%(totaltime)s seconds for %(size)s bytes. '
                           'Server originally reported %(reported)s.',
                           {'device': '/dev/foo',
                            'totaltime': mock.ANY,
                            'size': 11,
                            'reported': 11}),
            mock.call.info('%(device)s UUID is now %(root_uuid)s',
                           {'device': '/dev/foo', 'root_uuid': 'aaaabbbb'})
        ]
        mock_log.assert_has_calls(mock_log_calls)

    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_stream_raw_image_onto_device_write_error(self, requests_mock,
                                                      open_mock, hash_mock):
        self.config(image_download_connection_timeout=1)
        self.config(image_download_connection_retry_interval=0)
        image_info = _build_fake_image_info()
        response = requests_mock.return_value
        response.status_code = 200
        response.headers = {}
        response.iter_content.return_value = [b'some', b'content']
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.write.side_effect = Exception('Surprise!!!1!')
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']

        self.assertRaises(errors.ImageDownloadError,
                          self.agent_extension._stream_raw_image_onto_device,
                          image_info, '/dev/foo')
        calls = [mock.call('http://example.org', cert=None, proxies={},
                           stream=True, timeout=1, verify=True),
                 mock.call().iter_content(mock.ANY),
                 mock.call('http://example.org', cert=None, proxies={},
                           stream=True, timeout=1, verify=True),
                 mock.call().iter_content(mock.ANY),
                 mock.call('http://example.org', cert=None, proxies={},
                           stream=True, timeout=1, verify=True),
                 mock.call().iter_content(mock.ANY)]
        requests_mock.assert_has_calls(calls)
        write_calls = [mock.call(b'some'),
                       mock.call(b'some'),
                       mock.call(b'some')]
        file_mock.write.assert_has_calls(write_calls)

    @mock.patch('ironic_python_agent.disk_utils.fix_gpt_partition',
                autospec=True)
    @mock.patch('hashlib.new', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('requests.get', autospec=True)
    def test_stream_raw_image_onto_device_socket_read_timeout(
            self, requests_mock, open_mock, hash_mock, fix_gpt_mock):

        class create_timeout(object):
            status_code = 200

            def __init__(self, url, stream, proxies, verify, cert, timeout):
                self.count = 0

            def __iter__(self):
                return self

            def __next__(self):
                if self.count:
                    time.sleep(0.1)
                    return None
                self.count += 1
                return b"meow"

            def iter_content(self, chunk_size):
                return self

            @property
            def headers(self):
                return {}

        self.config(image_download_connection_timeout=1)
        self.config(image_download_connection_retries=2)
        self.config(image_download_connection_retry_interval=0)
        image_info = _build_fake_image_info()
        file_mock = mock.Mock()
        open_mock.return_value.__enter__.return_value = file_mock
        file_mock.read.return_value = None
        hexdigest_mock = hash_mock.return_value.hexdigest
        hexdigest_mock.return_value = image_info['os_hash_value']
        requests_mock.side_effect = create_timeout
        self.assertRaisesRegex(
            errors.ImageDownloadError,
            'Timed out reading next chunk',
            self.agent_extension._stream_raw_image_onto_device,
            image_info,
            '/dev/foo')

        calls = [mock.call(image_info['urls'][0], cert=None, verify=True,
                           stream=True, proxies={}, timeout=1),
                 mock.call(image_info['urls'][0], cert=None, verify=True,
                           stream=True, proxies={}, timeout=1),
                 mock.call(image_info['urls'][0], cert=None, verify=True,
                           stream=True, proxies={}, timeout=1)]
        requests_mock.assert_has_calls(calls)

        write_calls = [mock.call(b'meow'),
                       mock.call(b'meow'),
                       mock.call(b'meow')]
        file_mock.write.assert_has_calls(write_calls)
        fix_gpt_mock.assert_not_called()

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

    def test__message_format_partition_uefi(self):
        image_info = _build_fake_partition_image_info()
        image_info['deploy_boot_mode'] = 'uefi'
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

    @mock.patch('ironic_python_agent.utils.determine_time_method',
                autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test__sync_clock(self, execute_mock, mock_timemethod):
        self.config(ntp_server='192.168.1.1')
        self.config(fail_if_clock_not_set=True)
        execute_mock.return_value = ('', '')
        mock_timemethod.return_value = 'chronyd'

        self.agent_extension._sync_clock()

        calls = [mock.call('chronyc', 'shutdown', check_exit_code=[0, 1]),
                 mock.call("chronyd -q 'server 192.168.1.1 iburst'",
                           shell=True),
                 mock.call('hwclock', '-v', '--systohc')]
        execute_mock.assert_has_calls(calls)

        execute_mock.reset_mock()
        execute_mock.side_effect = [
            ('', ''), ('', ''),
            processutils.ProcessExecutionError('boop')
        ]

        self.assertRaises(errors.ClockSyncError,
                          self.agent_extension._sync_clock)
        execute_mock.assert_any_call('hwclock', '-v', '--systohc')

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_get_partition_uuids(self, execute_mock):
        self.agent_extension.partition_uuids = {'1': '2'}
        result = self.agent_extension.get_partition_uuids()
        self.assertEqual({'1': '2'}, result.serialize()['command_result'])

    @mock.patch.object(utils, 'get_node_boot_mode', lambda self: 'uefi')
    @mock.patch.object(utils, 'get_partition_table_type_from_specs',
                       lambda self: 'gpt')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    @mock.patch(
        'ironic_python_agent.disk_utils.get_and_validate_image_format',
        autospec=True)
    @mock.patch.object(partition_utils, 'work_on_disk', autospec=True)
    def test_write_partition_image_no_node_uuid_uefi(
            self, work_on_disk_mock,
            validate_mock,
            execute_mock, open_mock,
            dispatch_mock):
        image_info = _build_fake_partition_image_info()
        image_info['node_uuid'] = None
        device = '/dev/sda'
        root_mb = image_info['root_mb']
        swap_mb = image_info['swap_mb']
        ephemeral_mb = image_info['ephemeral_mb']
        ephemeral_format = image_info['ephemeral_format']
        node_uuid = image_info['node_uuid']
        pr_ep = image_info['preserve_ephemeral']
        source_format = image_info['disk_format']
        validate_mock.return_value = (source_format, _virtual_size(1))
        cpu_arch = self.fake_cpu.architecture

        image_path = standby._image_location(image_info)

        dispatch_mock.return_value = self.fake_cpu
        uuids = {'root uuid': 'root_uuid'}
        expected_uuid = {'root uuid': 'root_uuid'}
        work_on_disk_mock.return_value = uuids

        standby._write_image(image_info, device, 'configdrive')
        validate_mock.assert_called_once_with(image_path, source_format)
        work_on_disk_mock.assert_called_once_with(device, root_mb, swap_mb,
                                                  ephemeral_mb,
                                                  ephemeral_format,
                                                  image_path,
                                                  node_uuid,
                                                  configdrive='configdrive',
                                                  preserve_ephemeral=pr_ep,
                                                  boot_mode='uefi',
                                                  disk_label='gpt',
                                                  cpu_arch=cpu_arch,
                                                  source_format=source_format,
                                                  is_raw=False)

        self.assertEqual(expected_uuid, work_on_disk_mock.return_value)
        self.assertIsNone(node_uuid)


@mock.patch('hashlib.new', autospec=True)
@mock.patch('requests.get', autospec=True)
class TestImageDownload(base.IronicAgentTest):

    def test_download_image(self, requests_mock, hash_mock):
        content = ['SpongeBob', 'SquarePants']
        response = requests_mock.return_value
        response.status_code = 200
        response.iter_content.return_value = content

        image_info = _build_fake_image_info()
        hash_mock.return_value.hexdigest.return_value = image_info[
            'os_hash_value']
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={},
                                              timeout=60)
        self.assertEqual(image_info['os_hash_value'],
                         image_download._hash_algo.hexdigest())

    @mock.patch('time.sleep', autospec=True)
    def test_download_image_fail(self, sleep_mock, requests_mock, time_mock):
        response = requests_mock.return_value
        response.status_code = 401
        response.text = 'Unauthorized'
        time_mock.return_value = 0.0
        image_info = _build_fake_image_info()
        msg = ('Error downloading image: Download of image fake_id failed: '
               'URL: http://example.org; time: .* seconds. Error: '
               'Received status code 401 from http://example.org, expected '
               '200. Response body: Unauthorized')
        self.assertRaisesRegex(errors.ImageDownloadError, msg,
                               standby.ImageDownload, image_info)
        requests_mock.assert_called_once_with(image_info['urls'][0],
                                              cert=None, verify=True,
                                              stream=True, proxies={},
                                              timeout=60)
        self.assertFalse(sleep_mock.called)

    @mock.patch('time.sleep', autospec=True)
    def test_download_image_retries(self, sleep_mock, requests_mock,
                                    time_mock):
        self.config(image_download_connection_retries=2)
        response = requests_mock.return_value
        response.status_code = 500
        response.text = 'Oops'
        time_mock.return_value = 0.0
        image_info = _build_fake_image_info()
        msg = ('Error downloading image: Download of image fake_id failed: '
               'URL: http://example.org; time: .* seconds. Error: '
               'Received status code 500 from http://example.org, expected '
               '200. Response body: Oops')
        self.assertRaisesRegex(errors.ImageDownloadError, msg,
                               standby.ImageDownload, image_info)
        requests_mock.assert_called_with(image_info['urls'][0],
                                         cert=None, verify=True,
                                         stream=True, proxies={},
                                         timeout=60)
        self.assertEqual(3, requests_mock.call_count)
        sleep_mock.assert_called_with(10)
        self.assertEqual(2, sleep_mock.call_count)

    @mock.patch('time.sleep', autospec=True)
    def test_download_image_retries_success(self, sleep_mock, requests_mock,
                                            hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fail_response = mock.Mock()
        fail_response.status_code = 500
        fail_response.text = " "
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [requests.Timeout, fail_response, response]

        image_info = _build_fake_image_info()
        hash_mock.return_value.hexdigest.return_value = image_info[
            'os_hash_value']
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_called_with(image_info['urls'][0],
                                         cert=None, verify=True,
                                         stream=True, proxies={},
                                         timeout=60)
        self.assertEqual(3, requests_mock.call_count)
        sleep_mock.assert_called_with(10)
        self.assertEqual(2, sleep_mock.call_count)

    def test_download_image_and_checksum(self, requests_mock, hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = "019fe036425da1c562f2e9f5299820bf"
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = fake_cs + '\n'
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info()
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'http://example.com/checksum'
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())

    def test_download_image_and_checksum_md5(self, requests_mock, hash_mock):

        content = ['SpongeBob', 'SquarePants']
        fake_cs = "019fe036425da1c562f2e9f5299820bf"
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = fake_cs + '\n'
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info()
        del image_info['os_hash_value']
        del image_info['os_hash_algo']
        CONF.set_override('md5_enabled', True)
        image_info['checksum'] = 'http://example.com/checksum'
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())
        hash_mock.assert_has_calls([
            mock.call('md5')])

    def test_download_image_and_checksum_multiple_md5(self, requests_mock,
                                                      hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = "019fe036425da1c562f2e9f5299820bf"
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
foobar  irrelevant file.img
%s  image.img
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        CONF.set_override('md5_enabled', True)
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())

    def test_download_image_and_centos_checksum_md5(self, requests_mock,
                                                    hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = "019fe036425da1c562f2e9f5299820bf"
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
# centos-image.img: 1005593088 bytes
MD5 (centos-image.img) = %s
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/centos-image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        CONF.set_override('md5_enabled', True)
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None,
                      verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())

    def test_download_image_and_centos_checksum_sha256(self, requests_mock,
                                                       hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = ('3b678e4fb651d450f4970e1647abc9b0a38bff3febd3d558753'
                   '623c66369a633')
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
# centos-image.img: 1005593088 bytes
SHA256 (centos-image.img) = %s
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = iter(content)
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/centos-image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None,
                      verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())
        hash_mock.assert_has_calls([
            mock.call('sha256')])

    def test_download_image_and_centos_checksum_sha512(self, requests_mock,
                                                       hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = ('3b678e4fb651d450f4970e1647abc9b0a38bff3febd3d558753'
                   '623c66369a6333b678e4fb651d450f4970e1647abc9b0a38b'
                   'ff3febd3d558753623c66369a633')
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
# centos-image.img: 1005593088 bytes
SHA512 (centos-image.img) = %s
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = iter(content)
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/centos-image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None,
                      verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())
        hash_mock.assert_has_calls([
            mock.call('sha512')])

    def test_download_image_and_checksum_multiple_sha256(self, requests_mock,
                                                         hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = ('3b678e4fb651d450f4970e1647abc9b0a38bff3febd3d558753'
                   '623c66369a633')
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
foobar  irrelevant file.img
%s  image.img
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = iter(content)
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())
        hash_mock.assert_has_calls([
            mock.call('sha256')])

    def test_download_image_and_checksum_multiple_sha512(self, requests_mock,
                                                         hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = ('3b678e4fb651d450f4970e1647abc9b0a38bff3febd3d558753'
                   '623c66369a6333b678e4fb651d450f4970e1647abc9b0a38b'
                   'ff3febd3d558753623c66369a633')
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
foobar  irrelevant file.img
%s  image.img
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = iter(content)
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        hash_mock.return_value.hexdigest.return_value = fake_cs
        image_download = standby.ImageDownload(image_info)

        self.assertEqual(content, list(image_download))
        requests_mock.assert_has_calls([
            mock.call('http://example.com/checksum', cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
            mock.call(image_info['urls'][0], cert=None, verify=True,
                      stream=True, proxies={}, timeout=60),
        ])
        self.assertEqual(fake_cs, image_download._hash_algo.hexdigest())
        hash_mock.assert_has_calls([
            mock.call('sha512')])

    def test_download_image_and_checksum_unknown_file(self, requests_mock,
                                                      hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = "019fe036425da1c562f2e9f5299820bf"
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
foobar  irrelevant file.img
%s  not-my-image.img
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'http://example.com/checksum'
        hash_mock.return_value.hexdigest.return_value = fake_cs
        self.assertRaisesRegex(errors.ImageDownloadError,
                               'Checksum file does not contain name image.img',
                               standby.ImageDownload, image_info)

    def test_download_image_and_checksum_unknown_file_md5(self,
                                                          requests_mock,
                                                          hash_mock):
        CONF.set_override('md5_enabled', True)
        content = ['SpongeBob', 'SquarePants']
        fake_cs = "019fe036425da1c562f2e9f5299820bf"
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = """
foobar  irrelevant file.img
%s  not-my-image.img
""" % fake_cs
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        hash_mock.return_value.hexdigest.return_value = fake_cs
        self.assertRaisesRegex(errors.ImageDownloadError,
                               'Checksum file does not contain name image.img',
                               standby.ImageDownload, image_info)

    def test_download_image_and_checksum_empty_file_md5(self, requests_mock,
                                                        hash_mock):
        CONF.set_override('md5_enabled', True)
        content = ['SpongeBob', 'SquarePants']
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = " "
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_algo']
        del image_info['os_hash_value']
        self.assertRaisesRegex(errors.ImageDownloadError,
                               'Empty checksum file',
                               standby.ImageDownload, image_info)

    def test_download_image_and_checksum_empty_file(self, requests_mock,
                                                    hash_mock):
        content = ['SpongeBob', 'SquarePants']
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = " "
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'http://example.com/checksum'
        self.assertRaisesRegex(errors.ImageDownloadError,
                               'Empty checksum file',
                               standby.ImageDownload, image_info)

    def test_download_image_and_checksum_failed(self, requests_mock,
                                                hash_mock):
        self.config(image_download_connection_retry_interval=0)
        content = ['SpongeBob', 'SquarePants']
        cs_response = mock.Mock()
        cs_response.status_code = 400
        cs_response.text = " "
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        # 3 retries on status code
        requests_mock.side_effect = [cs_response, cs_response, cs_response,
                                     response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['os_hash_value'] = 'http://example.com/checksum'
        image_info['os_hash_algo'] = 'sha512'
        self.assertRaisesRegex(errors.ImageDownloadError,
                               'Received status code 400 from '
                               'http://example.com/checksum',
                               standby.ImageDownload, image_info)

    def test_download_image_and_checksum_failed_md5(self,
                                                    requests_mock,
                                                    hash_mock):
        CONF.set_override('md5_enabled', True)
        self.config(image_download_connection_retry_interval=0)
        content = ['SpongeBob', 'SquarePants']
        cs_response = mock.Mock()
        cs_response.status_code = 400
        cs_response.text = " "
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        # 3 retries on status code
        requests_mock.side_effect = [cs_response, cs_response, cs_response,
                                     response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['checksum'] = 'http://example.com/checksum'
        del image_info['os_hash_value']
        del image_info['os_hash_algo']
        self.assertRaisesRegex(errors.ImageDownloadError,
                               'Received status code 400 from '
                               'http://example.com/checksum',
                               standby.ImageDownload, image_info)

    def test_download_image_and_invalid_checksum(self, requests_mock,
                                                 hash_mock):
        content = ['SpongeBob', 'SquarePants']
        fake_cs = "invalid"
        cs_response = mock.Mock()
        cs_response.status_code = 200
        cs_response.text = fake_cs + '\n'
        response = mock.Mock()
        response.status_code = 200
        response.iter_content.return_value = content
        requests_mock.side_effect = [cs_response, response]

        image_info = _build_fake_image_info(
            'http://example.com/path/image.img')
        image_info['os_hash_algo'] = 'sha512'
        image_info['os_hash_value'] = 'http://example.com/checksum'
        self.assertRaisesRegex(
            errors.ImageDownloadError,
            r"Invalid checksum file \(No valid checksum found\) \['invalid'\]",
            standby.ImageDownload, image_info)

# Copyright 2022 Nvidia
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

import builtins
import io
import shutil
import tempfile
from unittest import mock
from urllib import error as urlError

from oslo_concurrency import processutils
from oslo_utils import fileutils

from ironic_python_agent.hardware_managers.nvidia import nvidia_fw_update
from ironic_python_agent.tests.unit import base
from ironic_python_agent import utils


class TestCheckPrereq(base.IronicAgentTest):
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_prereq(self, mocked_execute):
        nvidia_fw_update.check_prereq()
        calls = [mock.call('mstflint', '-v'),
                 mock.call('mstconfig', '-v'),
                 mock.call('mstfwreset', '-v'),
                 mock.call('lspci', '--version')]
        mocked_execute.assert_has_calls(calls)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_prereq_exception(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaises(processutils.ProcessExecutionError,
                          nvidia_fw_update.check_prereq)


class TestNvidiaNicFirmwareOps(base.IronicAgentTest):
    def setUp(self):
        super(TestNvidiaNicFirmwareOps, self).setUp()
        dev = "0000:03:00.0"
        self.nvidia_nic_fw_ops = nvidia_fw_update.NvidiaNicFirmwareOps(dev)

    def test_parse_mstflint_query_output(self):
        mstflint_data = """Image type:            FS4
FW Version:            20.35.1012
FW Release Date:       28.10.2022
Product Version:       20.35.1012
Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.804 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             043f720300f04c46        8
Base MAC:              043f72f04c46            8
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A"""
        expected_return = {'fw_ver': '20.35.1012', 'psid': 'MT_0000000228'}
        parsed_data = nvidia_fw_update.NvidiaNicFirmwareOps.\
            parse_mstflint_query_output(mstflint_data)
        self.assertEqual(expected_return, parsed_data)

    def test_parse_mstflint_query_output_with_running_fw(self):
        mstflint_data = """Image type:            FS4
FW Version:            20.35.1012
FW Version(Running):   20.34.1002
FW Release Date:       28.10.2022
Product Version:       20.35.1012
Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.804 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             043f720300f04c46        8
Base MAC:              043f72f04c46            8
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A"""
        expected_return = {'fw_ver': '20.35.1012', 'psid': 'MT_0000000228',
                           'running_fw_ver': '20.34.1002'}
        parsed_data = nvidia_fw_update.NvidiaNicFirmwareOps.\
            parse_mstflint_query_output(mstflint_data)
        self.assertEqual(expected_return, parsed_data)

    def test_parse_mstflint_query_output_no_data(self):
        mstflint_data = ""
        parsed_data = nvidia_fw_update.NvidiaNicFirmwareOps.\
            parse_mstflint_query_output(mstflint_data)
        self.assertFalse(parsed_data)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__query_device(self, mocked_execute):
        mocked_execute.return_value = ("""Image type:            FS4
FW Version:            20.35.1012
FW Release Date:       28.10.2022
Product Version:       20.35.1012
Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.804 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             043f720300f04c46        8
Base MAC:              043f72f04c46            8
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A""", '')
        expected_return = {'device': self.nvidia_nic_fw_ops.dev,
                           'fw_ver': '20.35.1012',
                           'psid': 'MT_0000000228'}
        query_output = self.nvidia_nic_fw_ops._query_device()
        self.assertEqual(self.nvidia_nic_fw_ops.dev,
                         self.nvidia_nic_fw_ops.dev)
        self.assertEqual(self.nvidia_nic_fw_ops.dev_info, expected_return)
        self.assertEqual(query_output, expected_return)
        mocked_execute.assert_called_once()

        # Do another query and make sure that the run command
        # called only one
        query_output2 = self.nvidia_nic_fw_ops._query_device()
        mocked_execute.assert_called_once()
        self.assertEqual(query_output2, expected_return)

        # Do another query with force and make sure that the run command
        # called one more time
        query_output3 = self.nvidia_nic_fw_ops._query_device(force=True)
        self.assertEqual(mocked_execute.call_count, 2)
        self.assertEqual(query_output3, expected_return)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_nic_psid(self, mocked_execute):
        mocked_execute.return_value = ("""Image type:            FS4
FW Version:            20.35.1012
FW Release Date:       28.10.2022
Product Version:       20.35.1012
Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.804 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             043f720300f04c46        8
Base MAC:              043f72f04c46            8
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A""", '')
        psid = self.nvidia_nic_fw_ops.get_nic_psid()
        self.assertEqual(psid, "MT_0000000228")
        mocked_execute.assert_called_once()

        @mock.patch.object(utils, 'execute', autospec=True)
        def test_is_image_changed_false(self, mocked_execute):
            mocked_execute.return_value = ("""Image type:            FS4
    FW Version:            20.35.1012
    FW Release Date:       28.10.2022
    Product Version:       20.35.1012
    Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                           type=PXE version=3.6.804 cpu=AMD64
    Description:           UID                GuidsNumber
    Base GUID:             043f720300f04c46        8
    Base MAC:              043f72f04c46            8
    Image VSD:             N/A
    Device VSD:            N/A
    PSID:                  MT_0000000228
    Security Attributes:   N/A""", '')
            is_image_changed = self.nvidia_nic_fw_ops.is_image_changed()
            self.assertFalse(is_image_changed)

        @mock.patch.object(utils, 'execute', autospec=True)
        def test_is_image_changed_true(self, mocked_execute):
            mocked_execute.return_value = ("""Image type:            FS4
    FW Version:            20.35.1012
    FW Version(Running):   20.34.1002
    FW Release Date:       28.10.2022
    Product Version:       20.35.1012
    Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                           type=PXE version=3.6.804 cpu=AMD64
    Description:           UID                GuidsNumber
    Base GUID:             043f720300f04c46        8
    Base MAC:              043f72f04c46            8
    Image VSD:             N/A
    Device VSD:            N/A
    PSID:                  MT_0000000228
    Security Attributes:   N/A""", '')
            is_image_changed = self.nvidia_nic_fw_ops.is_image_changed()
            self.assertTrue(is_image_changed)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_is_image_changed_true(self, mocked_execute):
        image_info = """Image type:            FS4
FW Version:            20.36.1012
FW Release Date:       28.10.2022
Product Version:       rel-20_35_1012
Rom Info:              type=UEFI version=14.29.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.904 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             N/A                     4
Base MAC:              N/A                     4
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A
Security Ver:          0"""

        mocked_execute.return_value = ("""Image type:            FS4
FW Version:            20.35.1012
FW Release Date:       28.10.2022
Product Version:       20.35.1012
Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.804 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             043f720300f04c46        8
Base MAC:              043f72f04c46            8
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A""", '')
        parsed_image_info = nvidia_fw_update.NvidiaNicFirmwareOps.\
            parse_mstflint_query_output(image_info)
        need_update = self.nvidia_nic_fw_ops._need_update(
            parsed_image_info['fw_ver'])
        self.assertTrue(need_update)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_fw_update_if_needed(self, mocked_execute):
        mocked_execute1_return_value = ("""Image type:            FS4
FW Version:            20.33.1012
FW Release Date:       28.10.2022
Product Version:       20.35.1012
Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.804 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             043f720300f04c46        8
Base MAC:              043f72f04c46            8
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A""", '')
        mocked_execute.side_effect = [mocked_execute1_return_value, '']
        image_path = '/tmp/nvidia_firmware65686/fw_20_35_1012.bin'
        self.nvidia_nic_fw_ops.fw_update_if_needed('20.35.1012', image_path)
        calls = [mock.call('mstflint', '-d',
                           self.nvidia_nic_fw_ops.dev, '-qq', 'query'),
                 mock.call('mstflint', '-d',
                           self.nvidia_nic_fw_ops.dev, '-i', image_path,
                           '-y', 'burn')]
        mocked_execute.assert_has_calls(calls)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_fw_update_if_needed_with_reset(self, mocked_execute):
        mocked_execute1_return_value = ("""Image type:            FS4
FW Version:            20.33.1012
FW Version(Running):   20.34.1002
FW Release Date:       28.10.2022
Product Version:       20.35.1012
Rom Info:              type=UEFI version=14.28.15 cpu=AMD64,AARCH64
                       type=PXE version=3.6.804 cpu=AMD64
Description:           UID                GuidsNumber
Base GUID:             043f720300f04c46        8
Base MAC:              043f72f04c46            8
Image VSD:             N/A
Device VSD:            N/A
PSID:                  MT_0000000228
Security Attributes:   N/A""", '')
        mocked_execute.side_effect = [mocked_execute1_return_value, '', '']
        image_path = '/tmp/nvidia_firmware65686/fw_20_35_1012.bin'
        self.nvidia_nic_fw_ops.fw_update_if_needed('20.35.1012', image_path)
        calls = [mock.call('mstflint', '-d',
                           self.nvidia_nic_fw_ops.dev, '-qq', 'query'),
                 mock.call('mstfwreset', '-d', self.nvidia_nic_fw_ops.dev,
                           '-y', '--sync', '1', 'reset'),
                 mock.call('mstflint', '-d', self.nvidia_nic_fw_ops.dev,
                           '-i', image_path,
                           '-y', 'burn')]
        mocked_execute.assert_has_calls(calls)


class TestNvidiaNics(base.IronicAgentTest):
    def setUp(self):
        super(TestNvidiaNics, self).setUp()
        self.nvidia_nics = nvidia_fw_update.NvidiaNics()

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_nvidia_nics(self, mocked_execute):
        mocked_execute1_return_value = ("""0000:06:00.0 0200: 15b3:101b
0000:06:00.1 0207: 15b3:101b
0000:03:00.0 0207: 15b3:1017
0000:03:00.1 0207: 15b3:1017
""", '')
        mocked_execute2_return_value = ("""Image type:            FS4
FW Version:            20.35.1012
PSID:                  MT_0000000228
""", '')
        mocked_execute3_return_value = ("""Image type:            FS4
FW Version:            20.35.1012
PSID:                  MT_0000000228
""", '')
        mocked_execute4_return_value = ("""Image type:            FS4
FW Version:            16.35.1012
PSID:                  MT_0000000652
""", '')
        mocked_execute5_return_value = ("""Image type:            FS4
FW Version:            16.35.1012
PSID:                  MT_0000000652
""", '')
        mocked_execute.side_effect = [mocked_execute1_return_value,
                                      mocked_execute2_return_value,
                                      mocked_execute3_return_value,
                                      mocked_execute4_return_value,
                                      mocked_execute5_return_value]

        self.nvidia_nics.discover()
        calls = [mock.call('lspci', '-Dn', '-d', '15b3:'),
                 mock.call('mstflint', '-d', '0000:06:00.0', '-qq', 'query'),
                 mock.call('mstflint', '-d', '0000:06:00.1', '-qq', 'query'),
                 mock.call('mstflint', '-d', '0000:03:00.0', '-qq', 'query'),
                 mock.call('mstflint', '-d', '0000:03:00.1', '-qq', 'query')]
        self.assertEqual(mocked_execute.call_args_list, calls)
        self.assertEqual(len(self.nvidia_nics._devs), 4)
        psids_list = self.nvidia_nics.get_psids_list()
        ids_list = self.nvidia_nics.get_ids_list()
        self.assertEqual(psids_list, {'MT_0000000228', 'MT_0000000652'})
        self.assertEqual(ids_list, {'101b', '1017'})


class TestNvidiaNicFirmwareBinary(base.IronicAgentTest):
    def setUp(self):
        super(TestNvidiaNicFirmwareBinary, self).setUp()

    @mock.patch.object(nvidia_fw_update.request, 'urlopen', autospec=True)
    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(fileutils, 'compute_file_checksum', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_http(
            self, mocked_mkdtemp, mocked_compute_file_checksum,
            mocked_execute, open_mock, mocked_url_open):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        a = mock.Mock()
        a.read.return_value = 'dummy data'
        mocked_url_open.return_value = a
        mocked_execute.return_value = ("""Image type:            FS4
FW Version:            20.35.1012
PSID:                  MT_0000000228
""", '')
        mocked_compute_file_checksum.return_value = \
            'a94e683ea16d9ae44768f0a65942234c'
        fd_mock = mock.MagicMock(spec=io.BytesIO)
        open_mock.return_value = fd_mock
        nvidia_nic_fw_binary = nvidia_fw_update.NvidiaNicFirmwareBinary(
            'http://10.10.10.10/firmware_images/fw1.bin',
            'a94e683ea16d9ae44768f0a65942234c',
            'sha512',
            'MT_0000000228',
            '20.35.1012')
        mocked_execute.assert_called_once()
        mocked_compute_file_checksum.assert_called_once()
        open_mock.assert_called_once()
        mocked_url_open.assert_called_once()
        mocked_mkdtemp.assert_called_once()
        self.assertEqual(nvidia_nic_fw_binary.dest_file_path,
                         '/tmp/nvidia_firmware123/fw1.bin')

    @mock.patch.object(nvidia_fw_update.request, 'urlopen', autospec=True)
    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(fileutils, 'compute_file_checksum', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_https(
            self, mocked_mkdtemp, mocked_compute_file_checksum,
            mocked_execute, open_mock, mocked_url_open):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        a = mock.Mock()
        a.read.return_value = 'dummy data'
        mocked_url_open.return_value = a
        mocked_execute.return_value = ("""Image type:            FS4
FW Version:            20.35.1012
PSID:                  MT_0000000228
""", '')
        mocked_compute_file_checksum.return_value = \
            'a94e683ea16d9ae44768f0a65942234c'
        fd_mock = mock.MagicMock(spec=io.BytesIO)
        open_mock.return_value = fd_mock
        nvidia_nic_fw_binary = nvidia_fw_update.NvidiaNicFirmwareBinary(
            'https://10.10.10.10/firmware_images/fw1.bin',
            'a94e683ea16d9ae44768f0a65942234c',
            'sha512',
            'MT_0000000228',
            '20.35.1012')
        mocked_execute.assert_called_once()
        mocked_compute_file_checksum.assert_called_once()
        open_mock.assert_called_once()
        mocked_url_open.assert_called_once()
        mocked_mkdtemp.assert_called_once()
        self.assertEqual(nvidia_nic_fw_binary.dest_file_path,
                         '/tmp/nvidia_firmware123/fw1.bin')

    def test_nvidia_nic_firmware_binray_invalid_url_scheme(self):
        self.assertRaises(nvidia_fw_update.InvalidURLScheme,
                          nvidia_fw_update.NvidiaNicFirmwareBinary,
                          'ftp://10.10.10.10/firmware_images/fw1.bin',
                          'a94e683ea16d9ae44768f0a65942234c',
                          'sha512',
                          'MT_0000000228',
                          '20.35.1012')

    @mock.patch.object(nvidia_fw_update.request, 'urlopen', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_http_err(self, mocked_mkdtemp,
                                                 mocked_url_open):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        mocked_url_open.side_effect = urlError.HTTPError(
            'http://10.10.10.10/firmware_images/fw1.bin',
            500, 'Internal Error', {}, None)
        self.assertRaises(urlError.HTTPError,
                          nvidia_fw_update.NvidiaNicFirmwareBinary,
                          'http://10.10.10.10/firmware_images/fw1.bin',
                          'a94e683ea16d9ae44768f0a65942234c',
                          'sha512',
                          'MT_0000000228',
                          '20.35.1012')
        mocked_url_open.assert_called_once()
        mocked_mkdtemp.assert_called_once()

    @mock.patch.object(nvidia_fw_update.request, 'urlopen', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_http_url_err(
            self, mocked_mkdtemp, mocked_url_open):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        mocked_url_open.side_effect = urlError.URLError('URL error')
        self.assertRaises(urlError.URLError,
                          nvidia_fw_update.NvidiaNicFirmwareBinary,
                          'http://10.10.10.firmware_images/fw1.bin',
                          'a94e683ea16d9ae44768f0a65942234c',
                          'sha512',
                          'MT_0000000228',
                          '20.35.1012')
        mocked_url_open.assert_called_once()
        mocked_mkdtemp.assert_called_once()

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(fileutils, 'compute_file_checksum', autospec=True)
    @mock.patch.object(shutil, 'move', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_file(self, mocked_mkdtemp,
                                             mocked_move,
                                             mocked_compute_file_checksum,
                                             mocked_execute, ):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        a = mock.Mock()
        a.read.return_value = 'dummy data'
        mocked_execute.return_value = ("""Image type:            FS4
FW Version:            20.35.1012
PSID:                  MT_0000000228
""", '')
        mocked_compute_file_checksum.return_value = \
            'a94e683ea16d9ae44768f0a65942234c'
        nvidia_nic_fw_binary = nvidia_fw_update.NvidiaNicFirmwareBinary(
            'file://10.10.10.10/firmware_images/fw1.bin',
            'a94e683ea16d9ae44768f0a65942234c',
            'sha512',
            'MT_0000000228',
            '20.35.1012')
        mocked_move.assert_called_once()
        mocked_execute.assert_called_once()
        mocked_compute_file_checksum.assert_called_once()
        self.assertEqual(nvidia_nic_fw_binary.dest_file_path,
                         '/tmp/nvidia_firmware123/fw1.bin')

    @mock.patch.object(shutil, 'move', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_file_not_found(
            self, mocked_mkdtemp, mocked_move):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        mocked_move.side_effect = FileNotFoundError
        self.assertRaises(FileNotFoundError,
                          nvidia_fw_update.NvidiaNicFirmwareBinary,
                          'file://10.10.10.10/firmware_images/fw1.bin',
                          'a94e683ea16d9ae44768f0a65942234c',
                          'sha512',
                          'MT_0000000228',
                          '20.35.1012')
        mocked_move.assert_called_once()

    @mock.patch.object(nvidia_fw_update.request, 'urlopen', autospec=True)
    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_mismatch_component_flavor(
            self, mocked_mkdtemp, mocked_execute, open_mock, mocked_url_open):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        a = mock.Mock()
        a.read.return_value = 'dummy data'
        mocked_url_open.return_value = a
        mocked_execute.return_value = ("""Image type:            FS4
    FW Version:            20.35.1012
    PSID:                  MT_0000000228
    """, '')
        fd_mock = mock.MagicMock(spec=io.BytesIO)
        open_mock.return_value = fd_mock
        self.assertRaises(nvidia_fw_update.MismatchComponentFlavor,
                          nvidia_fw_update.NvidiaNicFirmwareBinary,
                          'http://10.10.10.10/firmware_images/fw1.bin',
                          'a94e683ea16d9ae44768f0a65942234c',
                          'sha512',
                          'MT_0000000227',
                          '20.35.1012')
        mocked_execute.assert_called_once()
        open_mock.assert_called_once()
        mocked_url_open.assert_called_once()
        mocked_mkdtemp.assert_called_once()

    @mock.patch.object(nvidia_fw_update.request, 'urlopen', autospec=True)
    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_mismatch_fw_version(
            self, mocked_mkdtemp, mocked_execute, open_mock, mocked_url_open):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        a = mock.Mock()
        a.read.return_value = 'dummy data'
        mocked_url_open.return_value = a
        mocked_execute.return_value = ("""Image type:            FS4
        FW Version:            20.35.1012
        PSID:                  MT_0000000228
        """, '')
        fd_mock = mock.MagicMock(spec=io.BytesIO)
        open_mock.return_value = fd_mock
        self.assertRaises(nvidia_fw_update.MismatchFWVersion,
                          nvidia_fw_update.NvidiaNicFirmwareBinary,
                          'http://10.10.10.10/firmware_images/fw1.bin',
                          'a94e683ea16d9ae44768f0a65942234c',
                          'sha512',
                          'MT_0000000228',
                          '20.34.1012')
        mocked_execute.assert_called_once()
        open_mock.assert_called_once()
        mocked_url_open.assert_called_once()
        mocked_mkdtemp.assert_called_once()

    @mock.patch.object(nvidia_fw_update.request, 'urlopen', autospec=True)
    @mock.patch.object(builtins, 'open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(fileutils, 'compute_file_checksum', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    def test_nvidia_nic_firmware_binray_mismatch_checksum(
            self, mocked_mkdtemp, mocked_compute_file_checksum,
            mocked_execute, open_mock, mocked_url_open):
        mocked_mkdtemp.return_value = '/tmp/nvidia_firmware123/'
        a = mock.Mock()
        a.read.return_value = 'dummy data'
        mocked_url_open.return_value = a
        mocked_execute.return_value = ("""Image type:            FS4
        FW Version:            20.35.1012
        PSID:                  MT_0000000228
        """, '')
        mocked_compute_file_checksum.return_value = \
            'a94e683ea16d9ae44768f0a65942234c'
        fd_mock = mock.MagicMock(spec=io.BytesIO)
        open_mock.return_value = fd_mock
        self.assertRaises(nvidia_fw_update.MismatchChecksumError,
                          nvidia_fw_update.NvidiaNicFirmwareBinary,
                          'http://10.10.10.10/firmware_images/fw1.bin',
                          'a94e683ea16d9ae44768f0a65942234d',
                          'sha512',
                          'MT_0000000228',
                          '20.35.1012')
        mocked_execute.assert_called_once()
        mocked_compute_file_checksum.assert_called_once()
        open_mock.assert_called_once()
        mocked_url_open.assert_called_once()
        mocked_mkdtemp.assert_called_once()


class TestNvidiaFirmwareImages(base.IronicAgentTest):
    def setUp(self):
        super(TestNvidiaFirmwareImages, self).setUp()

    def test_validate_images_schema(self):
        firmware_images = [
            {
                "url": "file:///firmware_images/fw1.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234d",
                "checksumType": "md5",
                "componentFlavor": "MT_0000000540",
                "version": "24.34.1002"
            },
            {
                "url": "http://10.10.10.10/firmware_images/fw2.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234c",
                "checksumType": "sha512",
                "componentFlavor": "MT_0000000652",
                "version": "24.34.1002"
            }
        ]
        nvidia_fw_images = nvidia_fw_update.NvidiaFirmwareImages(
            firmware_images)
        nvidia_fw_images.validate_images_schema()

    def test_validate_images_schema_invalid_parameter(self):
        firmware_images = [
            {
                "url": "file:///firmware_images/fw1.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234d",
                "checksumType": "md5",
                "componentFlavor": "MT_0000000540",
                "version": "24.34.1002"
            },
            {
                "url": "http://10.10.10.10/firmware_images/fw2.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234c",
                "checksumType": "sha512",
                "component": "MT_0000000652",
                "version": "24.34.1002"
            }
        ]
        nvidia_fw_images = nvidia_fw_update.NvidiaFirmwareImages(
            firmware_images)
        self.assertRaises(nvidia_fw_update.InvalidFirmwareImageConfig,
                          nvidia_fw_images.validate_images_schema)

    def test_filter_images(self):
        firmware_images = [
            {
                "url": "file:///firmware_images/fw1.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234d",
                "checksumType": "md5",
                "componentFlavor": "MT_0000000540",
                "version": "24.34.1002"
            },
            {
                "url": "http://10.10.10.10/firmware_images/fw2.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234c",
                "checksumType": "sha512",
                "componentFlavor": "MT_0000000652",
                "version": "24.34.1002"
            }
        ]
        psids_list = ['MT_0000000540', 'MT_0000000680']
        nvidia_fw_images = nvidia_fw_update.NvidiaFirmwareImages(
            firmware_images)
        nvidia_fw_images.validate_images_schema()
        expected_images_psid_dict = {"MT_0000000540": {
            "url": "file:///firmware_images/fw1.bin",
            "checksum": "a94e683ea16d9ae44768f0a65942234d",
            "checksumType": "md5",
            "componentFlavor": "MT_0000000540",
            "version": "24.34.1002"
        }}
        nvidia_fw_images.filter_images(psids_list)
        self.assertEqual(nvidia_fw_images.filtered_images_psid_dict,
                         expected_images_psid_dict)

    def test_filter_images_duplicate_component_flavor_exception(self):
        firmware_images = [
            {
                "url": "file:///firmware_images/fw1.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234d",
                "checksumType": "md5",
                "componentFlavor": "MT_0000000540",
                "version": "24.34.1002"
            },
            {
                "url": "http://10.10.10.10/firmware_images/fw2.bin",
                "checksum": "a94e683ea16d9ae44768f0a65942234c",
                "checksumType": "sha512",
                "componentFlavor": "MT_0000000540",
                "version": "24.35.1002"
            }
        ]
        psids_list = ['MT_0000000540', 'MT_0000000680']
        nvidia_fw_images = nvidia_fw_update.NvidiaFirmwareImages(
            firmware_images)
        nvidia_fw_images.validate_images_schema()
        self.assertRaises(nvidia_fw_update.DuplicateComponentFlavor,
                          nvidia_fw_images.filter_images,
                          psids_list)

    def test_apply_net_firmware_update(self):
        pass


class TestNvidiaNicConfig(base.IronicAgentTest):
    def setUp(self):
        super(TestNvidiaNicConfig, self).setUp()
        self.dev = "0000:03:00.0"

    def test__mstconfig_parse_data(self):
        mstconfig_data = """
Device #1:
----------

Device type:    ConnectX6
Name:           MCX654106A-HCA_Ax
Device:         0000:06:00.0

Configurations:                              Next Boot
         NUM_OF_VFS                          0
         SRIOV_EN                            False(0)
         PF_TOTAL_SF                         0
"""
        expected_return = {'NUM_OF_VFS': '0', 'SRIOV_EN': 'False(0)',
                           'PF_TOTAL_SF': '0'}
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(self.dev, {})
        parsed_data = nvidia_nic_config._mstconfig_parse_data(mstconfig_data)
        self.assertEqual(expected_return, parsed_data)

    def test__mstconfig_parse_data_no_data(self):
        mstconfig_data = ""
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(self.dev, {})
        parsed_data = nvidia_nic_config._mstconfig_parse_data(mstconfig_data)
        self.assertFalse(parsed_data)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__get_device_conf_dict(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        mocked_execute.return_value = ("""
Device #1:
----------

Device type:    ConnectX6
Name:           MCX654106A-HCA_Ax
Device:         0000:06:00.0

Configurations:                              Next Boot
         NUM_OF_VFS                          0
         SRIOV_EN                            False(0)
         PF_TOTAL_SF                         0
""", '')
        expected_return = {'NUM_OF_VFS': '0', 'SRIOV_EN': 'False(0)',
                           'PF_TOTAL_SF': '0'}

        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, {})
        conf_dict = nvidia_nic_config._get_device_conf_dict()
        self.assertEqual(expected_return, conf_dict)
        self.assertEqual(expected_return, nvidia_nic_config.device_conf_dict)
        mocked_execute.assert_called_once()

        # Do another query and make sure that the run command called only one
        conf_dict2 = nvidia_nic_config._get_device_conf_dict()
        mocked_execute.assert_called_once()
        self.assertEqual(conf_dict2, expected_return)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__get_device_conf_dict_exception(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        mocked_execute.side_effect = processutils.ProcessExecutionError
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, {})
        self.assertRaises(processutils.ProcessExecutionError,
                          nvidia_nic_config._get_device_conf_dict)
        mocked_execute.assert_called_once()

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__param_supp_by_config_tool(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        mocked_execute.return_value = (
            """List of configurations the device 0000:06:00.0 may support:
    GLOBAL PCI CONF:
        SRIOV_EN=<False|True> Enable Single-Root I/O Virtualization (SR-IOV)
    PF PCI CONF:

        PF_TOTAL_SF=<NUM>     The total number of Sub Function partitions
                              (SFs) that can be supported, for this PF.
                              alid only when PER_PF_NUM_SF is set to TRUE
    INTERNAL HAIRPIN CONF:
        ESWITCH_HAIRPIN_TOT_BUFFER_SIZE=<NUM>   Log(base 2) of the buffer size
                                                (in bytes) allocated
                                                internally for hairpin for a
                                                given IEEE802.1p priority i.
                                                0 means no buffer for this
                                                priority and traffic with this
                                                priority will be dropped.

""", '')
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, {})
        global_config_param = "SRIOV_EN"
        function_config_param = "PF_TOTAL_SF"
        array_param = "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[0]"
        unspoorted_param = "UNSUPPORTED_PARAM"

        self.assertTrue(nvidia_nic_config._param_supp_by_config_tool(
            global_config_param))
        self.assertTrue(nvidia_nic_config._param_supp_by_config_tool(
            function_config_param))
        self.assertTrue(nvidia_nic_config._param_supp_by_config_tool(
            array_param))
        self.assertFalse(nvidia_nic_config._param_supp_by_config_tool(
            unspoorted_param))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__param_supp_by_config_tool_exception(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, {})
        fake_param = "FAKE_PARAM"
        mocked_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaises(processutils.ProcessExecutionError,
                          nvidia_nic_config._param_supp_by_config_tool,
                          fake_param)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__param_supp_by_fw(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        mocked_execute.return_value = ("""
Device #1:
----------

Device type:    ConnectX6
Name:           MCX654106A-HCA_Ax
Device:         0000:06:00.0

Configurations:                              Next Boot
         NUM_OF_VFS                          0
         SRIOV_EN                            False(0)
         PF_TOTAL_SF                         0
         ESWITCH_HAIRPIN_TOT_BUFFER_SIZE     Array[0..7]
""", '')
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, {})
        global_config_param = "SRIOV_EN"
        function_config_param = "PF_TOTAL_SF"
        array_param = "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[0]"
        array_param_with_range = "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[0..3]"
        array_param_index_out_of_range1 = "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[8]"
        array_param_index_out_of_range2 = \
            "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[0..8]"
        unspoorted_param = "UNSUPPORTED_PARAM"

        self.assertTrue(nvidia_nic_config._param_supp_by_fw(
            global_config_param))
        self.assertTrue(nvidia_nic_config._param_supp_by_fw(
            function_config_param))
        self.assertTrue(nvidia_nic_config._param_supp_by_fw(array_param))
        self.assertTrue(nvidia_nic_config._param_supp_by_fw(
            array_param_with_range))
        self.assertFalse(nvidia_nic_config._param_supp_by_fw(
            array_param_index_out_of_range1))
        self.assertFalse(nvidia_nic_config._param_supp_by_fw(
            array_param_index_out_of_range2))
        self.assertFalse(nvidia_nic_config._param_supp_by_fw(
            unspoorted_param))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__param_supp_by_fw_exception(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, {})
        fake_param = "FAKE_PARAM"
        mocked_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaises(processutils.ProcessExecutionError,
                          nvidia_nic_config._param_supp_by_fw,
                          fake_param)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_config(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        mocked_execute1_return_value = (
            """List of configurations the device 0000:06:00.0 may support:
    GLOBAL PCI CONF:
        SRIOV_EN=<False|True> Enable Single-Root I/O Virtualization (SR-IOV)
    PF PCI CONF:

        PF_TOTAL_SF=<NUM>     The total number of Sub Function partitions
                              (SFs) that can be supported, for this PF.
                              alid only when PER_PF_NUM_SF is set to TRUE
    INTERNAL HAIRPIN CONF:
        ESWITCH_HAIRPIN_TOT_BUFFER_SIZE=<NUM>   Log(base 2) of the buffer size
                                                (in bytes) allocated
                                                internally for hairpin for a
                                                given IEEE802.1p priority i.
                                                0 means no buffer for this
                                                priority and traffic with this
                                                priority will be dropped.

""", '')
        mocked_execute2_return_value = ("""
Device #1:
----------

Device type:    ConnectX6
Name:           MCX654106A-HCA_Ax
Device:         0000:06:00.0

Configurations:                              Next Boot
         NUM_OF_VFS                          0
         SRIOV_EN                            False(0)
         PF_TOTAL_SF                         0
         ESWITCH_HAIRPIN_TOT_BUFFER_SIZE     Array[0..7]
""", '')
        mocked_execute.side_effect = [mocked_execute1_return_value,
                                      mocked_execute2_return_value]
        params = {"SRIOV_EN": True, "PF_TOTAL_SF": 16,
                  "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[2]": 16}
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, params)
        nvidia_nic_config.validate_config()
        calls = [mock.call('mstconfig', '-d',
                           nvidia_nic_config.nvidia_dev.dev_pci, 'i'),
                 mock.call('mstconfig', '-d',
                           nvidia_nic_config.nvidia_dev.dev_pci, 'q')]
        self.assertEqual(mocked_execute.call_args_list, calls)
        self.assertEqual(mocked_execute.call_count, 2)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_config_unsupported_config_by_mstflint_package(
            self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        mocked_execute.return_value = (
            """List of configurations the device 0000:06:00.0 may support:
    GLOBAL PCI CONF:
        SRIOV_EN=<False|True> Enable Single-Root I/O Virtualization (SR-IOV)
    PF PCI CONF:

        PF_TOTAL_SF=<NUM>     The total number of Sub Function partitions
                              (SFs) that can be supported, for this PF.
                              alid only when PER_PF_NUM_SF is set to TRUE
    INTERNAL HAIRPIN CONF:
        ESWITCH_HAIRPIN_TOT_BUFFER_SIZE=<NUM>   Log(base 2) of the buffer size
                                                (in bytes) allocated
                                                internally for hairpin for a
                                                given IEEE802.1p priority i.
                                                0 means no buffer for this
                                                priority and traffic with this
                                                priority will be dropped.

""", '')
        params = {"UNSUPPORTED_PARAM": "unsupported_param"}
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, params)
        self.assertRaises(nvidia_fw_update.UnSupportedConfigByMstflintPackage,
                          nvidia_nic_config.validate_config)
        mocked_execute.assert_called_once_with(
            'mstconfig', '-d', nvidia_nic_config.nvidia_dev.dev_pci, 'i')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_config_unsupported_config_by_fw(self,
                                                      mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        mocked_execute1_return_value = (
            """List of configurations the device 0000:06:00.0 may support:
    GLOBAL PCI CONF:
        SRIOV_EN=<False|True> Enable Single-Root I/O Virtualization (SR-IOV)
    PF PCI CONF:

        PF_TOTAL_SF=<NUM>     The total number of Sub Function partitions
                              (SFs) that can be supported, for this PF.
                              alid only when PER_PF_NUM_SF is set to TRUE
    INTERNAL HAIRPIN CONF:
        ESWITCH_HAIRPIN_TOT_BUFFER_SIZE=<NUM>   Log(base 2) of the buffer size
                                                (in bytes) allocated
                                                internally for hairpin for a
                                                given IEEE802.1p priority i.
                                                0 means no buffer for this
                                                priority and traffic with this
                                                priority will be dropped.

""", '')
        mocked_execute2_return_value = ("""
Device #1:
----------

Device type:    ConnectX6
Name:           MCX654106A-HCA_Ax
Device:         0000:06:00.0

Configurations:                              Next Boot
         NUM_OF_VFS                          0
         SRIOV_EN                            False(0)
         PF_TOTAL_SF                         0
         ESWITCH_HAIRPIN_TOT_BUFFER_SIZE     Array[0..7]
""", '')
        mocked_execute.side_effect = [mocked_execute1_return_value,
                                      mocked_execute2_return_value]
        params = {"ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[8]": 16}
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, params)
        self.assertRaises(nvidia_fw_update.UnSupportedConfigByFW,
                          nvidia_nic_config.validate_config)
        calls = [mock.call('mstconfig', '-d',
                           nvidia_nic_config.nvidia_dev.dev_pci, 'i'),
                 mock.call('mstconfig', '-d',
                           nvidia_nic_config.nvidia_dev.dev_pci, 'q')]
        self.assertEqual(mocked_execute.call_args_list, calls)
        self.assertEqual(mocked_execute.call_count, 2)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_set_config(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"

        params = {"SRIOV_EN": True, "NUM_OF_VFS": 64, "PF_TOTAL_SF": 16,
                  "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[2]": 16}
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, params)
        nvidia_nic_config.device_conf_dict = {
            "NUM_OF_VFS": "0", "SRIOV_EN": "True(1)",
            "PF_TOTAL_SF": "0",
            "ESWITCH_HAIRPIN_TOT_BUFFER_SIZE": "Array[0..7]"}
        nvidia_nic_config.set_config()
        mocked_execute.assert_called_once_with(
            'mstconfig', '-d', nvidia_nic_config.nvidia_dev.dev_pci, '-y',
            'set',
            'NUM_OF_VFS=64',
            'PF_TOTAL_SF=16',
            'ESWITCH_HAIRPIN_TOT_BUFFER_SIZE[2]=16')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_set_config_exception(self, mocked_execute):
        mocked_nvidia_nic = mock.Mock()
        mocked_nvidia_nic.dev_pci.return_value = "0000:03:00.0"
        params = {"SRIOV_EN": "20"}
        nvidia_nic_config = nvidia_fw_update.NvidiaNicConfig(
            mocked_nvidia_nic, params)
        nvidia_nic_config.device_conf_dict = {"SRIOV_EN": "True(1)"}
        mocked_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaises(processutils.ProcessExecutionError,
                          nvidia_nic_config.set_config)
        mocked_execute.assert_called_once()


class TestNvidiaNicsConfig(base.IronicAgentTest):
    def setUp(self):
        super(TestNvidiaNicsConfig, self).setUp()

    def test_create_settings_map(self):
        mocked_nvidia_nics = mock.Mock()
        mocked_nvidia_nics.get_ids_list.return_value = {'101b', '1017'}
        settings = [{"deviceID": "1017",
                     "globalConfig": {"NUM_OF_VFS": 127, "SRIOV_EN": True},
                     "function0Config": {"PF_TOTAL_SF": 500},
                     "function1Config": {"PF_TOTAL_SF": 600}}]
        nvidia_nics_config = nvidia_fw_update.NvidiaNicsConfig(
            mocked_nvidia_nics, settings)
        nvidia_nics_config.create_settings_map()
        expected_settings_map = {
            '1017': {
                'deviceID': '1017',
                'function0Config': {'PF_TOTAL_SF': 500},
                'function1Config': {'PF_TOTAL_SF': 600},
                'globalConfig': {
                    'NUM_OF_VFS': 127,
                    'SRIOV_EN': True}}}
        self.assertEqual(nvidia_nics_config.settings_map,
                         expected_settings_map)

    def test_create_settings_map_duplicate_device_id(self):
        mocked_nvidia_nics = mock.Mock()
        mocked_nvidia_nics.get_ids_list.return_value = {'101b', '1017'}
        settings = [{"deviceID": "1017",
                     "globalConfig": {"NUM_OF_VFS": 127, "SRIOV_EN": True},
                     "function0Config": {"PF_TOTAL_SF": 500},
                     "function1Config": {"PF_TOTAL_SF": 600}},
                    {"deviceID": "1017",
                     "globalConfig": {"SRIOV_EN": False}}]
        nvidia_nics_config = nvidia_fw_update.NvidiaNicsConfig(
            mocked_nvidia_nics, settings)
        self.assertRaises(nvidia_fw_update.DuplicateDeviceID,
                          nvidia_nics_config.create_settings_map)

    def test_create_settings_map_invalid_firmware_settings_config(self):
        mocked_nvidia_nics = mock.Mock()
        mocked_nvidia_nics.get_ids_list.return_value = {'101b', '1017'}
        settings = [{"deviceID": "1017",
                     "globalConfig": {"NUM_OF_VFS": 127, "SRIOV_EN": True},
                     "function0Config": {"PF_TOTAL_SF": 500},
                     "function1Config": {"PF_TOTAL_SF": 600}},
                    {"device": "101b",
                     "globalConfig": {"SRIOV_EN": False}}]
        nvidia_nics_config = nvidia_fw_update.NvidiaNicsConfig(
            mocked_nvidia_nics, settings)
        self.assertRaises(nvidia_fw_update.InvalidFirmwareSettingsConfig,
                          nvidia_nics_config.create_settings_map)

    def test_prepare_nvidia_nic_config(self):
        mocked_nvidia_nic1 = mock.MagicMock()
        mocked_nvidia_nic1.dev_pci = "0000:03:00.0"
        mocked_nvidia_nic1.dev_id = '1017'
        mocked_nic1_devops = mock.MagicMock()
        mocked_nic1_devops.is_image_changed.return_value = True
        mocked_nvidia_nic1.dev_ops = mocked_nic1_devops

        mocked_nvidia_nic2 = mock.MagicMock()
        mocked_nvidia_nic2.dev_pci = "0000:03:00.1"
        mocked_nvidia_nic2.dev_id = '1017'
        mocked_nic2_devops = mock.MagicMock()
        mocked_nic2_devops.is_image_changed.return_value = True
        mocked_nvidia_nic2.dev_ops = mocked_nic2_devops

        mocked_nvidia_nic3 = mock.MagicMock()
        mocked_nvidia_nic3.dev_pci = "0000:06:00.0"
        mocked_nvidia_nic3.dev_id = '101b'
        mocked_nic3_devops = mock.MagicMock()
        mocked_nic3_devops.is_image_changed.return_value = False
        mocked_nvidia_nic3.dev_ops = mocked_nic3_devops

        mocked_nvidia_nics = mock.MagicMock()
        mocked_nvidia_nics.__iter__.return_value = [
            mocked_nvidia_nic1, mocked_nvidia_nic2, mocked_nvidia_nic3]

        mocked_nvidia_nics.get_ids_list.return_value = {'101b', '1017'}

        settings_map = {
            '1017': {
                'deviceID': '1017',
                'function0Config': {'PF_TOTAL_SF': 500},
                'function1Config': {'PF_TOTAL_SF': 600},
                'globalConfig': {
                    'NUM_OF_VFS': 127,
                    'SRIOV_EN': True}}}
        expected_nic1_params = {
            'PF_TOTAL_SF': 500, 'NUM_OF_VFS': 127, 'SRIOV_EN': True}
        expected_nic2_params = {'PF_TOTAL_SF': 600}
        nvidia_nics_config = nvidia_fw_update.NvidiaNicsConfig(
            mocked_nvidia_nics, [])
        nvidia_nics_config.settings_map = settings_map
        nvidia_nics_config.prepare_nvidia_nic_config()
        self.assertEqual(nvidia_nics_config._nvidia_nics_to_be_reset_list,
                         [mocked_nvidia_nic1])
        self.assertEqual(len(nvidia_nics_config._nvidia_nics_config_list), 2)
        return_config = {}
        for nvidia_nic_config in nvidia_nics_config._nvidia_nics_config_list:
            return_config[nvidia_nic_config.nvidia_dev] = \
                nvidia_nic_config.params
        self.assertEqual(return_config, {
            mocked_nvidia_nic1: expected_nic1_params,
            mocked_nvidia_nic2: expected_nic2_params})


class TestUpdateNvidiaNicFirmwareImage(base.IronicAgentTest):
    def setUp(self):
        super(TestUpdateNvidiaNicFirmwareImage, self).setUp()

    def test_update_nvidia_nic_firmware_image_exception(self):
        images = {}
        self.assertRaises(nvidia_fw_update.InvalidFirmwareImageConfig,
                          nvidia_fw_update.update_nvidia_nic_firmware_image,
                          images)


class TestUpdatenvidiaNicFirmwareSettings(base.IronicAgentTest):
    def setUp(self):
        super(TestUpdatenvidiaNicFirmwareSettings, self).setUp()

    def test_update_nvidia_nic_firmware_settings_exception(self):
        settings = {}
        self.assertRaises(
            nvidia_fw_update.InvalidFirmwareSettingsConfig,
            nvidia_fw_update.update_nvidia_nic_firmware_settings,
            settings)

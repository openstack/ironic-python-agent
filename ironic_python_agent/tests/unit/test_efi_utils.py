#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import shutil
import tempfile
from unittest import mock

from ironic_lib import disk_utils

from ironic_python_agent import efi_utils
from ironic_python_agent import errors
from ironic_python_agent import partition_utils
from ironic_python_agent.tests.unit import base
from ironic_python_agent import utils


@mock.patch.object(os, 'walk', autospec=True)
@mock.patch.object(os, 'access', autospec=False)
class TestGetEfiBootloaders(base.IronicAgentTest):

    def test__no_efi_bootloaders(self, mock_access, mock_walk):
        # No valid efi file.
        mock_walk.return_value = [
            ('/boot/efi', ['EFI'], []),
            ('/boot/efi/EFI', ['centos', 'BOOT'], []),
            ('/boot/efi/EFI/centos', ['fw', 'fonts'],
             ['shimx64-centos.efi',
              'MokManager.efi', 'mmx64.efi', 'shim.efi', 'fwupia32.efi',
              'fwupx64.efi', 'shimx64.efi', 'grubenv', 'grubx64.efi',
              'grub.cfg']),
            ('/boot/efi/EFI/centos/fw', [], []),
            ('/boot/efi/EFI/centos/fonts', [], ['unicode.pf2']),
            ('/boot/efi/EFI/BOOT', [], [])
        ]

        result = efi_utils._get_efi_bootloaders("/boot/efi")
        self.assertEqual(result, [])
        mock_access.assert_not_called()

    def test__get_efi_bootloaders(self, mock_access, mock_walk):
        mock_walk.return_value = [
            ('/boot/efi', ['EFI'], []),
            ('/boot/efi/EFI', ['centos', 'BOOT'], []),
            ('/boot/efi/EFI/centos', ['fw', 'fonts'],
             ['shimx64-centos.efi', 'BOOTX64.CSV',
              'MokManager.efi', 'mmx64.efi', 'shim.efi', 'fwupia32.efi',
              'fwupx64.efi', 'shimx64.efi', 'grubenv', 'grubx64.efi',
              'grub.cfg']),
            ('/boot/efi/EFI/centos/fw', [], []),
            ('/boot/efi/EFI/centos/fonts', [], ['unicode.pf2']),
            ('/boot/efi/EFI/BOOT', [],
             ['BOOTX64.EFI', 'fallback.efi', 'fbx64.efi'])
        ]
        mock_access.return_value = True
        result = efi_utils._get_efi_bootloaders("/boot/efi")
        self.assertEqual(result[0], 'EFI/centos/BOOTX64.CSV')

    def test__get_efi_bootloaders_no_csv(self, mock_access, mock_walk):
        mock_walk.return_value = [
            ('/boot/efi', ['EFI'], []),
            ('/boot/efi/EFI', ['centos', 'BOOT'], []),
            ('/boot/efi/EFI/centos', ['fw', 'fonts'],
             ['shimx64-centos.efi',
              'MokManager.efi', 'mmx64.efi', 'shim.efi', 'fwupia32.efi',
              'fwupx64.efi', 'shimx64.efi', 'grubenv', 'grubx64.efi',
              'grub.cfg']),
            ('/boot/efi/EFI/centos/fw', [], []),
            ('/boot/efi/EFI/centos/fonts', [], ['unicode.pf2']),
            ('/boot/efi/EFI/BOOT', [],
             ['BOOTX64.EFI', 'fallback.efi', 'fbx64.efi'])
        ]
        mock_access.return_value = True
        result = efi_utils._get_efi_bootloaders("/boot/efi")
        self.assertEqual(result[0], 'EFI/BOOT/BOOTX64.EFI')

    def test__get_windows_efi_bootloaders(self, mock_access, mock_walk):
        mock_walk.return_value = [
            ('/boot/efi', ['WINDOWS'], []),
            ('/boot/efi/WINDOWS', ['system32'], []),
            ('/boot/efi/WINDOWS/system32', [],
             ['winload.efi'])
        ]
        mock_access.return_value = True
        result = efi_utils._get_efi_bootloaders("/boot/efi")
        self.assertEqual(result[0], 'WINDOWS/system32/winload.efi')


@mock.patch.object(utils, 'execute', autospec=True)
class TestRunEfiBootmgr(base.IronicAgentTest):

    fake_dev = '/dev/fake'
    fake_efi_system_part = '/dev/fake1'
    fake_dir = '/tmp/fake-dir'

    def test__run_efibootmgr_no_bootloaders(self, mock_execute):
        result = efi_utils._run_efibootmgr([], self.fake_dev,
                                           self.fake_efi_system_part,
                                           self.fake_dir)
        expected = []
        self.assertIsNone(result)
        mock_execute.assert_has_calls(expected)

    def test__run_efibootmgr(self, mock_execute):
        mock_execute.return_value = ('', '')
        result = efi_utils._run_efibootmgr(['EFI/BOOT/BOOTX64.EFI'],
                                           self.fake_dev,
                                           self.fake_efi_system_part,
                                           self.fake_dir)
        expected = [mock.call('efibootmgr', '-v'),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', self.fake_efi_system_part, '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI')]
        self.assertIsNone(result)
        mock_execute.assert_has_calls(expected)


@mock.patch.object(shutil, 'rmtree', lambda *_: None)
@mock.patch.object(tempfile, 'mkdtemp', lambda *_: '/tmp/fake-dir')
@mock.patch.object(utils, 'rescan_device', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
@mock.patch.object(partition_utils, 'get_partition', autospec=True)
@mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
class TestManageUefi(base.IronicAgentTest):

    fake_dev = '/dev/fake'
    fake_efi_system_part = '/dev/fake1'
    fake_root_part = '/dev/fake2'
    fake_root_uuid = '11111111-2222-3333-4444-555555555555'
    fake_dir = '/tmp/fake-dir'

    def test_no_partition(self, mock_utils_efi_part,
                          mock_get_part_uuid, mock_execute,
                          mock_rescan):
        mock_utils_efi_part.return_value = None
        self.assertRaises(errors.DeviceNotFound,
                          efi_utils.manage_uefi, self.fake_dev, None)
        self.assertFalse(mock_get_part_uuid.called)
        mock_rescan.assert_called_once_with(self.fake_dev)

    def test_empty_partition_by_uuid(self, mock_utils_efi_part,
                                     mock_get_part_uuid, mock_execute,
                                     mock_rescan):
        mock_utils_efi_part.return_value = None
        mock_get_part_uuid.return_value = self.fake_root_part
        result = efi_utils.manage_uefi(self.fake_dev, self.fake_root_uuid)
        self.assertFalse(result)
        mock_rescan.assert_called_once_with(self.fake_dev)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_ok(self, mkdir_mock, mock_efi_bl, mock_utils_efi_part,
                mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_uuid.return_value = self.fake_dev

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']

        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v'),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI'),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        result = efi_utils.manage_uefi(self.fake_dev, self.fake_root_uuid)
        self.assertTrue(result)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        self.assertEqual(5, mock_execute.call_count)
        mock_rescan.assert_called_once_with(self.fake_dev)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_found_csv(self, mkdir_mock, mock_efi_bl, mock_utils_efi_part,
                       mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_uuid.return_value = self.fake_dev
        mock_efi_bl.return_value = ['EFI/vendor/BOOTX64.CSV']

        # Format is <file>,<entry_name>,<options>,humanfriendlytextnotused
        # https://www.rodsbooks.com/efi-bootloaders/fallback.html
        # Mild difference, Ubuntu ships a file without a 0xFEFF delimiter
        # at the start of the file, where as Red Hat *does*
        csv_file_data = u'shimx64.efi,Vendor String,,Grub2MadeUSDoThis\n'
        # This test also handles deleting a pre-existing matching vendor
        # string in advance.
        dupe_entry = """
BootCurrent: 0001
Timeout: 0 seconds
BootOrder: 0000,00001
Boot0000* Vendor String HD(1,GPT,4f3c6294-bf9b-4208-9808-be45dfc34b5c)File(\EFI\Boot\BOOTX64.EFI)
Boot0001 Vendor String HD(2,GPT,4f3c6294-bf9b-4208-9808-be45dfc34b5c)File(\EFI\Boot\BOOTX64.EFI)
Boot0002: VENDMAGIC FvFile(9f3c6294-bf9b-4208-9808-be45dfc34b51)
"""  # noqa This is a giant literal string for testing.

        mock_execute.side_effect = iter([('', ''), (dupe_entry, ''),
                                         ('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v'),
                    mock.call('efibootmgr', '-b', '0000', '-B'),
                    mock.call('efibootmgr', '-b', '0001', '-B'),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'Vendor String', '-l',
                              '\\EFI\\vendor\\shimx64.efi'),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]
        with mock.patch('builtins.open',
                        mock.mock_open(read_data=csv_file_data)):
            result = efi_utils.manage_uefi(self.fake_dev, self.fake_root_uuid)
        self.assertTrue(result)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_nvme_device(self, mkdir_mock, mock_efi_bl, mock_utils_efi_part,
                         mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_uuid.return_value = '/dev/fakenvme0p1'

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']

        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', '/dev/fakenvme0p1',
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v'),
                    mock.call('efibootmgr', '-v', '-c', '-d', '/dev/fakenvme0',
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI'),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        result = efi_utils.manage_uefi('/dev/fakenvme0', self.fake_root_uuid)
        self.assertTrue(result)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_wholedisk(self, mkdir_mock, mock_efi_bl, mock_utils_efi_part,
                       mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_uuid.side_effect = Exception

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']

        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v'),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI'),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        result = efi_utils.manage_uefi(self.fake_dev, None)
        self.assertTrue(result)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)

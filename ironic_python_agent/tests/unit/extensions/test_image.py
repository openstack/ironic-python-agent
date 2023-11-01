# Copyright 2015 Red Hat, Inc.
# All Rights Reserved.
#
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

from ironic_lib import utils as ilib_utils
from oslo_concurrency import processutils

from ironic_python_agent import disk_utils
from ironic_python_agent import efi_utils
from ironic_python_agent import errors
from ironic_python_agent.extensions import image
from ironic_python_agent import hardware
from ironic_python_agent import partition_utils
from ironic_python_agent import raid_utils
from ironic_python_agent.tests.unit import base
from ironic_python_agent.tests.unit.samples import hardware_samples as hws


EFI_RESULT = ''.encode('utf-16')


@mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
@mock.patch.object(ilib_utils, 'execute', autospec=True)
@mock.patch.object(tempfile, 'mkdtemp', lambda *_: '/tmp/fake-dir')
@mock.patch.object(shutil, 'rmtree', lambda *_: None)
class TestImageExtension(base.IronicAgentTest):

    def setUp(self):
        super(TestImageExtension, self).setUp()
        self.agent_extension = image.ImageExtension()
        self.fake_dev = '/dev/fake'
        self.fake_efi_system_part = '/dev/fake1'
        self.fake_root_part = '/dev/fake2'
        self.fake_prep_boot_part = '/dev/fake3'
        self.fake_root_uuid = '11111111-2222-3333-4444-555555555555'
        self.fake_efi_system_part_uuid = '45AB-2312'
        self.fake_prep_boot_part_uuid = '76937797-3253-8843-999999999999'
        self.fake_dir = '/tmp/fake-dir'

    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_bios(self, mock_grub2,
                                      mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='bios')
        ]
        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid).join()
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        mock_grub2.assert_called_once_with(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None, prep_boot_part_uuid=None,
            target_boot_mode='bios'
        )

    @mock.patch.object(efi_utils, 'manage_uefi', autospec=True)
    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_uefi(self, mock_grub2, mock_uefi,
                                      mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_uefi.return_value = False
        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi'
        ).join()
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        mock_grub2.assert_called_once_with(
            self.fake_dev,
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            prep_boot_part_uuid=None,
            target_boot_mode='uefi'
        )

    @mock.patch.object(efi_utils, 'manage_uefi', autospec=True)
    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_uefi_ignores_manage_failure(
            self, mock_grub2, mock_uefi,
            mock_execute, mock_dispatch):
        self.config(ignore_bootloader_failure=True)
        mock_uefi.side_effect = OSError('meow')
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_uefi.return_value = False
        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi'
        ).join()
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        mock_grub2.assert_called_once_with(
            self.fake_dev,
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            prep_boot_part_uuid=None,
            target_boot_mode='uefi'
        )

    @mock.patch.object(efi_utils, 'manage_uefi', autospec=True)
    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_uefi_ignores_grub_failure(
            self, mock_grub2, mock_uefi,
            mock_execute, mock_dispatch):
        self.config(ignore_bootloader_failure=True)
        mock_grub2.side_effect = OSError('meow')
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_uefi.return_value = False
        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi'
        ).join()
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        mock_grub2.assert_called_once_with(
            self.fake_dev,
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            prep_boot_part_uuid=None,
            target_boot_mode='uefi'
        )

    @mock.patch.object(efi_utils, 'manage_uefi', autospec=True)
    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_uefi_ignores_grub_failure_api_override(
            self, mock_grub2, mock_uefi,
            mock_execute, mock_dispatch):
        self.config(ignore_bootloader_failure=False)
        mock_grub2.side_effect = OSError('meow')
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_uefi.return_value = False
        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi', ignore_bootloader_failure=True,
        ).join()
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        mock_grub2.assert_called_once_with(
            self.fake_dev,
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            prep_boot_part_uuid=None,
            target_boot_mode='uefi'
        )

    @mock.patch.object(efi_utils, 'manage_uefi', autospec=True)
    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_uefi_grub_failure_api_override(
            self, mock_grub2, mock_uefi,
            mock_execute, mock_dispatch):
        self.config(ignore_bootloader_failure=True)
        mock_grub2.side_effect = OSError('meow')
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_uefi.return_value = False
        result = self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi', ignore_bootloader_failure=False,
        ).join()
        self.assertIsNotNone(result.command_error)
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        mock_grub2.assert_called_once_with(
            self.fake_dev,
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            prep_boot_part_uuid=None,
            target_boot_mode='uefi'
        )

    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_no_root(self, mock_grub2,
                                         mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='bios')
        ]
        self.agent_extension.install_bootloader(
            root_uuid='0x00000000').join()
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        self.assertFalse(mock_grub2.called)

    @mock.patch.object(hardware, 'is_md_device', lambda *_: False)
    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    @mock.patch.object(disk_utils, 'find_efi_partition', autospec=False)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test__uefi_bootloader_given_partition(
            self, mkdir_mock, mock_utils_efi_part, mock_get_partition,
            mock_efi_bl, mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_get_partition.return_value = self.fake_efi_system_part
        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        mock_utils_efi_part.return_value = None

        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         (EFI_RESULT, ''), (EFI_RESULT, ''),
                                         ('', ''), ('', '')])

        expected = [mock.call('efibootmgr', '--version'),
                    mock.call('partx', '-av', '/dev/fake', attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid).join()

        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_utils_efi_part.assert_called_once_with(self.fake_dev)
        self.assertEqual(8, mock_execute.call_count)

    @mock.patch.object(hardware, 'is_md_device', lambda *_: False)
    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(efi_utils, 'get_partition_path_by_number',
                       autospec=True)
    @mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test__uefi_bootloader_find_partition(
            self, mkdir_mock, mock_utils_efi_part, mock_get_part_path,
            mock_efi_bl, mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         (EFI_RESULT, ''), (EFI_RESULT, ''),
                                         ('', ''), ('', '')])

        expected = [mock.call('efibootmgr', '--version'),
                    mock.call('partx', '-av', '/dev/fake', attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None).join()

        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_utils_efi_part.assert_called_once_with(self.fake_dev)
        self.assertEqual(8, mock_execute.call_count)

    @mock.patch.object(hardware, 'is_md_device', lambda *_: False)
    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(efi_utils, 'get_partition_path_by_number',
                       autospec=True)
    @mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test__uefi_bootloader_with_entry_removal(
            self, mkdir_mock, mock_utils_efi_part, mock_get_part_path,
            mock_efi_bl, mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        stdout_msg = """
BootCurrent: 0001
Timeout: 0 seconds
BootOrder: 0000,00001
Boot0000 ironic1 HD(1,GPT,4f3c6294-bf9b-4208-9808-be45dfc34b5c)File(\EFI\Boot\BOOTX64.EFI)
Boot0001 ironic2 HD(1,GPT,4f3c6294-bf9b-4208-9808-111111111112)File(\EFI\Boot\BOOTX64.EFI)
Boot0002 VENDMAGIC FvFile(9f3c6294-bf9b-4208-9808-be45dfc34b51)
"""  # noqa This is a giant literal string for testing.
        stdout_msg = stdout_msg.encode('utf-16')
        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         (stdout_msg, ''), (EFI_RESULT, ''),
                                         (EFI_RESULT, ''), (EFI_RESULT, ''),
                                         ('', ''), ('', '')])

        expected = [mock.call('efibootmgr', '--version'),
                    mock.call('partx', '-av', '/dev/fake', attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-b', '0000', '-B', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None).join()

        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_utils_efi_part.assert_called_once_with(self.fake_dev)
        self.assertEqual(9, mock_execute.call_count)

    @mock.patch.object(hardware, 'is_md_device', lambda *_: False)
    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(efi_utils, 'get_partition_path_by_number',
                       autospec=True)
    @mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test__uefi_bootloader_with_entry_removal_lenovo(
            self, mkdir_mock, mock_utils_efi_part, mock_get_part_path,
            mock_efi_bl, mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        # NOTE(TheJulia): This test string was derived from a lenovo SR650
        # which does do some weird things with additional entries.
        # most notably
        stdout_msg = """
BootCurrent: 0000
Timeout: 1 seconds
BootOrder: 0000,0003,0002,0001
Boot0000* ironic1       HD(1,GPT,55db8d03-c8f6-4a5b-9155-790dddc348fa,0x800,0x64000)/File(\EFI\boot\shimx64.efi)
Boot0001* CD/DVD Rom    VenHw(1fad3248-0000-7950-2166-a1e506fdb83a,02000000)..GO
Boot0002* Hard Disk     VenHw(1fad3248-0000-7950-2166-a1e506fdb83a,01000000)..GO..NO..........V.U.E.F.I.:. . . .S.C.S.I. .H.a.r.d. .D.r.i.v.e........A....................................*..............@.........U..[J.Uy...H.......BO
Boot0003* Network       VenHw(1fad3248-0000-7950-2166-a1e506fdb83a,05000000)..GO..NO............U.E.F.I.:. . . .S.L.O.T.2. .(.2.F./.0./.0.). .P.X.E. .I.P.4. . .Q.L.o.g.i.c. .Q.L.4.1.2.6.2. .P.C.I.e. .2.5.G.b. .2.-.P.o.r.t. .S.F.P.2.8. .E.t.h.e.r.n.e.t. .A.d.a.p.t.e.r. .-. .P.X.E........A....................%.4..Z...............................................................Gd-.;.A..MQ..L.P.X.E. .I.P.4. .Q.L.o.g.i.c. .Q.L.4.1.2.6.2. .P.C.I.e. .2.5.G.b. .2.-.P.o.r.t. .S.F.P.2.8. .E.t.h.e.r.n.e.t. .A.d.a.p.t.e.r. .-. .P.X.E.......BO..NO............U.E.F.I.:. . . .S.L.O.T.1. .(.3.0./.0./.0.). .P.X.E. .I.P.4. . .Q.L.o.g.i.c. .Q.L.4.1.2.6.2. .P.C.I.e. .2.5.G.b. .2.-.P.o.r.t. .S.F.P.2.8. .E.t.h.e.r.n.e.t. .A.d.a.p.t.e.r. .-.
Boot0004* ironic1      HD(1,GPT,55db8d03-c8f6-4a5b-9155-790dddc348fa,0x800,0x64000)/File(\EFI\boot\shimx64.efi)
"""  # noqa This is a giant literal string for testing.
        stdout_msg = stdout_msg.encode('utf-16')
        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         (stdout_msg, ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', ''), ('', '')])
        expected = [mock.call('efibootmgr', '--version'),
                    mock.call('partx', '-av', '/dev/fake', attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-b', '0000', '-B', binary=True),
                    mock.call('efibootmgr', '-b', '0004', '-B', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None).join()

        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_utils_efi_part.assert_called_once_with(self.fake_dev)
        self.assertEqual(10, mock_execute.call_count)

    @mock.patch.object(hardware, 'is_md_device', lambda *_: False)
    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(efi_utils, 'get_partition_path_by_number',
                       autospec=True)
    @mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test__add_multi_bootloaders(
            self, mkdir_mock, mock_utils_efi_part, mock_get_part_path,
            mock_efi_bl, mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI',
                                    'WINDOWS/system32/winload.efi']

        mock_execute.side_effect = iter([('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         (EFI_RESULT, ''), (EFI_RESULT, ''),
                                         (EFI_RESULT, ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('efibootmgr', '--version'),
                    mock.call('partx', '-av', '/dev/fake', attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic2', '-l',
                              '\\WINDOWS\\system32\\winload.efi', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None).join()

        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_utils_efi_part.assert_called_once_with(self.fake_dev)
        self.assertEqual(9, mock_execute.call_count)

    @mock.patch.object(image, '_install_grub2', autospec=True)
    def test__install_bootloader_prep(self, mock_grub2,
                                      mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='bios')
        ]
        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None,
            prep_boot_part_uuid=self.fake_prep_boot_part_uuid).join()
        mock_dispatch.assert_any_call('get_os_install_device')
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(2, mock_dispatch.call_count)
        mock_grub2.assert_called_once_with(
            self.fake_dev,
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None,
            prep_boot_part_uuid=self.fake_prep_boot_part_uuid,
            target_boot_mode='bios'
        )

    @mock.patch.object(hardware, 'is_md_device', lambda *_: False)
    @mock.patch.object(os.path, 'exists', lambda *_: False)
    def test_install_bootloader_failure(self, mock_execute, mock_dispatch):
        mock_dispatch.side_effect = [
            self.fake_dev, hardware.BootInfo(current_boot_mode='uefi')
        ]
        mock_execute.side_effect = FileNotFoundError
        result = self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None).join()
        self.assertIsNotNone(result.command_error)
        expected = [mock.call('efibootmgr', '--version')]
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(os.path, 'exists', lambda *_: True)
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2(self, mock_get_part_uuid, environ_mock,
                            mock_md_get_raid_devices, mock_is_md_device,
                            mock_append_to_fstab, mock_execute,
                            mock_dispatch):
        mock_get_part_uuid.return_value = self.fake_root_part
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        image._install_grub2(self.fake_dev, self.fake_root_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub2-install %s"' %
                               (self.fake_dir, self.fake_dev)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_called_once_with(self.fake_dev,
                                                   uuid=self.fake_root_uuid)
        self.assertFalse(mock_dispatch.called)
        self.assertFalse(mock_append_to_fstab.called)

    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_prep(self, mock_get_part_uuid, environ_mock,
                                 mock_md_get_raid_devices, mock_is_md_device,
                                 mock_execute, mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_prep_boot_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        image._install_grub2(self.fake_dev, self.fake_root_uuid,
                             prep_boot_part_uuid=self.fake_prep_boot_part_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub-install %s"' %
                               (self.fake_dir, self.fake_prep_boot_part)),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub-mkconfig -o '
                               '/boot/grub/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_prep_boot_part_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(os.path, 'ismount', lambda *_: False)
    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: True)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi(self, mock_get_part_uuid, mkdir_mock,
                                 environ_mock, mock_md_get_raid_devices,
                                 mock_is_md_device, mock_append_to_fstab,
                                 mock_execute, mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub-install --removable"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(
                        'umount', self.fake_dir + '/boot/efi',
                        attempts=3, delay_on_retry=True),
                    mock.call('mount', self.fake_efi_system_part,
                              '/tmp/fake-dir/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub-mkconfig -o '
                               '/boot/grub/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)
        mock_append_to_fstab.assert_called_with(self.fake_dir,
                                                self.fake_efi_system_part_uuid)

    @mock.patch.object(hardware, 'get_multipath_status', lambda *_: False)
    @mock.patch.object(os.path, 'ismount', lambda *_: False)
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_fstab(self, mock_get_part_uuid, mkdir_mock,
                                       environ_mock, mock_md_get_raid_devices,
                                       mock_is_md_device, mock_exists,
                                       mock_execute, mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        mock_exists.side_effect = iter([False, True, False, True, True])
        mock_execute.return_value = (hws.PARTUUID_DEVICE_TEMPLATE, '')

        with mock.patch('builtins.open', mock.mock_open()) as mock_open:
            image._install_grub2(
                self.fake_dev, root_uuid=self.fake_root_uuid,
                efi_system_part_uuid=self.fake_efi_system_part_uuid,
                target_boot_mode='uefi')
            write_calls = [
                mock.call(self.fake_dir + '/etc/fstab', 'r+'),
                mock.call().__enter__(),
                mock.call().read(),
                mock.call().writelines('UUID=%s\t/boot/efi\tvfat\t'
                                       'umask=0077\t0\t1'
                                       '\n' % self.fake_efi_system_part_uuid),
                mock.call().__exit__(None, None, None)]
            mock_open.assert_has_calls(write_calls)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub2-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub2-install --removable"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(
                        'umount', self.fake_dir + '/boot/efi',
                        attempts=3, delay_on_retry=True),
                    mock.call('mount', self.fake_efi_system_part,
                              '/tmp/fake-dir/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('lsblk', '-bia', '--json',
                              '-oKNAME,MODEL,SIZE,ROTA,'
                              + 'TYPE,UUID,PARTUUID,SERIAL,WWN',
                              check_exit_code=[0]),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(hardware, 'get_multipath_status', lambda *_: False)
    @mock.patch.object(image, '_efi_boot_setup', lambda *_: False)
    @mock.patch.object(os.path, 'ismount', lambda *_: False)
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_no_fstab(
            self, mock_get_part_uuid,
            mkdir_mock,
            environ_mock, mock_md_get_raid_devices,
            mock_is_md_device, mock_exists,
            mock_execute, mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        mock_execute.return_value = (hws.PARTUUID_DEVICE_TEMPLATE, '')
        # Validates the complete opposite path *and* no-write behavior
        # occurs if the entry already exists.
        fstab_data = (
            'PARTUUID=%s\tpath vfat option' % self.fake_efi_system_part_uuid)
        mock_exists.side_effect = [True, False, True, True, True, False,
                                   True, True]
        with mock.patch('builtins.open',
                        mock.mock_open(read_data=fstab_data)) as mock_open:
            image._install_grub2(
                self.fake_dev, root_uuid=self.fake_root_uuid,
                efi_system_part_uuid=self.fake_efi_system_part_uuid,
                target_boot_mode='uefi')
            write_calls = [
                mock.call(self.fake_dir + '/etc/fstab', 'r+'),
                mock.call().__enter__(),
                mock.call().read(),
                mock.call().__exit__(None, None, None)]
            mock_open.assert_has_calls(write_calls)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('umount', self.fake_dir + '/boot/efi'),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    # NOTE(TheJulia): chroot mount is for whole disk images
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub2-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub2-install --removable"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(
                        'umount', self.fake_dir + '/boot/efi',
                        attempts=3, delay_on_retry=True),
                    mock.call('mount', self.fake_efi_system_part,
                              '/tmp/fake-dir/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('lsblk', '-bia', '--json',
                              '-oKNAME,MODEL,SIZE,ROTA,'
                              + 'TYPE,UUID,PARTUUID,SERIAL,WWN',
                              check_exit_code=[0]),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(os.path, 'ismount', lambda *_: False)
    @mock.patch.object(os, 'listdir', lambda *_: ['file1', 'file2'])
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(image, '_efi_boot_setup', autospec=True)
    @mock.patch.object(shutil, 'copytree', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_partition_image_with_loader(
            self, mock_get_part_uuid, mkdir_mock,
            environ_mock, mock_md_get_raid_devices,
            mock_is_md_device, mock_exists,
            mock_copytree, mock_efi_setup,
            mock_append_to_fstab, mock_execute,
            mock_dispatch):
        mock_exists.side_effect = [True, False, True, True, True, False, True,
                                   False, False]
        mock_efi_setup.return_value = True
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')
        mock_efi_setup.assert_called_once_with(self.fake_dev,
                                               self.fake_efi_system_part_uuid)
        mock_copytree.assert_has_calls([
            mock.call(self.fake_dir + '/boot/efi/EFI',
                      self.fake_dir + '/efi_loader'),
            mock.call(self.fake_dir + '/efi_loader',
                      self.fake_dir + '/boot/efi/EFI')])

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call('chroot %s /bin/sh -c "grub2-mkconfig -o '
                              '/boot/grub2/grub.cfg"' % self.fake_dir,
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('mount', '-t', 'vfat', '/dev/fake1',
                              self.fake_dir + '/boot/efi'),
                    mock.call('umount', self.fake_dir + '/boot/efi'),
                    mock.call('chroot %s /bin/sh -c "umount -a -t '
                              'vfat"' % self.fake_dir, shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mkdir_mock.assert_not_called()
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)
        mock_append_to_fstab.assert_called_with(self.fake_dir,
                                                self.fake_efi_system_part_uuid)

    @mock.patch.object(os, 'listdir', lambda *_: ['file1', 'file2'])
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(shutil, 'copy2', autospec=True)
    @mock.patch.object(os.path, 'isfile', autospec=True)
    @mock.patch.object(image, '_efi_boot_setup', autospec=True)
    @mock.patch.object(shutil, 'copytree', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_partition_image_with_loader_with_grubcfg(
            self, mock_get_part_uuid, mkdir_mock,
            environ_mock, mock_md_get_raid_devices,
            mock_is_md_device, mock_exists,
            mock_copytree, mock_efi_setup,
            mock_isfile, mock_copy2,
            mock_fstab_append, mock_execute,
            mock_dispatch):
        mock_exists.return_value = True
        mock_efi_setup.return_value = True
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        mock_isfile.side_effect = [True, False, False, True, True, False]

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')
        mock_efi_setup.assert_called_once_with(self.fake_dev,
                                               self.fake_efi_system_part_uuid)
        mock_copytree.assert_has_calls([
            mock.call(self.fake_dir + '/boot/efi/EFI',
                      self.fake_dir + '/efi_loader'),
            mock.call(self.fake_dir + '/efi_loader',
                      self.fake_dir + '/boot/efi/EFI')])

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot ' + self.fake_dir + ' /bin/sh -c '
                               '"grub2-mkconfig -o /boot/grub2/grub.cfg"'),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('mount', '-t', 'vfat', '/dev/fake1',
                              self.fake_dir + '/boot/efi'),
                    mock.call('umount', self.fake_dir + '/boot/efi'),
                    mock.call(('chroot ' + self.fake_dir
                               + ' /bin/sh -c "umount -a -t vfat"'),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mkdir_mock.assert_not_called()
        mock_execute.assert_has_calls(expected)
        mock_copy2.assert_has_calls([])
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        mock_fstab_append.assert_called_once_with(
            self.fake_dir,
            self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(os.path, 'ismount', lambda *_: False)
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(image, '_preserve_efi_assets', autospec=True)
    @mock.patch.object(image, '_efi_boot_setup', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_partition_image_with_preserve_failure(
            self, mock_get_part_uuid, mkdir_mock,
            environ_mock, mock_md_get_raid_devices,
            mock_is_md_device, mock_exists,
            mock_efi_setup,
            mock_preserve_efi_assets,
            mock_append_to_fstab,
            mock_execute, mock_dispatch):
        mock_exists.return_value = True
        mock_efi_setup.side_effect = Exception('meow')
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        mock_preserve_efi_assets.return_value = False

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')
        self.assertFalse(mock_efi_setup.called)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub2-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub2-install --removable"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(
                        'umount', self.fake_dir + '/boot/efi',
                        attempts=3, delay_on_retry=True),
                    mock.call('mount', self.fake_efi_system_part,
                              '/tmp/fake-dir/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]

        mkdir_mock.assert_not_called()
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)
        mock_preserve_efi_assets.assert_called_with(
            self.fake_dir,
            self.fake_dir + '/boot/efi/EFI',
            '/dev/fake1',
            self.fake_dir + '/boot/efi')
        mock_append_to_fstab.assert_called_with(self.fake_dir,
                                                self.fake_efi_system_part_uuid)

    @mock.patch.object(os.path, 'ismount', lambda *_: False)
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(image, '_preserve_efi_assets', autospec=True)
    @mock.patch.object(image, '_efi_boot_setup', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_partition_image_with_preserve_failure2(
            self, mock_get_part_uuid, mkdir_mock,
            environ_mock, mock_md_get_raid_devices,
            mock_is_md_device, mock_exists,
            mock_efi_setup,
            mock_preserve_efi_assets,
            mock_append_to_fstab,
            mock_execute, mock_dispatch):
        mock_exists.return_value = True
        mock_efi_setup.side_effect = Exception('meow')
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        mock_preserve_efi_assets.return_value = None
        exec_results = [('', '')] * 21
        already_exists = processutils.ProcessExecutionError(
            '/dev is already mounted at /path')
        # Mark mounts as already mounted, which is where os.path.ismount
        # usage corresponds.
        exec_results[6] = already_exists
        exec_results[8] = already_exists

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')
        self.assertFalse(mock_efi_setup.called)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub2-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub2-install --removable"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(
                        'umount', self.fake_dir + '/boot/efi',
                        attempts=3, delay_on_retry=True),
                    mock.call('mount', self.fake_efi_system_part,
                              '/tmp/fake-dir/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]

        mkdir_mock.assert_not_called()
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)
        mock_preserve_efi_assets.assert_called_with(
            self.fake_dir,
            self.fake_dir + '/boot/efi/EFI',
            '/dev/fake1',
            self.fake_dir + '/boot/efi')
        mock_append_to_fstab.assert_called_with(self.fake_dir,
                                                self.fake_efi_system_part_uuid)

    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(shutil, 'copy2', autospec=True)
    @mock.patch.object(os.path, 'isfile', autospec=True)
    @mock.patch.object(image, '_efi_boot_setup', autospec=True)
    @mock.patch.object(shutil, 'copytree', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_partition_image_with_loader_grubcfg_fails(
            self, mock_get_part_uuid, mkdir_mock,
            environ_mock, mock_md_get_raid_devices,
            mock_is_md_device, mock_exists,
            mock_copytree, mock_efi_setup,
            mock_isfile, mock_copy2,
            mock_oslistdir, mock_append_to_fstab,
            mock_execute, mock_dispatch):
        mock_exists.return_value = True
        mock_efi_setup.return_value = True
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}
        mock_isfile.side_effect = [True, False, False, True, False,
                                   True, False]
        mock_copy2.side_effect = OSError('copy failed')
        mock_oslistdir.return_value = ['file1', 'file2']

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')
        mock_efi_setup.assert_called_once_with(self.fake_dev,
                                               self.fake_efi_system_part_uuid)
        mock_copytree.assert_has_calls([
            mock.call(self.fake_dir + '/boot/efi/EFI',
                      self.fake_dir + '/efi_loader'),
            mock.call(self.fake_dir + '/efi_loader',
                      self.fake_dir + '/boot/efi/EFI')])

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot ' + self.fake_dir + ' /bin/sh -c '
                               '"grub2-mkconfig -o /boot/grub2/grub.cfg"'),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('mount', '-t', 'vfat', '/dev/fake1',
                              self.fake_dir + '/boot/efi'),
                    mock.call('umount', self.fake_dir + '/boot/efi'),
                    mock.call(('chroot ' + self.fake_dir
                               + ' /bin/sh -c "umount -a -t vfat"'),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys', attempts=3,
                              delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mkdir_mock.assert_not_called()
        mock_execute.assert_has_calls(expected)
        self.assertEqual(3, mock_copy2.call_count)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)
        self.assertEqual(2, mock_oslistdir.call_count)
        mock_append_to_fstab.assert_called_with(self.fake_dir,
                                                self.fake_efi_system_part_uuid)

    @mock.patch.object(os.path, 'ismount', lambda *_: False)
    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(image, '_append_uefi_to_fstab', autospec=True)
    @mock.patch.object(image, '_efi_boot_setup', autospec=True)
    @mock.patch.object(shutil, 'copytree', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_partition_image_with_no_loader(
            self, mock_get_part_uuid, mkdir_mock,
            environ_mock, mock_md_get_raid_devices,
            mock_is_md_device, mock_exists,
            mock_copytree, mock_efi_setup,
            mock_append_to_fstab, mock_oslistdir,
            mock_execute, mock_dispatch):
        mock_exists.side_effect = [True, False, False, True, True, True, True]
        mock_efi_setup.side_effect = Exception('meow')
        mock_oslistdir.return_value = ['file1']
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call('mount', '-t', 'vfat', '/dev/fake1',
                              self.fake_dir + '/boot/efi'),
                    mock.call('umount', self.fake_dir + '/boot/efi'),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub2-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub2-install --removable"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(
                        'umount', self.fake_dir + '/boot/efi',
                        attempts=3, delay_on_retry=True),
                    mock.call('mount', self.fake_efi_system_part,
                              '/tmp/fake-dir/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub2-mkconfig -o '
                               '/boot/grub2/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]

        mkdir_mock.assert_not_called()
        mock_execute.assert_has_calls(expected)
        self.assertEqual(2, mock_copytree.call_count)
        self.assertTrue(mock_efi_setup.called)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)
        mock_append_to_fstab.assert_called_with(self.fake_dir,
                                                self.fake_efi_system_part_uuid)

    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_umount_fails(
            self, mock_get_part_uuid, mkdir_mock, environ_mock,
            mock_md_get_raid_devices, mock_is_md_device, mock_execute,
            mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        mock_is_md_device.return_value = False
        mock_md_get_raid_devices.return_value = {}

        def umount_raise_func(*args, **kwargs):
            if args[0] == 'umount':
                raise processutils.ProcessExecutionError('error')

        mock_execute.side_effect = umount_raise_func
        environ_mock.get.return_value = '/sbin'
        self.assertRaises(errors.CommandExecutionError,
                          image._install_grub2,
                          self.fake_dev, root_uuid=self.fake_root_uuid,
                          efi_system_part_uuid=self.fake_efi_system_part_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                              '"grub-install --removable"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    # Call from for loop
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    # Call from finally
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True)
                    ]
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_uefi_mount_fails(
            self, mock_get_part_uuid, mkdir_mock, environ_mock,
            mock_is_md_device, mock_md_get_raid_devices, mock_execute,
            mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        mock_is_md_device.side_effect = [False, False]
        environ_mock.get.return_value = '/sbin'
        mock_md_get_raid_devices.return_value = {}

        def mount_raise_func(*args, **kwargs):
            if args[0] == 'mount':
                raise processutils.ProcessExecutionError('error')

        mock_execute.side_effect = mount_raise_func
        self.assertRaises(errors.CommandExecutionError,
                          image._install_grub2,
                          self.fake_dev, root_uuid=self.fake_root_uuid,
                          efi_system_part_uuid=self.fake_efi_system_part_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: False)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    def test__install_grub2_command_fail(self, mock_get_part_uuid,
                                         mock_execute,
                                         mock_dispatch):
        mock_get_part_uuid.return_value = self.fake_root_part
        mock_execute.side_effect = processutils.ProcessExecutionError('boom')

        self.assertRaises(errors.CommandExecutionError, image._install_grub2,
                          self.fake_dev, self.fake_root_uuid)

        mock_get_part_uuid.assert_called_once_with(self.fake_dev,
                                                   uuid=self.fake_root_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_restart', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True,
                       return_value=['/dev/sda', '/dev/sdb'])
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    @mock.patch.object(raid_utils, 'prepare_boot_partitions_for_softraid',
                       autospec=True,
                       return_value='/dev/md/esp')
    @mock.patch.object(image, '_has_dracut',
                       autospec=True,
                       return_value=False)
    def test__install_grub2_softraid_uefi_gpt(
            self, mock_dracut,
            mock_prepare, mock_get_part_uuid, mkdir_mock, environ_mock,
            mock_holder, mock_md_get_raid_devices, mock_restart,
            mock_is_md_device,
            mock_execute, mock_dispatch):

        # return success for every execute call
        mock_execute.side_effect = [('', '')] * 24

        # make grub2-install calls fail
        grub_failure = processutils.ProcessExecutionError(
            stdout='',
            stderr='grub2-install: error: this utility cannot be used '
                   'for EFI platforms because it does not support '
                   'UEFI Secure Boot.\n',
            exit_code=1,
            cmd='grub2-install'
        )
        mock_execute.side_effect[12] = grub_failure
        mock_execute.side_effect[13] = grub_failure

        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = True
        mock_md_get_raid_devices.return_value = {}

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid,
            target_boot_mode='uefi')

        expected = [mock.call('partx', '-av', '/dev/fake', attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mkdir', '-p', self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mkdir', '-p', self.fake_dir + '/proc'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mkdir', '-p', self.fake_dir + '/run'),
                    mock.call('mount', '-o', 'bind', '/run',
                              self.fake_dir + '/run'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('mount', '/dev/md/esp',
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c "grub-install"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub-install --removable"' %
                               self.fake_dir), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call(
                        'umount', self.fake_dir + '/boot/efi',
                        attempts=3, delay_on_retry=True),
                    mock.call('mount', '/dev/md/esp',
                              '/tmp/fake-dir/boot/efi'),
                    mock.call(('chroot %s /bin/sh -c '
                               '"grub-mkconfig -o '
                               '/boot/grub/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                                  'GRUB_DISABLE_OS_PROBER': 'true',
                                  'GRUB_SAVEDEFAULT': 'true'},
                              use_standard_locale=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                              (self.fake_dir)), shell=True,
                              env_variables={
                                  'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/run',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)
        mock_prepare.assert_called_once_with(self.fake_dev,
                                             ['/dev/sda', '/dev/sdb'],
                                             self.fake_efi_system_part, 'uefi')
        mock_restart.assert_called_once_with(self.fake_dev)
        mock_holder.assert_called_once_with(self.fake_dev)
        mock_dracut.assert_called_once_with(self.fake_dir)

    @mock.patch.object(image, '_is_bootloader_loaded', lambda *_: True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(hardware, 'md_restart', autospec=True)
    @mock.patch.object(hardware, 'md_get_raid_devices', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True,
                       return_value=['/dev/sda', '/dev/sdb'])
    @mock.patch.object(os, 'environ', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(partition_utils, 'get_partition', autospec=True)
    @mock.patch.object(raid_utils, 'prepare_boot_partitions_for_softraid',
                       autospec=True,
                       return_value=[])
    @mock.patch.object(image, '_has_dracut',
                       autospec=True,
                       return_value=False)
    def test__install_grub2_softraid_bios(
            self, mock_dracut,
            mock_prepare, mock_get_part_uuid, mkdir_mock, environ_mock,
            mock_holder, mock_md_get_raid_devices, mock_restart,
            mock_is_md_device,
            mock_execute, mock_dispatch):

        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'
        mock_is_md_device.return_value = True
        mock_md_get_raid_devices.return_value = {}

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None,
            target_boot_mode='bios')

        expected = [
            mock.call('mount', '/dev/fake2', self.fake_dir),
            mock.call('mkdir', '-p', self.fake_dir + '/dev'),
            mock.call('mount', '-o', 'bind', '/dev',
                      self.fake_dir + '/dev'),
            mock.call('mkdir', '-p', self.fake_dir + '/proc'),
            mock.call('mount', '-o', 'bind', '/proc',
                      self.fake_dir + '/proc'),
            mock.call('mkdir', '-p', self.fake_dir + '/run'),
            mock.call('mount', '-o', 'bind', '/run',
                      self.fake_dir + '/run'),
            mock.call('mount', '-t', 'sysfs', 'none',
                      self.fake_dir + '/sys'),
            mock.call(('chroot %s /bin/sh -c "mount -a -t vfat"' %
                       (self.fake_dir)), shell=True,
                      env_variables={
                          'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
            mock.call(('chroot %s /bin/sh -c '
                       '"grub-install %s"' %
                       (self.fake_dir, '/dev/sda')), shell=True,
                      env_variables={
                          'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
            mock.call(('chroot %s /bin/sh -c '
                       '"grub-install %s"' %
                       (self.fake_dir, '/dev/sdb')), shell=True,
                      env_variables={
                          'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
            mock.call(('chroot %s /bin/sh -c '
                       '"grub-mkconfig -o '
                       '/boot/grub/grub.cfg"' % self.fake_dir),
                      shell=True,
                      env_variables={
                          'PATH': '/sbin:/bin:/usr/sbin:/sbin',
                          'GRUB_DISABLE_OS_PROBER': 'true',
                          'GRUB_SAVEDEFAULT': 'true'},
                      use_standard_locale=True),
            mock.call(('chroot %s /bin/sh -c "umount -a -t vfat"' %
                      (self.fake_dir)), shell=True,
                      env_variables={
                          'PATH': '/sbin:/bin:/usr/sbin:/sbin'}),
            mock.call('umount', self.fake_dir + '/dev',
                      attempts=3, delay_on_retry=True),
            mock.call('umount', self.fake_dir + '/proc',
                      attempts=3, delay_on_retry=True),
            mock.call('umount', self.fake_dir + '/run',
                      attempts=3, delay_on_retry=True),
            mock.call('umount', self.fake_dir + '/sys',
                      attempts=3, delay_on_retry=True),
            mock.call('umount', self.fake_dir, attempts=3,
                      delay_on_retry=True)]
        self.assertFalse(mkdir_mock.called)
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        self.assertFalse(mock_dispatch.called)
        mock_prepare.assert_called_once_with(self.fake_dev,
                                             ['/dev/sda', '/dev/sdb'],
                                             None, 'bios')
        mock_restart.assert_called_once_with(self.fake_dev)
        mock_holder.assert_called_once_with(self.fake_dev)
        mock_dracut.assert_called_once_with(self.fake_dir)

    def test__is_bootloader_loaded(self, mock_execute,
                                   mock_dispatch):
        mock_dispatch.return_value = hardware.BootInfo(
            current_boot_mode='bios')
        parted_output = ('BYT;\n'
                         '/dev/loop1:46.1MB:loopback:512:512:gpt:Loopback '
                         'device:;\n'
                         '15:1049kB:9437kB:8389kB:::boot;\n'
                         '1:9437kB:46.1MB:36.7MB:ext3::;\n')
        disk_file_output = ('/dev/loop1: partition 1: ID=0xee, starthead 0, '
                            'startsector 1, 90111 sectors, extended '
                            'partition table (last)\011, code offset 0x48')

        part_file_output = ('/dev/loop1p15: x86 boot sector, mkdosfs boot '
                            'message display, code offset 0x3c, OEM-ID '
                            '"mkfs.fat", sectors/cluster 8, root entries '
                            '512, sectors 16384 (volumes <=32 MB) , Media '
                            'descriptor 0xf8, sectors/FAT 8, heads 255, '
                            'serial number 0x23a08feb, unlabeled, '
                            'FAT (12 bit)')

        # NOTE(TheJulia): File evaluates this data, so it is pointless to
        # try and embed the raw bytes in the test.
        dd_output = ('')

        file_output = ('/dev/loop1: DOS executable (COM)\n')

        mock_execute.side_effect = iter([(parted_output, ''),
                                         (disk_file_output, ''),
                                         (part_file_output, ''),
                                         (dd_output, ''),
                                         (file_output, '')])

        result = image._is_bootloader_loaded(self.fake_dev)
        self.assertTrue(result)

    def test__is_bootloader_loaded_not_bootable(self,
                                                mock_execute,
                                                mock_dispatch):
        parted_output = ('BYT;\n'
                         '/dev/loop1:46.1MB:loopback:512:512:gpt:Loopback '
                         'device:;\n'
                         '15:1049kB:9437kB:8389kB:::;\n'
                         '1:9437kB:46.1MB:36.7MB:ext3::;\n')
        mock_execute.return_value = (parted_output, '')
        result = image._is_bootloader_loaded(self.fake_dev)
        self.assertFalse(result)

    def test__is_bootloader_loaded_empty(self,
                                         mock_execute,
                                         mock_dispatch):
        parted_output = ('BYT;\n'
                         '/dev/loop1:46.1MB:loopback:512:512:gpt:Loopback '
                         'device:;\n')
        mock_execute.return_value = (parted_output, '')
        result = image._is_bootloader_loaded(self.fake_dev)
        self.assertFalse(result)

    def test__is_bootloader_loaded_uefi_mode(self, mock_execute,
                                             mock_dispatch):

        mock_dispatch.return_value = hardware.BootInfo(
            current_boot_mode='uefi')
        result = image._is_bootloader_loaded(self.fake_dev)
        self.assertFalse(result)
        mock_dispatch.assert_any_call('get_boot_info')
        self.assertEqual(0, mock_execute.call_count)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(os.path, 'exists', lambda *_: True)
    def test__append_uefi_to_fstab_handles_error(self, mock_execute,
                                                 mock_dispatch,
                                                 mock_list_blk_devs):
        with mock.patch('builtins.open', mock.mock_open()) as mock_open:
            mock_open.side_effect = OSError('boom')
            image._append_uefi_to_fstab(
                self.fake_dir, 'abcd-efgh')

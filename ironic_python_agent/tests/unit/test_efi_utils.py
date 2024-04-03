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
import re
import shutil
import tempfile
from unittest import mock

from oslo_concurrency import processutils

from ironic_python_agent import disk_utils
from ironic_python_agent import efi_utils
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import partition_utils
from ironic_python_agent import raid_utils
from ironic_python_agent.tests.unit import base
from ironic_python_agent.tests.unit.samples import hardware_samples
from ironic_python_agent import utils


EFI_RESULT = ''.encode('utf-16')


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
        mock_execute.return_value = (''.encode('utf-16'), '')
        result = efi_utils._run_efibootmgr(['EFI/BOOT/BOOTX64.EFI'],
                                           self.fake_dev,
                                           self.fake_efi_system_part,
                                           self.fake_dir)
        expected = [mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', self.fake_efi_system_part, '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True)]
        self.assertIsNone(result)
        mock_execute.assert_has_calls(expected)


@mock.patch.object(shutil, 'rmtree', lambda *_: None)
@mock.patch.object(tempfile, 'mkdtemp', lambda *_: '/tmp/fake-dir')
@mock.patch.object(utils, 'rescan_device', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
@mock.patch.object(partition_utils, 'get_partition', autospec=True)
@mock.patch.object(efi_utils, 'get_partition_path_by_number', autospec=True)
@mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
class TestManageUefi(base.IronicAgentTest):

    fake_dev = '/dev/fake'
    fake_efi_system_part = '/dev/fake1'
    fake_root_part = '/dev/fake2'
    fake_root_uuid = '11111111-2222-3333-4444-555555555555'
    fake_dir = '/tmp/fake-dir'

    def test_no_partition(self, mock_utils_efi_part,
                          mock_get_part_path,
                          mock_get_part_uuid, mock_execute,
                          mock_rescan):
        mock_utils_efi_part.return_value = None
        self.assertRaises(errors.DeviceNotFound,
                          efi_utils.manage_uefi, self.fake_dev, None)
        self.assertFalse(mock_get_part_uuid.called)
        mock_rescan.assert_called_once_with(self.fake_dev)

    def test_empty_partition_by_uuid(self, mock_utils_efi_part,
                                     mock_get_part_path,
                                     mock_get_part_uuid, mock_execute,
                                     mock_rescan):
        mock_utils_efi_part.return_value = None
        mock_get_part_uuid.return_value = self.fake_root_part
        result = efi_utils.manage_uefi(self.fake_dev, self.fake_root_uuid)
        self.assertFalse(result)
        mock_rescan.assert_called_once_with(self.fake_dev)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_ok(self, mkdir_mock, mock_efi_bl, mock_is_md_device,
                mock_utils_efi_part, mock_get_part_path, mock_get_part_uuid,
                mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_is_md_device.return_value = False

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        mock_execute.side_effect = iter([('', ''), (EFI_RESULT, ''),
                                         (EFI_RESULT, ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
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

    def test_get_boot_records(self, mock_utils_efi_part,
                              mock_get_part_path,
                              mock_get_part_uuid, mock_execute,
                              mock_rescan):
        efibootmgr_resp = """
BootCurrent: 0001
Timeout: 0 seconds
BootOrder: 0001,0000,001B,001C,001D,001E,001F,0020,0021,0022,0012,0011,0023,0024,0002
Boot0000* Red Hat Enterprise Linux	HD(1,GPT,34178504-2340-4fe0-8001-264372cf9b2d,0x800,0x64000)/File(\\EFI\\redhat\\shimx64.efi)
Boot0001* Fedora	HD(1,GPT,da6b4491-61f2-42b0-8ab1-7c4a87317c4e,0x800,0x64000)/File(\\EFI\\fedora\\shimx64.efi)
Boot0002* Linux-Firmware-Updater	HD(1,GPT,da6b4491-61f2-42b0-8ab1-7c4a87317c4e,0x800,0x64000)/File(\\EFI\\fedora\\fwupdx64.efi)
Boot0003  ThinkShield secure wipe	FvFile(3593a0d5-bd52-43a0-808e-cbff5ece2477)
Boot0004  LENOVO CLOUD	VenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,ad38ccbbf7edf04d959cf42aa74d3650)/Uri(https://download.lenovo.com/pccbbs/cdeploy/efi/boot.efi)
Boot0005  IDER BOOT CDROM	PciRoot(0x0)/Pci(0x14,0x0)/USB(11,1)
Boot0006 ATA HDD	VenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,91af625956449f41a7b91f4f892ab0f6)
Boot0007* Hard drive C: VenHw(d6c0639f-c705-4eb9-aa4f-5802d8823de6)......................................................................................A.....................P.E.R.C. .H.7.3.0.P. .M.i.n.i.(.b.u.s. .1.8. .d.e.v. .0.0.)...
BootAAA8* IBA GE Slot 0100 v1588        BBS(128,IBA GE Slot 0100 v1588,0x0)........................B.............................................................A.....................I.B.A. .G.E. .S.l.o.t. .0.1.0.0. .v.1.5.8.8...
Boot0FF9* Virtual CD/DVD        PciRoot(0x0)/Pci(0x14,0x0)/USB(13,0)/USB(3,0)/USB(1,0)
Boot123A* Integrated NIC 1 Port 1 Partition 1   VenHw(33391845-5f86-4e78-8fce-c4cff59f9bbb)
Boot000B* UEFI: PXE IPv4 Realtek PCIe 2.5GBE Family Controller	PciRoot(0x0)/Pci(0x1c,0x0)/Pci(0x0,0x0)/MAC([REDACTED],0)/IPv4(0.0.0.00.0.0.0,0,0)..BO
Boot0008* Generic USB Boot UsbClass(ffff,ffff,255,255)
Boot0009* Internal CD/DVD ROM Drive (UEFI)      PciRoot(0x0)/Pci(0x11,0x0)/Sata(1,65535,0)/CDROM(1,0x265,0x2000)
""".encode('utf-16') # noqa This is a giant literal string for testing.
        mock_execute.return_value = (efibootmgr_resp, '')
        result = list(efi_utils.get_boot_records())

        self.assertEqual(
            ('0000', 'Red Hat Enterprise Linux', 'HD',
             'HD(1,GPT,34178504-2340-4fe0-8001-264372cf9b2d,0x800,0x64000)/'
             'File(\\EFI\\redhat\\shimx64.efi)'),
            result[0])
        self.assertEqual(
            ('0001', 'Fedora', 'HD',
             'HD(1,GPT,da6b4491-61f2-42b0-8ab1-7c4a87317c4e,0x800,0x64000)/'
             'File(\\EFI\\fedora\\shimx64.efi)'),
            result[1])
        self.assertEqual(
            ('0002', 'Linux-Firmware-Updater', 'HD',
             'HD(1,GPT,da6b4491-61f2-42b0-8ab1-7c4a87317c4e,0x800,0x64000)/'
             'File(\\EFI\\fedora\\fwupdx64.efi)'),
            result[2])
        self.assertEqual(
            ('0003', 'ThinkShield secure wipe', 'FvFile',
             'FvFile(3593a0d5-bd52-43a0-808e-cbff5ece2477)'),
            result[3])
        self.assertEqual(
            ('0004', 'LENOVO CLOUD', 'VenMsg',
             'VenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,'
             'ad38ccbbf7edf04d959cf42aa74d3650)/'
             'Uri(https://download.lenovo.com/pccbbs/cdeploy/efi/boot.efi)'),
            result[4])
        self.assertEqual(
            ('0005', 'IDER BOOT CDROM', 'PciRoot',
             'PciRoot(0x0)/Pci(0x14,0x0)/USB(11,1)'),
            result[5])
        self.assertEqual(
            ('0006', 'ATA HDD', 'VenMsg',
             'VenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,'
             '91af625956449f41a7b91f4f892ab0f6)'),
            result[6])
        self.assertEqual(
            ('0007', 'Hard drive C:', 'VenHw',
             mock.ANY),
            result[7])
        self.assertEqual(
            ('AAA8', 'IBA GE Slot 0100 v1588', 'BBS',
             mock.ANY),
            result[8])
        self.assertEqual(
            ('0FF9', 'Virtual CD/DVD', 'PciRoot',
             'PciRoot(0x0)/Pci(0x14,0x0)/USB(13,0)/USB(3,0)/USB(1,0)'),
            result[9])
        self.assertEqual(
            ('123A', 'Integrated NIC 1 Port 1 Partition 1', 'VenHw',
             'VenHw(33391845-5f86-4e78-8fce-c4cff59f9bbb)'),
            result[10])
        self.assertEqual(
            ('000B',
             'UEFI: PXE IPv4 Realtek PCIe 2.5GBE Family Controller',
             'PciRoot',
             'PciRoot(0x0)/Pci(0x1c,0x0)/Pci(0x0,0x0)/MAC([REDACTED],0)/'
             'IPv4(0.0.0.00.0.0.0,0,0)..BO'),
            result[11])
        self.assertEqual(
            ('0008', 'Generic USB Boot', 'UsbClass',
             'UsbClass(ffff,ffff,255,255)'),
            result[12])
        self.assertEqual(
            ('0009', 'Internal CD/DVD ROM Drive (UEFI)', 'PciRoot',
             'PciRoot(0x0)/Pci(0x11,0x0)/Sata(1,65535,0)/'
             'CDROM(1,0x265,0x2000)'),
            result[13])

    def test_clean_boot_records(self, mock_utils_efi_part,
                                mock_get_part_path,
                                mock_get_part_uuid, mock_execute,
                                mock_rescan):
        efibootmgr_resp = """
BootCurrent: 0001
Timeout: 0 seconds
BootOrder: 0001,0000,001B,001C,001D,001E,001F,0020,0021,0022,0012,0011,0023,0024,0002
Boot0000* Red Hat Enterprise Linux	HD(1,GPT,34178504-2340-4fe0-8001-264372cf9b2d,0x800,0x64000)/File(\\EFI\\redhat\\grubx64.efi)
Boot0001* Fedora	HD(1,GPT,da6b4491-61f2-42b0-8ab1-7c4a87317c4e,0x800,0x64000)/File(\\EFI\\fedora\\SHIMX64.EFI)
Boot0002* Linux-Firmware-Updater	HD(1,GPT,da6b4491-61f2-42b0-8ab1-7c4a87317c4e,0x800,0x64000)/File(\\EFI\\fedora\\fwupdx64.efi)
Boot0003  ThinkShield secure wipe	FvFile(3593a0d5-bd52-43a0-808e-cbff5ece2477)
Boot0004  LENOVO CLOUD	VenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,ad38ccbbf7edf04d959cf42aa74d3650)/Uri(https://download.lenovo.com/pccbbs/cdeploy/efi/boot.efi)
Boot0005  IDER BOOT CDROM	PciRoot(0x0)/Pci(0x14,0x0)/USB(11,1)
Boot0006 ATA HDD	VenMsg(bc7838d2-0f82-4d60-8316-c068ee79d25b,91af625956449f41a7b91f4f892ab0f6)
Boot0007* Hard drive C: VenHw(d6c0639f-c705-4eb9-aa4f-5802d8823de6)......................................................................................A.....................P.E.R.C. .H.7.3.0.P. .M.i.n.i.(.b.u.s. .1.8. .d.e.v. .0.0.)...
BootAAA8* IBA GE Slot 0100 v1588        BBS(128,IBA GE Slot 0100 v1588,0x0)........................B.............................................................A.....................I.B.A. .G.E. .S.l.o.t. .0.1.0.0. .v.1.5.8.8...
Boot0FF9* Virtual CD/DVD        PciRoot(0x0)/Pci(0x14,0x0)/USB(13,0)/USB(3,0)/USB(1,0)
Boot123A* Integrated NIC 1 Port 1 Partition 1   VenHw(33391845-5f86-4e78-8fce-c4cff59f9bbb)
Boot000B* UEFI: PXE IPv4 Realtek PCIe 2.5GBE Family Controller	PciRoot(0x0)/Pci(0x1c,0x0)/Pci(0x0,0x0)/MAC([REDACTED],0)/IPv4(0.0.0.00.0.0.0,0,0)..BO
Boot0008* Generic USB Boot UsbClass(ffff,ffff,255,255)
Boot0009* Internal CD/DVD ROM Drive (UEFI)      PciRoot(0x0)/Pci(0x11,0x0)/Sata(1,65535,0)/CDROM(1,0x265,0x2000)
""".encode('utf-16') # noqa This is a giant literal string for testing.
        mock_execute.return_value = (efibootmgr_resp, '')
        patterns = [
            re.compile(r'^HD\(', flags=re.IGNORECASE),
            re.compile(r'shim.*\.efi', flags=re.IGNORECASE),
            re.compile(r'^UsbClass', flags=re.IGNORECASE),
        ]
        efi_utils.clean_boot_records(patterns)

        # Assert that entries 0000, 0001, 0002, and 0008 were deleted
        mock_execute.assert_has_calls([
            mock.call('efibootmgr', '-v', binary=True),
            mock.call('efibootmgr', '-b', '0000', '-B', binary=True),
            mock.call('efibootmgr', '-b', '0001', '-B', binary=True),
            mock.call('efibootmgr', '-b', '0002', '-B', binary=True),
            mock.call('efibootmgr', '-b', '0008', '-B', binary=True)
        ])

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_found_csv(self, mkdir_mock, mock_efi_bl, mock_is_md_device,
                       mock_utils_efi_part, mock_get_part_path,
                       mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_efi_bl.return_value = ['EFI/vendor/BOOTX64.CSV']
        mock_is_md_device.return_value = False

        # Format is <file>,<entry_name>,<options>,humanfriendlytextnotused
        # https://www.rodsbooks.com/efi-bootloaders/fallback.html
        # Mild difference, Ubuntu ships a file without a 0xFEFF delimiter
        # at the start of the file, where as Red Hat *does*
        csv_file_data = u'shimx64.efi,Vendor String,,Grub2MadeUSDoThis\n'
        # This test also handles deleting a pre-existing matching vendor
        # string in advance. This string also includes a UTF16 character
        # *on* purpose, to force proper decoding to be tested and garbage
        # characters which can be found in OVMF test VM NVRAM records.
        dupe_entry = """
BootCurrent: 0001
Timeout: 0 seconds
BootOrder: 0000,00001
Boot0000 UTF16ÿ HD(1,GPT,4f3c6294-bf9b-4208-9808-be45dfc34b5c)File(\EFI\Boot\BOOTX64.EFI)
Boot0001* Vendor String HD(1,GPT,4f3c6294-bf9b-4208-9808-be45dfc34b5c)File(\EFI\Boot\BOOTX64.EFI)
Boot0002 Vendor String HD(2,GPT,4f3c6294-bf9b-4208-9808-be45dfc34b5c)File(\EFI\Boot\BOOTX64.EFI)
Boot0003: VENDMAGIC FvFile(9f3c6294-bf9b-4208-9808-be45dfc34b51)N.....YM....R,Y.
"""  # noqa This is a giant literal string for testing.
        dupe_entry = dupe_entry.encode('utf-16')
        mock_execute.side_effect = iter([('', ''),
                                         (dupe_entry, ''),
                                         ('', ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-b', '0001', '-B', binary=True),
                    mock.call('efibootmgr', '-b', '0002', '-B', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'Vendor String', '-l',
                              '\\EFI\\vendor\\shimx64.efi', binary=True),
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
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_nvme_device(self, mkdir_mock, mock_efi_bl, mock_is_md_device,
                         mock_utils_efi_part, mock_get_part_path,
                         mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = None
        mock_get_part_uuid.return_value = '/dev/fakenvme0p1'
        mock_is_md_device.return_value = False

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        mock_execute.side_effect = iter([('', ''), (EFI_RESULT, ''),
                                         (EFI_RESULT, ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', '/dev/fakenvme0p1',
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', '/dev/fakenvme0',
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        result = efi_utils.manage_uefi('/dev/fakenvme0', self.fake_root_uuid)
        self.assertTrue(result)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_wholedisk(self, mkdir_mock, mock_efi_bl, mock_is_md_device,
                       mock_utils_efi_part, mock_get_part_path,
                       mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_is_md_device.return_value = False

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        mock_execute.side_effect = iter([('', ''), (EFI_RESULT, ''),
                                         (EFI_RESULT, ''), ('', ''),
                                         ('', ''), ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', self.fake_dev,
                              '-p', '1', '-w',
                              '-L', 'ironic1', '-l',
                              '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        result = efi_utils.manage_uefi(self.fake_dev, None)
        self.assertTrue(result)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_not_called()

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(raid_utils,
                       'prepare_boot_partitions_for_softraid',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_software_raid(self, mkdir_mock, mock_efi_bl, mock_is_md_device,
                           mock_get_holder_disks, mock_prepare,
                           mock_get_component_devices,
                           mock_utils_efi_part, mock_get_part_path,
                           mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_is_md_device.return_value = True
        mock_get_holder_disks.return_value = ['/dev/sda', '/dev/sdb']
        mock_prepare.return_value = '/dev/md125'
        mock_get_component_devices.return_value = ['/dev/sda3', '/dev/sdb3']

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']
        mock_execute.side_effect = iter([('', ''),
                                         ('', ''),
                                         ('', ''),
                                         (EFI_RESULT, ''),
                                         (EFI_RESULT, ''),
                                         (EFI_RESULT, ''),
                                         (EFI_RESULT, ''),
                                         ('', ''),
                                         ('', '')])

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', '/dev/sda3',
                              '-p', '3', '-w', '-L', 'ironic1 (RAID, part0)',
                              '-l', '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('efibootmgr', '-v', '-c', '-d', '/dev/sdb3',
                              '-p', '3', '-w', '-L', 'ironic1 (RAID, part1)',
                              '-l', '\\EFI\\BOOT\\BOOTX64.EFI', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        result = efi_utils.manage_uefi(self.fake_dev, None)
        self.assertTrue(result)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_failure(self, mkdir_mock, mock_efi_bl, mock_is_md_device,
                     mock_utils_efi_part, mock_get_part_path,
                     mock_get_part_uuid, mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_is_md_device.return_value = False

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']

        mock_execute.side_effect = processutils.ProcessExecutionError('boom')

        self.assertRaisesRegex(errors.CommandExecutionError, 'boom',
                               efi_utils.manage_uefi,
                               self.fake_dev, self.fake_root_uuid)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_not_called()
        mock_execute.assert_called_once_with(
            'mount', self.fake_efi_system_part, self.fake_dir + '/boot/efi')
        mock_rescan.assert_called_once_with(self.fake_dev)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_failure_after_mount(self, mkdir_mock, mock_efi_bl,
                                 mock_is_md_device, mock_utils_efi_part,
                                 mock_get_part_path, mock_get_part_uuid,
                                 mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_is_md_device.return_value = False

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']

        mock_execute.side_effect = [
            ('', ''),
            processutils.ProcessExecutionError('boom'),
            ('', ''),
            ('', ''),
        ]

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('sync')]

        self.assertRaisesRegex(errors.CommandExecutionError, 'boom',
                               efi_utils.manage_uefi,
                               self.fake_dev, self.fake_root_uuid)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        self.assertEqual(4, mock_execute.call_count)
        mock_rescan.assert_called_once_with(self.fake_dev)

    @mock.patch.object(os.path, 'exists', lambda *_: False)
    @mock.patch.object(hardware, 'is_md_device', autospec=True)
    @mock.patch.object(efi_utils, '_get_efi_bootloaders', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_failure_after_failure(self, mkdir_mock, mock_efi_bl,
                                   mock_is_md_device, mock_utils_efi_part,
                                   mock_get_part_path, mock_get_part_uuid,
                                   mock_execute, mock_rescan):
        mock_utils_efi_part.return_value = {'number': '1'}
        mock_get_part_path.return_value = self.fake_efi_system_part
        mock_is_md_device.return_value = False

        mock_efi_bl.return_value = ['EFI/BOOT/BOOTX64.EFI']

        mock_execute.side_effect = [
            ('', ''),
            processutils.ProcessExecutionError('boom'),
            processutils.ProcessExecutionError('no umount'),
            ('', ''),
        ]

        expected = [mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call('efibootmgr', '-v', binary=True),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True)]

        self.assertRaisesRegex(errors.CommandExecutionError, 'boom',
                               efi_utils.manage_uefi,
                               self.fake_dev, self.fake_root_uuid)
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_efi_bl.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        self.assertEqual(3, mock_execute.call_count)
        mock_rescan.assert_called_once_with(self.fake_dev)


@mock.patch.object(partition_utils, 'get_partition', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
class TestGetPartitionPathByNumber(base.IronicAgentTest):

    def test_ok(self, mock_execute, mock_get_partition):
        mock_execute.return_value = (hardware_samples.SGDISK_INFO_TEMPLATE, '')
        mock_get_partition.return_value = '/dev/fake1'

        result = efi_utils.get_partition_path_by_number('/dev/fake', 1)
        self.assertEqual('/dev/fake1', result)

        mock_execute.assert_called_once_with('sgdisk', '-i', '1', '/dev/fake',
                                             use_standard_locale=True)

    def test_broken(self, mock_execute, mock_get_partition):
        mock_execute.return_value = ('I am a teaport', '')

        self.assertIsNone(
            efi_utils.get_partition_path_by_number('/dev/fake', 1))
        mock_get_partition.assert_not_called()

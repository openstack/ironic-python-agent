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

from unittest import mock

from ironic_lib import disk_utils
from ironic_lib import utils as ilib_utils
from oslo_concurrency import processutils

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import raid_utils
from ironic_python_agent.tests.unit import base
from ironic_python_agent.tests.unit.samples import hardware_samples as hws
from ironic_python_agent.tests.unit import test_hardware
from ironic_python_agent import utils


class TestRaidUtils(base.IronicAgentTest):

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__get_actual_component_devices(self, mock_execute):
        mock_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT, '')]
        component_devices = raid_utils._get_actual_component_devices(
            '/dev/md0')
        self.assertEqual(['/dev/vde1', '/dev/vdf1'], component_devices)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__get_actual_component_devices_broken_raid0(self, mock_execute):
        mock_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT_BROKEN_RAID0, '')]
        component_devices = raid_utils._get_actual_component_devices(
            '/dev/md126')
        self.assertEqual(['/dev/sda2'], component_devices)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_raid_device(self, mock_execute, mocked_components):
        logical_disk = {
            "block_devices": ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            "raid_level": "1",
        }
        mocked_components.return_value = ['/dev/sda1',
                                          '/dev/sdb1',
                                          '/dev/sdc1']

        raid_utils.create_raid_device(0, logical_disk)

        mock_execute.assert_called_once_with(
            'mdadm', '--create', '/dev/md0', '--force', '--run',
            '--metadata=1', '--level', '1', '--name', '/dev/md0',
            '--raid-devices', 3, '/dev/sda1', '/dev/sdb1', '/dev/sdc1')

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_raid_device_with_volume_name(self, mock_execute,
                                                 mocked_components):
        logical_disk = {
            "block_devices": ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            "raid_level": "1",
            "volume_name": "diskname"
        }
        mocked_components.return_value = ['/dev/sda1',
                                          '/dev/sdb1',
                                          '/dev/sdc1']

        raid_utils.create_raid_device(0, logical_disk)

        mock_execute.assert_called_once_with(
            'mdadm', '--create', '/dev/md0', '--force', '--run',
            '--metadata=1', '--level', '1', '--name', 'diskname',
            '--raid-devices', 3, '/dev/sda1', '/dev/sdb1', '/dev/sdc1')

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_raid_device_missing_device(self, mock_execute,
                                               mocked_components):
        logical_disk = {
            "block_devices": ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            "raid_level": "1",
        }
        mocked_components.return_value = ['/dev/sda1',
                                          '/dev/sdc1']

        raid_utils.create_raid_device(0, logical_disk)

        expected_calls = [
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', '/dev/md0',
                      '--raid-devices', 3, '/dev/sda1', '/dev/sdb1',
                      '/dev/sdc1'),
            mock.call('mdadm', '--add', '/dev/md0', '/dev/sdb1',
                      attempts=3, delay_on_retry=True)
        ]
        self.assertEqual(mock_execute.call_count, 2)
        mock_execute.assert_has_calls(expected_calls)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_raid_device_fail_create_device(self, mock_execute):
        logical_disk = {
            "block_devices": ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            "raid_level": "1",
        }
        mock_execute.side_effect = processutils.ProcessExecutionError()

        self.assertRaisesRegex(errors.SoftwareRAIDError,
                               "Failed to create md device /dev/md0",
                               raid_utils.create_raid_device, 0,
                               logical_disk)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_raid_device_fail_read_device(self, mock_execute,
                                                 mocked_components):
        logical_disk = {
            "block_devices": ['/dev/sda', '/dev/sdb', '/dev/sdc'],
            "raid_level": "1",
        }
        mock_execute.side_effect = [mock.Mock,
                                    processutils.ProcessExecutionError()]

        mocked_components.return_value = ['/dev/sda1',
                                          '/dev/sdc1']

        self.assertRaisesRegex(errors.SoftwareRAIDError,
                               "Failed re-add /dev/sdb1 to /dev/md0",
                               raid_utils.create_raid_device, 0,
                               logical_disk)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_volume_name_of_raid_device(self, mock_execute):
        mock_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT_VOLUME_NAME, '')]
        volume_name = raid_utils.get_volume_name_of_raid_device('/dev/md0')
        self.assertEqual("this_name", volume_name)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_volume_name_of_raid_device_invalid(self, mock_execute):
        mock_execute.side_effect = [(
            hws.MDADM_DETAIL_OUTPUT_VOLUME_NAME_INVALID, ''
        )]
        volume_name = raid_utils.get_volume_name_of_raid_device('/dev/md0')
        self.assertIsNone(volume_name)

    @mock.patch.object(disk_utils, 'trigger_device_rescan', autospec=True)
    @mock.patch.object(raid_utils, 'get_next_free_raid_device', autospec=True,
                       return_value='/dev/md42')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(ilib_utils, 'execute', autospec=True)
    @mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
    def test_prepare_boot_partitions_for_softraid_uefi_gpt(
            self, mock_efi_part, mock_execute, mock_dispatch,
            mock_free_raid_device, mock_rescan):
        mock_efi_part.return_value = {'number': '12'}
        mock_execute.side_effect = [
            ('451', None),  # sgdisk -F
            (None, None),  # sgdisk create part
            (None, None),  # partprobe
            (None, None),  # blkid
            ('/dev/sda12: dsfkgsdjfg', None),  # blkid
            ('452', None),  # sgdisk -F
            (None, None),  # sgdisk create part
            (None, None),  # partprobe
            (None, None),  # blkid
            ('/dev/sdb14: whatever', None),  # blkid
            (None, None),  # mdadm
            (None, None),  # cp
            (None, None),  # wipefs
        ]

        efi_part = raid_utils.prepare_boot_partitions_for_softraid(
            '/dev/md0', ['/dev/sda', '/dev/sdb'], None,
            target_boot_mode='uefi')

        mock_efi_part.assert_called_once_with('/dev/md0')
        expected = [
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('sgdisk', '-n', '0:451s:+550MiB', '-t', '0:ef00', '-c',
                      '0:uefi-holder-0', '/dev/sda'),
            mock.call('partprobe'),
            mock.call('blkid'),
            mock.call('blkid', '-l', '-t', 'PARTLABEL=uefi-holder-0',
                      '/dev/sda'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('sgdisk', '-n', '0:452s:+550MiB', '-t', '0:ef00', '-c',
                      '0:uefi-holder-1', '/dev/sdb'),
            mock.call('partprobe'),
            mock.call('blkid'),
            mock.call('blkid', '-l', '-t', 'PARTLABEL=uefi-holder-1',
                      '/dev/sdb'),
            mock.call('mdadm', '--create', '/dev/md42', '--force', '--run',
                      '--metadata=1.0', '--level', '1', '--name', 'esp',
                      '--raid-devices', 2, '/dev/sda12', '/dev/sdb14'),
            mock.call('cp', '/dev/md0p12', '/dev/md42'),
            mock.call('wipefs', '-a', '/dev/md0p12')
        ]
        mock_execute.assert_has_calls(expected, any_order=False)
        self.assertEqual(efi_part, '/dev/md42')
        mock_rescan.assert_called_once_with('/dev/md42')

    @mock.patch.object(disk_utils, 'trigger_device_rescan', autospec=True)
    @mock.patch.object(raid_utils, 'get_next_free_raid_device', autospec=True,
                       return_value='/dev/md42')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(ilib_utils, 'execute', autospec=True)
    @mock.patch.object(disk_utils, 'find_efi_partition', autospec=True)
    @mock.patch.object(ilib_utils, 'mkfs', autospec=True)
    def test_prepare_boot_partitions_for_softraid_uefi_gpt_esp_not_found(
            self, mock_mkfs, mock_efi_part, mock_execute, mock_dispatch,
            mock_free_raid_device, mock_rescan):
        mock_efi_part.return_value = None
        mock_execute.side_effect = [
            ('451', None),  # sgdisk -F
            (None, None),  # sgdisk create part
            (None, None),  # partprobe
            (None, None),  # blkid
            ('/dev/sda12: dsfkgsdjfg', None),  # blkid
            ('452', None),  # sgdisk -F
            (None, None),  # sgdisk create part
            (None, None),  # partprobe
            (None, None),  # blkid
            ('/dev/sdb14: whatever', None),  # blkid
            (None, None),  # mdadm
        ]

        efi_part = raid_utils.prepare_boot_partitions_for_softraid(
            '/dev/md0', ['/dev/sda', '/dev/sdb'], None,
            target_boot_mode='uefi')

        mock_efi_part.assert_called_once_with('/dev/md0')
        expected = [
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('sgdisk', '-n', '0:451s:+550MiB', '-t', '0:ef00', '-c',
                      '0:uefi-holder-0', '/dev/sda'),
            mock.call('partprobe'),
            mock.call('blkid'),
            mock.call('blkid', '-l', '-t', 'PARTLABEL=uefi-holder-0',
                      '/dev/sda'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('sgdisk', '-n', '0:452s:+550MiB', '-t', '0:ef00', '-c',
                      '0:uefi-holder-1', '/dev/sdb'),
            mock.call('partprobe'),
            mock.call('blkid'),
            mock.call('blkid', '-l', '-t', 'PARTLABEL=uefi-holder-1',
                      '/dev/sdb'),
        ]
        mock_execute.assert_has_calls(expected, any_order=False)
        mock_mkfs.assert_has_calls([
            mock.call(path='/dev/md42', label='efi-part', fs='vfat'),
        ], any_order=False)
        self.assertEqual(efi_part, '/dev/md42')
        mock_rescan.assert_called_once_with('/dev/md42')

    @mock.patch.object(disk_utils, 'trigger_device_rescan', autospec=True)
    @mock.patch.object(raid_utils, 'get_next_free_raid_device', autospec=True,
                       return_value='/dev/md42')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(ilib_utils, 'execute', autospec=True)
    def test_prepare_boot_partitions_for_softraid_uefi_gpt_efi_provided(
            self, mock_execute, mock_dispatch, mock_free_raid_device,
            mock_rescan):
        mock_execute.side_effect = [
            ('451', None),  # sgdisk -F
            (None, None),  # sgdisk create part
            (None, None),  # partprobe
            (None, None),  # blkid
            ('/dev/sda12: dsfkgsdjfg', None),  # blkid
            ('452', None),  # sgdisk -F
            (None, None),  # sgdisk create part
            (None, None),  # partprobe
            (None, None),  # blkid
            ('/dev/sdb14: whatever', None),  # blkid
            (None, None),  # mdadm create
            (None, None),  # cp
            (None, None),  # wipefs
        ]

        efi_part = raid_utils.prepare_boot_partitions_for_softraid(
            '/dev/md0', ['/dev/sda', '/dev/sdb'], '/dev/md0p15',
            target_boot_mode='uefi')

        expected = [
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('sgdisk', '-n', '0:451s:+550MiB', '-t', '0:ef00', '-c',
                      '0:uefi-holder-0', '/dev/sda'),
            mock.call('partprobe'),
            mock.call('blkid'),
            mock.call('blkid', '-l', '-t', 'PARTLABEL=uefi-holder-0',
                      '/dev/sda'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('sgdisk', '-n', '0:452s:+550MiB', '-t', '0:ef00', '-c',
                      '0:uefi-holder-1', '/dev/sdb'),
            mock.call('partprobe'),
            mock.call('blkid'),
            mock.call('blkid', '-l', '-t', 'PARTLABEL=uefi-holder-1',
                      '/dev/sdb'),
            mock.call('mdadm', '--create', '/dev/md42', '--force', '--run',
                      '--metadata=1.0', '--level', '1', '--name', 'esp',
                      '--raid-devices', 2, '/dev/sda12', '/dev/sdb14'),
            mock.call('cp', '/dev/md0p15', '/dev/md42'),
            mock.call('wipefs', '-a', '/dev/md0p15')
        ]
        mock_execute.assert_has_calls(expected, any_order=False)
        self.assertEqual(efi_part, '/dev/md42')

    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(ilib_utils, 'execute', autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type', autospec=True,
                       return_value='msdos')
    def test_prepare_boot_partitions_for_softraid_bios_msdos(
            self, mock_label_scan, mock_execute, mock_dispatch):

        efi_part = raid_utils.prepare_boot_partitions_for_softraid(
            '/dev/md0', ['/dev/sda', '/dev/sdb'], 'notusedanyway',
            target_boot_mode='bios')

        expected = [
            mock.call('/dev/sda'),
            mock.call('/dev/sdb'),
        ]
        mock_label_scan.assert_has_calls(expected, any_order=False)
        self.assertIsNone(efi_part)

    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(ilib_utils, 'execute', autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type', autospec=True,
                       return_value='gpt')
    def test_prepare_boot_partitions_for_softraid_bios_gpt(
            self, mock_label_scan, mock_execute, mock_dispatch):

        mock_execute.side_effect = [
            ('whatever\n314', None),  # sgdisk -F
            (None, None),  # bios boot grub
            ('warning message\n914', None),  # sgdisk -F
            (None, None),  # bios boot grub
        ]

        efi_part = raid_utils.prepare_boot_partitions_for_softraid(
            '/dev/md0', ['/dev/sda', '/dev/sdb'], 'notusedanyway',
            target_boot_mode='bios')

        expected_scan = [
            mock.call('/dev/sda'),
            mock.call('/dev/sdb'),
        ]

        mock_label_scan.assert_has_calls(expected_scan, any_order=False)

        expected_exec = [
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('sgdisk', '-n', '0:314s:+2MiB', '-t', '0:ef02', '-c',
                      '0:bios-boot-part-0', '/dev/sda'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('sgdisk', '-n', '0:914s:+2MiB', '-t', '0:ef02', '-c',
                      '0:bios-boot-part-1', '/dev/sdb'),
        ]

        mock_execute.assert_has_calls(expected_exec, any_order=False)
        self.assertIsNone(efi_part)


@mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
class TestGetNextFreeRaidDevice(base.IronicAgentTest):

    def test_ok(self, mock_dispatch):
        mock_dispatch.return_value = \
            test_hardware.RAID_BLK_DEVICE_TEMPLATE_DEVICES
        result = raid_utils.get_next_free_raid_device()
        self.assertEqual('/dev/md2', result)
        mock_dispatch.assert_called_once_with('list_block_devices')

    def test_no_device(self, mock_dispatch):
        mock_dispatch.return_value = [
            hardware.BlockDevice(name=f'/dev/md{idx}', model='RAID',
                                 size=1765517033470, rotational=False,
                                 vendor="FooTastic", uuid="")
            for idx in range(128)
        ]
        self.assertRaises(errors.SoftwareRAIDError,
                          raid_utils.get_next_free_raid_device)

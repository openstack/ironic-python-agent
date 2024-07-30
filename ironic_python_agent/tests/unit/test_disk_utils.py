# Copyright 2014 Red Hat, Inc.
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

import json
import os
import stat
from unittest import mock

from ironic_lib import exception
from ironic_lib.tests import base
from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils.imageutils import QemuImgInfo
from oslo_utils import units

from ironic_python_agent import disk_utils
from ironic_python_agent.errors import InvalidImage
from ironic_python_agent import format_inspector
from ironic_python_agent import qemu_img

CONF = cfg.CONF


class MockFormatInspectorCls(object):
    def __init__(self, img_format='qcow2', virtual_size_mb=0, safe=False):
        self.img_format = img_format
        self.virtual_size_mb = virtual_size_mb
        self.safe = safe

    def __str__(self):
        return self.img_format

    @property
    def virtual_size(self):
        # NOTE(JayF): Allow the mock-user to input MBs but
        # backwards-calculate so code in _write_image can still work
        if self.virtual_size_mb == 0:
            return 0
        else:
            return (self.virtual_size_mb * units.Mi) + 1 - units.Mi

    def safety_check(self):
        return self.safe


def _get_fake_qemu_image_info(file_format='qcow2', virtual_size=0):
    fake_data = {'format': file_format, 'virtual-size': virtual_size, }
    return QemuImgInfo(cmd_output=json.dumps(fake_data), format='json')


@mock.patch.object(utils, 'execute', autospec=True)
class ListPartitionsTestCase(base.IronicLibTestCase):

    def test_correct(self, execute_mock):
        output = """
BYT;
/dev/sda:500107862016B:scsi:512:4096:msdos:ATA HGST HTS725050A7:;
1:1.00MiB:501MiB:500MiB:ext4::boot;
2:501MiB:476940MiB:476439MiB:::;
"""
        expected = [
            {'number': 1, 'start': 1, 'end': 501, 'size': 500,
             'filesystem': 'ext4', 'partition_name': '', 'flags': 'boot',
             'path': '/dev/fake1'},
            {'number': 2, 'start': 501, 'end': 476940, 'size': 476439,
             'filesystem': '', 'partition_name': '', 'flags': '',
             'path': '/dev/fake2'},
        ]
        execute_mock.return_value = (output, '')
        result = disk_utils.list_partitions('/dev/fake')
        self.assertEqual(expected, result)
        execute_mock.assert_called_once_with(
            'parted', '-s', '-m', '/dev/fake', 'unit', 'MiB', 'print',
            use_standard_locale=True)

    @mock.patch.object(disk_utils.LOG, 'warning', autospec=True)
    def test_incorrect(self, log_mock, execute_mock):
        output = """
BYT;
/dev/sda:500107862016B:scsi:512:4096:msdos:ATA HGST HTS725050A7:;
1:XX1076MiB:---:524MiB:ext4::boot;
"""
        execute_mock.return_value = (output, '')
        self.assertEqual([], disk_utils.list_partitions('/dev/fake'))
        self.assertEqual(1, log_mock.call_count)

    def test_correct_gpt_nvme(self, execute_mock):
        output = """
BYT;
/dev/vda:40960MiB:virtblk:512:512:gpt:Virtio Block Device:;
2:1.00MiB:2.00MiB:1.00MiB::Bios partition:bios_grub;
1:4.00MiB:5407MiB:5403MiB:ext4:Root partition:;
3:5407MiB:5507MiB:100MiB:fat16:Boot partition:boot, esp;
"""
        expected = [
            {'end': 2, 'number': 2, 'start': 1, 'flags': 'bios_grub',
             'filesystem': '', 'partition_name': 'Bios partition', 'size': 1,
             'path': '/dev/fake0p2'},
            {'end': 5407, 'number': 1, 'start': 4, 'flags': '',
             'filesystem': 'ext4', 'partition_name': 'Root partition',
             'size': 5403, 'path': '/dev/fake0p1'},
            {'end': 5507, 'number': 3, 'start': 5407,
             'flags': 'boot, esp', 'filesystem': 'fat16',
             'partition_name': 'Boot partition', 'size': 100,
             'path': '/dev/fake0p3'},
        ]
        execute_mock.return_value = (output, '')
        result = disk_utils.list_partitions('/dev/fake0')
        self.assertEqual(expected, result)
        execute_mock.assert_called_once_with(
            'parted', '-s', '-m', '/dev/fake0', 'unit', 'MiB', 'print',
            use_standard_locale=True)

    @mock.patch.object(disk_utils.LOG, 'warning', autospec=True)
    def test_incorrect_gpt(self, log_mock, execute_mock):
        output = """
BYT;
/dev/vda:40960MiB:virtblk:512:512:gpt:Virtio Block Device:;
2:XX1.00MiB:---:1.00MiB::primary:bios_grub;
"""
        execute_mock.return_value = (output, '')
        self.assertEqual([], disk_utils.list_partitions('/dev/fake'))
        self.assertEqual(1, log_mock.call_count)


@mock.patch.object(utils, 'execute', autospec=True)
class MakePartitionsTestCase(base.IronicLibTestCase):

    def setUp(self):
        super(MakePartitionsTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.root_mb = 1024
        self.swap_mb = 512
        self.ephemeral_mb = 0
        self.configdrive_mb = 0
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"
        self.efi_size = CONF.disk_utils.efi_system_partition_size
        self.bios_size = CONF.disk_utils.bios_boot_partition_size

    def _get_parted_cmd(self, dev, label=None):
        if label is None:
            label = 'msdos'

        return ['parted', '-a', 'optimal', '-s', dev,
                '--', 'unit', 'MiB', 'mklabel', label]

    def _add_efi_sz(self, x):
        return str(x + self.efi_size)

    def _add_bios_sz(self, x):
        return str(x + self.bios_size)

    def _test_make_partitions(self, mock_exc, boot_option, boot_mode='bios',
                              disk_label=None, cpu_arch=""):
        mock_exc.return_value = ('', '')
        disk_utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                                   self.ephemeral_mb, self.configdrive_mb,
                                   self.node_uuid, boot_option=boot_option,
                                   boot_mode=boot_mode, disk_label=disk_label,
                                   cpu_arch=cpu_arch)

        if boot_option == "local" and boot_mode == "uefi":
            expected_mkpart = ['mkpart', 'primary', 'fat32', '1',
                               self._add_efi_sz(1),
                               'set', '1', 'boot', 'on',
                               'mkpart', 'primary', 'linux-swap',
                               self._add_efi_sz(1), self._add_efi_sz(513),
                               'mkpart', 'primary', '', self._add_efi_sz(513),
                               self._add_efi_sz(1537)]
        else:
            if boot_option == "local":
                if disk_label == "gpt":
                    if cpu_arch.startswith('ppc64'):
                        expected_mkpart = ['mkpart', 'primary', '', '1', '9',
                                           'set', '1', 'prep', 'on',
                                           'mkpart', 'primary', 'linux-swap',
                                           '9', '521', 'mkpart', 'primary',
                                           '', '521', '1545']
                    else:
                        expected_mkpart = ['mkpart', 'primary', '', '1',
                                           self._add_bios_sz(1),
                                           'set', '1', 'bios_grub', 'on',
                                           'mkpart', 'primary', 'linux-swap',
                                           self._add_bios_sz(1),
                                           self._add_bios_sz(513),
                                           'mkpart', 'primary', '',
                                           self._add_bios_sz(513),
                                           self._add_bios_sz(1537)]
                elif cpu_arch.startswith('ppc64'):
                    expected_mkpart = ['mkpart', 'primary', '', '1', '9',
                                       'set', '1', 'boot', 'on',
                                       'set', '1', 'prep', 'on',
                                       'mkpart', 'primary', 'linux-swap',
                                       '9', '521', 'mkpart', 'primary',
                                       '', '521', '1545']
                else:
                    expected_mkpart = ['mkpart', 'primary', 'linux-swap', '1',
                                       '513', 'mkpart', 'primary', '', '513',
                                       '1537', 'set', '2', 'boot', 'on']
            else:
                expected_mkpart = ['mkpart', 'primary', 'linux-swap', '1',
                                   '513', 'mkpart', 'primary', '', '513',
                                   '1537']
        self.dev = 'fake-dev'
        parted_cmd = (self._get_parted_cmd(self.dev, disk_label)
                      + expected_mkpart)
        parted_call = mock.call(*parted_cmd, use_standard_locale=True)
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])

        sync_calls = [mock.call('sync'),
                      mock.call('udevadm', 'settle'),
                      mock.call('partprobe', self.dev, attempts=10),
                      mock.call('udevadm', 'settle'),
                      mock.call('sgdisk', '-v', self.dev)]

        mock_exc.assert_has_calls([parted_call, fuser_call] + sync_calls)

    def test_make_partitions(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="netboot")

    def test_make_partitions_local_boot(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="local")

    def test_make_partitions_local_boot_uefi(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="local",
                                   boot_mode="uefi", disk_label="gpt")

    def test_make_partitions_local_boot_gpt_bios(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="local",
                                   disk_label="gpt")

    def test_make_partitions_disk_label_gpt(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="netboot",
                                   disk_label="gpt")

    def test_make_partitions_mbr_with_prep(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="local",
                                   disk_label="msdos", cpu_arch="ppc64le")

    def test_make_partitions_gpt_with_prep(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="local",
                                   disk_label="gpt", cpu_arch="ppc64le")

    def test_make_partitions_with_ephemeral(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        self.dev = 'fake-dev'
        cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        mock_exc.return_value = ('', '')
        disk_utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                                   self.ephemeral_mb, self.configdrive_mb,
                                   self.node_uuid)

        parted_call = mock.call(*cmd, use_standard_locale=True)
        mock_exc.assert_has_calls([parted_call])

    def test_make_partitions_with_iscsi_device(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        self.dev = '/dev/iqn.2008-10.org.openstack:%s.fake-9' % self.node_uuid
        ep = '/dev/iqn.2008-10.org.openstack:%s.fake-9-part1' % self.node_uuid
        swap = ('/dev/iqn.2008-10.org.openstack:%s.fake-9-part2'
                % self.node_uuid)
        root = ('/dev/iqn.2008-10.org.openstack:%s.fake-9-part3'
                % self.node_uuid)
        expected_result = {'ephemeral': ep,
                           'swap': swap,
                           'root': root}
        cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        mock_exc.return_value = ('', '')
        result = disk_utils.make_partitions(
            self.dev, self.root_mb, self.swap_mb, self.ephemeral_mb,
            self.configdrive_mb, self.node_uuid)

        parted_call = mock.call(*cmd, use_standard_locale=True)
        mock_exc.assert_has_calls([parted_call])
        self.assertEqual(expected_result, result)

    def test_make_partitions_with_nvme_device(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        self.dev = '/dev/nvmefake-9'
        ep = '/dev/nvmefake-9p1'
        swap = '/dev/nvmefake-9p2'
        root = '/dev/nvmefake-9p3'
        expected_result = {'ephemeral': ep,
                           'swap': swap,
                           'root': root}
        cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        mock_exc.return_value = ('', '')
        result = disk_utils.make_partitions(
            self.dev, self.root_mb, self.swap_mb, self.ephemeral_mb,
            self.configdrive_mb, self.node_uuid)

        parted_call = mock.call(*cmd, use_standard_locale=True)
        mock_exc.assert_has_calls([parted_call])
        self.assertEqual(expected_result, result)

    def test_make_partitions_with_local_device(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        self.dev = 'fake-dev'
        expected_result = {'ephemeral': 'fake-dev1',
                           'swap': 'fake-dev2',
                           'root': 'fake-dev3'}
        cmd = self._get_parted_cmd(self.dev) + expected_mkpart
        mock_exc.return_value = ('', '')
        result = disk_utils.make_partitions(
            self.dev, self.root_mb, self.swap_mb, self.ephemeral_mb,
            self.configdrive_mb, self.node_uuid)

        parted_call = mock.call(*cmd, use_standard_locale=True)
        mock_exc.assert_has_calls([parted_call])
        self.assertEqual(expected_result, result)


@mock.patch.object(utils, 'execute', autospec=True)
class DestroyMetaDataTestCase(base.IronicLibTestCase):

    def setUp(self):
        super(DestroyMetaDataTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_destroy_disk_metadata_4096(self, mock_exec):
        mock_exec.side_effect = iter([
            (None, None),
            ('4096\n', None),
            ('524288\n', None),
            (None, None),
            (None, None),
            (None, None),
            (None, None)])

        expected_calls = [mock.call('wipefs', '--force', '--all', 'fake-dev',
                                    use_standard_locale=True),
                          mock.call('blockdev', '--getss', 'fake-dev'),
                          mock.call('blockdev', '--getsize64', 'fake-dev'),
                          mock.call('dd', 'bs=4096', 'if=/dev/zero',
                                    'of=fake-dev', 'count=5', 'oflag=direct',
                                    use_standard_locale=True),
                          mock.call('dd', 'bs=4096', 'if=/dev/zero',
                                    'of=fake-dev', 'count=5', 'oflag=direct',
                                    'seek=123', use_standard_locale=True),
                          mock.call('sgdisk', '-Z', 'fake-dev',
                                    use_standard_locale=True),
                          mock.call('fuser', self.dev, check_exit_code=[0, 1])]
        disk_utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)

    def test_destroy_disk_metadata(self, mock_exec):
        # Note(TheJulia): This list will get-reused, but only the second
        # execution returning a string is needed for the test as otherwise
        # command output is not used.
        mock_exec.side_effect = iter([
            (None, None),
            ('512\n', None),
            ('524288\n', None),
            (None, None),
            (None, None),
            (None, None),
            (None, None)])

        expected_calls = [mock.call('wipefs', '--force', '--all', 'fake-dev',
                                    use_standard_locale=True),
                          mock.call('blockdev', '--getss', 'fake-dev'),
                          mock.call('blockdev', '--getsize64', 'fake-dev'),
                          mock.call('dd', 'bs=512', 'if=/dev/zero',
                                    'of=fake-dev', 'count=33', 'oflag=direct',
                                    use_standard_locale=True),
                          mock.call('dd', 'bs=512', 'if=/dev/zero',
                                    'of=fake-dev', 'count=33', 'oflag=direct',
                                    'seek=991', use_standard_locale=True),
                          mock.call('sgdisk', '-Z', 'fake-dev',
                                    use_standard_locale=True),
                          mock.call('fuser', self.dev, check_exit_code=[0, 1])]
        disk_utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)

    def test_destroy_disk_metadata_wipefs_fail(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError

        expected_call = [mock.call('wipefs', '--force', '--all', 'fake-dev',
                                   use_standard_locale=True)]
        self.assertRaises(processutils.ProcessExecutionError,
                          disk_utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_call)

    def test_destroy_disk_metadata_sgdisk_fail(self, mock_exec):
        expected_calls = [mock.call('wipefs', '--force', '--all', 'fake-dev',
                                    use_standard_locale=True),
                          mock.call('blockdev', '--getss', 'fake-dev'),
                          mock.call('blockdev', '--getsize64', 'fake-dev'),
                          mock.call('dd', 'bs=512', 'if=/dev/zero',
                                    'of=fake-dev', 'count=33', 'oflag=direct',
                                    use_standard_locale=True),
                          mock.call('dd', 'bs=512', 'if=/dev/zero',
                                    'of=fake-dev', 'count=33', 'oflag=direct',
                                    'seek=991', use_standard_locale=True),
                          mock.call('sgdisk', '-Z', 'fake-dev',
                                    use_standard_locale=True)]
        mock_exec.side_effect = iter([
            (None, None),
            ('512\n', None),
            ('524288\n', None),
            (None, None),
            (None, None),
            processutils.ProcessExecutionError()])
        self.assertRaises(processutils.ProcessExecutionError,
                          disk_utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)

    def test_destroy_disk_metadata_wipefs_not_support_force(self, mock_exec):
        mock_exec.side_effect = iter([
            processutils.ProcessExecutionError(description='--force'),
            (None, None),
            ('512\n', None),
            ('524288\n', None),
            (None, None),
            (None, None),
            (None, None),
            (None, None)])

        expected_call = [mock.call('wipefs', '--force', '--all', 'fake-dev',
                                   use_standard_locale=True),
                         mock.call('wipefs', '--all', 'fake-dev',
                                   use_standard_locale=True)]
        disk_utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_call)

    def test_destroy_disk_metadata_ebr(self, mock_exec):
        expected_calls = [mock.call('wipefs', '--force', '--all', 'fake-dev',
                                    use_standard_locale=True),
                          mock.call('blockdev', '--getss', 'fake-dev'),
                          mock.call('blockdev', '--getsize64', 'fake-dev'),
                          mock.call('dd', 'bs=512', 'if=/dev/zero',
                                    'of=fake-dev', 'count=2', 'oflag=direct',
                                    use_standard_locale=True),
                          mock.call('sgdisk', '-Z', 'fake-dev',
                                    use_standard_locale=True)]
        mock_exec.side_effect = iter([
            (None, None),
            ('512\n', None),
            ('1024\n', None),  # an EBR is 2 sectors
            (None, None),
            (None, None),
            (None, None),
            (None, None)])
        disk_utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)

    def test_destroy_disk_metadata_tiny_partition(self, mock_exec):
        expected_calls = [mock.call('wipefs', '--force', '--all', 'fake-dev',
                                    use_standard_locale=True),
                          mock.call('blockdev', '--getss', 'fake-dev'),
                          mock.call('blockdev', '--getsize64', 'fake-dev'),
                          mock.call('dd', 'bs=512', 'if=/dev/zero',
                                    'of=fake-dev', 'count=33', 'oflag=direct',
                                    use_standard_locale=True),
                          mock.call('dd', 'bs=512', 'if=/dev/zero',
                                    'of=fake-dev', 'count=33', 'oflag=direct',
                                    'seek=9', use_standard_locale=True),
                          mock.call('sgdisk', '-Z', 'fake-dev',
                                    use_standard_locale=True)]
        mock_exec.side_effect = iter([
            (None, None),
            ('512\n', None),
            ('21504\n', None),
            (None, None),
            (None, None),
            (None, None),
            (None, None)])
        disk_utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)


@mock.patch.object(utils, 'execute', autospec=True)
class GetDeviceByteSizeTestCase(base.IronicLibTestCase):

    def setUp(self):
        super(GetDeviceByteSizeTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_get_dev_byte_size(self, mock_exec):
        mock_exec.return_value = ("64", "")
        expected_call = [mock.call('blockdev', '--getsize64', self.dev)]
        disk_utils.get_dev_byte_size(self.dev)
        mock_exec.assert_has_calls(expected_call)


@mock.patch.object(disk_utils, 'dd', autospec=True)
@mock.patch.object(qemu_img, 'convert_image', autospec=True)
class PopulateImageTestCase(base.IronicLibTestCase):

    def test_populate_raw_image(self, mock_cg, mock_dd):
        source_format = 'raw'
        disk_utils.populate_image('src', 'dst',
                                  source_format=source_format,
                                  is_raw=True)
        mock_dd.assert_called_once_with('src', 'dst', conv_flags=None)
        self.assertFalse(mock_cg.called)

    def test_populate_qcow2_image(self, mock_cg, mock_dd):
        source_format = 'qcow2'
        disk_utils.populate_image('src', 'dst',
                                  source_format=source_format, is_raw=False)
        mock_cg.assert_called_once_with('src', 'dst', 'raw', True,
                                        sparse_size='0',
                                        source_format=source_format)
        self.assertFalse(mock_dd.called)


@mock.patch('time.sleep', lambda sec: None)
class OtherFunctionTestCase(base.IronicLibTestCase):

    @mock.patch.object(os, 'stat', autospec=True)
    @mock.patch.object(stat, 'S_ISBLK', autospec=True)
    def test_is_block_device_works(self, mock_is_blk, mock_os):
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        mock_is_blk.return_value = True
        mock_os().st_mode = 10000
        self.assertTrue(disk_utils.is_block_device(device))
        mock_is_blk.assert_called_once_with(mock_os().st_mode)

    @mock.patch.object(os, 'stat', autospec=True)
    def test_is_block_device_raises(self, mock_os):
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        mock_os.side_effect = OSError
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils.is_block_device, device)
        mock_os.assert_has_calls([mock.call(device)] * 3)

    @mock.patch.object(os, 'stat', autospec=True)
    def test_is_block_device_attempts(self, mock_os):
        CONF.set_override('partition_detection_attempts', 2,
                          group='disk_utils')
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        mock_os.side_effect = OSError
        self.assertRaises(exception.InstanceDeployFailure,
                          disk_utils.is_block_device, device)
        mock_os.assert_has_calls([mock.call(device)] * 2)

    def _test_count_mbr_partitions(self, output, mock_execute):
        mock_execute.return_value = (output, '')
        out = disk_utils.count_mbr_partitions('/dev/fake')
        mock_execute.assert_called_once_with('partprobe', '-d', '-s',
                                             '/dev/fake',
                                             use_standard_locale=True)
        return out

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_count_mbr_partitions(self, mock_execute):
        output = "/dev/fake: msdos partitions 1 2 3 <5 6>"
        pp, lp = self._test_count_mbr_partitions(output, mock_execute)
        self.assertEqual(3, pp)
        self.assertEqual(2, lp)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_count_mbr_partitions_no_logical_partitions(self, mock_execute):
        output = "/dev/fake: msdos partitions 1 2"
        pp, lp = self._test_count_mbr_partitions(output, mock_execute)
        self.assertEqual(2, pp)
        self.assertEqual(0, lp)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_count_mbr_partitions_wrong_partition_table(self, mock_execute):
        output = "/dev/fake: gpt partitions 1 2 3 4 5 6"
        mock_execute.return_value = (output, '')
        self.assertRaises(ValueError, disk_utils.count_mbr_partitions,
                          '/dev/fake')
        mock_execute.assert_called_once_with('partprobe', '-d', '-s',
                                             '/dev/fake',
                                             use_standard_locale=True)

    @mock.patch.object(disk_utils, 'get_device_information', autospec=True)
    def test_block_uuid(self, mock_get_device_info):
        mock_get_device_info.return_value = {'UUID': '123',
                                             'PARTUUID': '123456'}
        self.assertEqual('123', disk_utils.block_uuid('/dev/fake'))
        mock_get_device_info.assert_called_once_with(
            '/dev/fake', fields=['UUID', 'PARTUUID'])

    @mock.patch.object(disk_utils, 'get_device_information', autospec=True)
    def test_block_uuid_fallback_to_uuid(self, mock_get_device_info):
        mock_get_device_info.return_value = {'PARTUUID': '123456'}
        self.assertEqual('123456', disk_utils.block_uuid('/dev/fake'))
        mock_get_device_info.assert_called_once_with(
            '/dev/fake', fields=['UUID', 'PARTUUID'])


@mock.patch.object(utils, 'execute', autospec=True)
class FixGptStructsTestCases(base.IronicLibTestCase):

    def setUp(self):
        super(FixGptStructsTestCases, self).setUp()
        self.dev = "/dev/fake"
        self.config_part_label = "config-2"
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_fix_gpt_structs_fix_required(self, mock_execute):
        sgdisk_v_output = """
Problem: The secondary header's self-pointer indicates that it doesn't reside
at the end of the disk. If you've added a disk to a RAID array, use the 'e'
option on the experts' menu to adjust the secondary header's and partition
table's locations.

Identified 1 problems!
"""
        mock_execute.return_value = (sgdisk_v_output, '')
        execute_calls = [
            mock.call('sgdisk', '-v', '/dev/fake'),
            mock.call('sgdisk', '-e', '/dev/fake')
        ]
        disk_utils._fix_gpt_structs('/dev/fake', self.node_uuid)
        mock_execute.assert_has_calls(execute_calls)

    def test_fix_gpt_structs_fix_not_required(self, mock_execute):
        mock_execute.return_value = ('', '')

        disk_utils._fix_gpt_structs('/dev/fake', self.node_uuid)
        mock_execute.assert_called_once_with('sgdisk', '-v', '/dev/fake')

    @mock.patch.object(disk_utils.LOG, 'error', autospec=True)
    def test_fix_gpt_structs_exc(self, mock_log, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Failed to fix GPT data structures on disk',
                               disk_utils._fix_gpt_structs,
                               self.dev, self.node_uuid)
        mock_execute.assert_called_once_with('sgdisk', '-v', '/dev/fake')
        self.assertEqual(1, mock_log.call_count)


@mock.patch.object(utils, 'execute', autospec=True)
class TriggerDeviceRescanTestCase(base.IronicLibTestCase):
    def test_trigger(self, mock_execute):
        self.assertTrue(disk_utils.trigger_device_rescan('/dev/fake'))
        mock_execute.assert_has_calls([
            mock.call('sync'),
            mock.call('udevadm', 'settle'),
            mock.call('partprobe', '/dev/fake', attempts=10),
            mock.call('udevadm', 'settle'),
            mock.call('sgdisk', '-v', '/dev/fake'),
        ])

    def test_custom_attempts(self, mock_execute):
        self.assertTrue(
            disk_utils.trigger_device_rescan('/dev/fake', attempts=1))
        mock_execute.assert_has_calls([
            mock.call('sync'),
            mock.call('udevadm', 'settle'),
            mock.call('partprobe', '/dev/fake', attempts=1),
            mock.call('udevadm', 'settle'),
            mock.call('sgdisk', '-v', '/dev/fake'),
        ])

    def test_fails(self, mock_execute):
        mock_execute.side_effect = [('', '')] * 4 + [
            processutils.ProcessExecutionError
        ]
        self.assertFalse(disk_utils.trigger_device_rescan('/dev/fake'))
        mock_execute.assert_has_calls([
            mock.call('sync'),
            mock.call('udevadm', 'settle'),
            mock.call('partprobe', '/dev/fake', attempts=10),
            mock.call('udevadm', 'settle'),
            mock.call('sgdisk', '-v', '/dev/fake'),
        ])


BLKID_PROBE = ("""
/dev/disk/by-path/ip-10.1.0.52:3260-iscsi-iqn.2008-10.org.openstack: """
               """PTUUID="123456" PTTYPE="gpt"
               """)

LSBLK_NORMAL = (
    'UUID="123" BLOCK_SIZE="512" TYPE="vfat" '
    'PARTLABEL="EFI System Partition" PARTUUID="123456"'
)


@mock.patch.object(utils, 'execute', autospec=True)
class GetDeviceInformationTestCase(base.IronicLibTestCase):

    def test_normal(self, mock_execute):
        mock_execute.return_value = LSBLK_NORMAL, ""
        result = disk_utils.get_device_information('/dev/fake')
        self.assertEqual(
            {'UUID': '123', 'BLOCK_SIZE': '512', 'TYPE': 'vfat',
             'PARTLABEL': 'EFI System Partition', 'PARTUUID': '123456'},
            result
        )
        mock_execute.assert_called_once_with(
            'lsblk', '/dev/fake', '--pairs', '--bytes', '--ascii', '--nodeps',
            '--output-all', use_standard_locale=True)

    def test_fields(self, mock_execute):
        mock_execute.return_value = LSBLK_NORMAL, ""
        result = disk_utils.get_device_information('/dev/fake',
                                                   fields=['UUID', 'LABEL'])
        # No filtering on our side, so returning all fake fields
        self.assertEqual(
            {'UUID': '123', 'BLOCK_SIZE': '512', 'TYPE': 'vfat',
             'PARTLABEL': 'EFI System Partition', 'PARTUUID': '123456'},
            result
        )
        mock_execute.assert_called_once_with(
            'lsblk', '/dev/fake', '--pairs', '--bytes', '--ascii', '--nodeps',
            '--output', 'UUID,LABEL',
            use_standard_locale=True)

    def test_empty(self, mock_execute):
        mock_execute.return_value = "\n", ""
        result = disk_utils.get_device_information('/dev/fake')
        self.assertEqual({}, result)
        mock_execute.assert_called_once_with(
            'lsblk', '/dev/fake', '--pairs', '--bytes', '--ascii', '--nodeps',
            '--output-all', use_standard_locale=True)


@mock.patch.object(utils, 'execute', autospec=True)
class GetPartitionTableTypeTestCase(base.IronicLibTestCase):
    def test_gpt(self, mocked_execute):
        self._test_by_type(mocked_execute, 'gpt', 'gpt')

    def test_msdos(self, mocked_execute):
        self._test_by_type(mocked_execute, 'msdos', 'msdos')

    def test_unknown(self, mocked_execute):
        self._test_by_type(mocked_execute, 'whatever', 'unknown')

    def _test_by_type(self, mocked_execute, table_type_output,
                      expected_table_type):
        parted_ret = PARTED_OUTPUT_UNFORMATTED.format(table_type_output)

        mocked_execute.side_effect = [
            (parted_ret, None),
        ]

        ret = disk_utils.get_partition_table_type('hello')
        mocked_execute.assert_called_once_with(
            'parted', '--script', 'hello', '--', 'print',
            use_standard_locale=True)
        self.assertEqual(expected_table_type, ret)


PARTED_OUTPUT_UNFORMATTED = '''Model: whatever
Disk /dev/sda: 450GB
Sector size (logical/physical): 512B/512B
Partition Table: {}
Disk Flags:

Number  Start   End     Size    File system  Name  Flags
14      1049kB  5243kB  4194kB                     bios_grub
15      5243kB  116MB   111MB   fat32              boot, esp
 1      116MB   2361MB  2245MB  ext4
'''


@mock.patch.object(disk_utils, 'list_partitions', autospec=True)
@mock.patch.object(disk_utils, 'get_partition_table_type', autospec=True)
class FindEfiPartitionTestCase(base.IronicLibTestCase):

    def test_find_efi_partition(self, mocked_type, mocked_parts):
        mocked_parts.return_value = [
            {'number': '1', 'flags': ''},
            {'number': '14', 'flags': 'bios_grub'},
            {'number': '15', 'flags': 'esp, boot'},
        ]
        ret = disk_utils.find_efi_partition('/dev/sda')
        self.assertEqual({'number': '15', 'flags': 'esp, boot'}, ret)

    def test_find_efi_partition_only_boot_flag_gpt(self, mocked_type,
                                                   mocked_parts):
        mocked_type.return_value = 'gpt'
        mocked_parts.return_value = [
            {'number': '1', 'flags': ''},
            {'number': '14', 'flags': 'bios_grub'},
            {'number': '15', 'flags': 'boot'},
        ]
        ret = disk_utils.find_efi_partition('/dev/sda')
        self.assertEqual({'number': '15', 'flags': 'boot'}, ret)

    def test_find_efi_partition_only_boot_flag_mbr(self, mocked_type,
                                                   mocked_parts):
        mocked_type.return_value = 'msdos'
        mocked_parts.return_value = [
            {'number': '1', 'flags': ''},
            {'number': '14', 'flags': 'bios_grub'},
            {'number': '15', 'flags': 'boot'},
        ]
        self.assertIsNone(disk_utils.find_efi_partition('/dev/sda'))

    def test_find_efi_partition_not_found(self, mocked_type, mocked_parts):
        mocked_parts.return_value = [
            {'number': '1', 'flags': ''},
            {'number': '14', 'flags': 'bios_grub'},
        ]
        self.assertIsNone(disk_utils.find_efi_partition('/dev/sda'))


class WaitForDisk(base.IronicLibTestCase):

    def setUp(self):
        super(WaitForDisk, self).setUp()
        CONF.set_override('check_device_interval', .01,
                          group='disk_partitioner')
        CONF.set_override('check_device_max_retries', 2,
                          group='disk_partitioner')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_wait_for_disk_to_become_available(self, mock_exc):
        mock_exc.return_value = ('', '')
        disk_utils.wait_for_disk_to_become_available('fake-dev')
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])
        self.assertEqual(1, mock_exc.call_count)
        mock_exc.assert_has_calls([fuser_call])

    @mock.patch.object(utils, 'execute', autospec=True,
                       side_effect=processutils.ProcessExecutionError(
                           stderr='fake'))
    def test_wait_for_disk_to_become_available_no_fuser(self, mock_exc):
        self.assertRaises(exception.IronicException,
                          disk_utils.wait_for_disk_to_become_available,
                          'fake-dev')
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])
        self.assertEqual(2, mock_exc.call_count)
        mock_exc.assert_has_calls([fuser_call, fuser_call])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_wait_for_disk_to_become_available_device_in_use_psmisc(
            self, mock_exc):
        # Test that the device is not available. This version has the 'psmisc'
        # version of 'fuser' values for stdout and stderr.
        # NOTE(TheJulia): Looks like fuser returns the actual list of pids
        # in the stdout output, where as all other text is returned in
        # stderr.
        # The 'psmisc' version has a leading space character in stdout. The
        # filename is output to stderr
        mock_exc.side_effect = [(' 1234   ', 'fake-dev: '),
                                (' 15503  3919 15510 15511', 'fake-dev:')]
        expected_error = ('Processes with the following PIDs are '
                          'holding device fake-dev: 15503, 3919, 15510, '
                          '15511. Timed out waiting for completion.')
        self.assertRaisesRegex(
            exception.IronicException,
            expected_error,
            disk_utils.wait_for_disk_to_become_available,
            'fake-dev')
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])
        self.assertEqual(2, mock_exc.call_count)
        mock_exc.assert_has_calls([fuser_call, fuser_call])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_wait_for_disk_to_become_available_device_in_use_busybox(
            self, mock_exc):
        # Test that the device is not available. This version has the 'busybox'
        # version of 'fuser' values for stdout and stderr.
        # NOTE(TheJulia): Looks like fuser returns the actual list of pids
        # in the stdout output, where as all other text is returned in
        # stderr.
        # The 'busybox' version does not have a leading space character in
        # stdout. Also nothing is output to stderr.
        mock_exc.side_effect = [('1234', ''),
                                ('15503  3919 15510 15511', '')]
        expected_error = ('Processes with the following PIDs are '
                          'holding device fake-dev: 15503, 3919, 15510, '
                          '15511. Timed out waiting for completion.')
        self.assertRaisesRegex(
            exception.IronicException,
            expected_error,
            disk_utils.wait_for_disk_to_become_available,
            'fake-dev')
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])
        self.assertEqual(2, mock_exc.call_count)
        mock_exc.assert_has_calls([fuser_call, fuser_call])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_wait_for_disk_to_become_available_no_device(self, mock_exc):
        # NOTE(TheJulia): Looks like fuser returns the actual list of pids
        # in the stdout output, where as all other text is returned in
        # stderr.

        mock_exc.return_value = ('', 'Specified filename /dev/fake '
                                     'does not exist.')
        expected_error = ('Fuser exited with "Specified filename '
                          '/dev/fake does not exist." while checking '
                          'locks for device fake-dev. Timed out waiting '
                          'for completion.')
        self.assertRaisesRegex(
            exception.IronicException,
            expected_error,
            disk_utils.wait_for_disk_to_become_available,
            'fake-dev')
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])
        self.assertEqual(2, mock_exc.call_count)
        mock_exc.assert_has_calls([fuser_call, fuser_call])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_wait_for_disk_to_become_available_dev_becomes_avail_psmisc(
            self, mock_exc):
        # Test that initially device is not available but then becomes
        # available. This version has the 'psmisc' version of 'fuser' values
        # for stdout and stderr.
        # The 'psmisc' version has a leading space character in stdout. The
        # filename is output to stderr
        mock_exc.side_effect = [(' 1234   ', 'fake-dev: '),
                                ('', '')]
        disk_utils.wait_for_disk_to_become_available('fake-dev')
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])
        self.assertEqual(2, mock_exc.call_count)
        mock_exc.assert_has_calls([fuser_call, fuser_call])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_wait_for_disk_to_become_available_dev_becomes_avail_busybox(
            self, mock_exc):
        # Test that initially device is not available but then becomes
        # available. This version has the 'busybox' version of 'fuser' values
        # for stdout and stderr.
        # The 'busybox' version does not have a leading space character in
        # stdout. Also nothing is output to stderr.
        mock_exc.side_effect = [('1234 5895', ''),
                                ('', '')]
        disk_utils.wait_for_disk_to_become_available('fake-dev')
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, check_exit_code=[0, 1])
        self.assertEqual(2, mock_exc.call_count)
        mock_exc.assert_has_calls([fuser_call, fuser_call])


class GetAndValidateImageFormat(base.IronicLibTestCase):
    @mock.patch.object(disk_utils, '_image_inspection', autospec=True)
    @mock.patch('os.path.getsize', autospec=True)
    def test_happy_raw(self, mock_size, mock_ii):
        """Valid raw image"""
        CONF.set_override('disable_deep_image_inspection', False)
        mock_size.return_value = 13
        fmt = 'raw'
        self.assertEqual(
            (fmt, 13),
            disk_utils.get_and_validate_image_format('/fake/path', fmt))
        mock_ii.assert_not_called()
        mock_size.assert_called_once_with('/fake/path')

    @mock.patch.object(disk_utils, '_image_inspection', autospec=True)
    def test_happy_qcow2(self, mock_ii):
        """Valid qcow2 image"""
        CONF.set_override('disable_deep_image_inspection', False)
        fmt = 'qcow2'
        mock_ii.return_value = MockFormatInspectorCls(fmt, 0, True)
        self.assertEqual(
            (fmt, 0),
            disk_utils.get_and_validate_image_format('/fake/path', fmt)
        )
        mock_ii.assert_called_once_with('/fake/path')

    @mock.patch.object(disk_utils, '_image_inspection', autospec=True)
    def test_format_type_disallowed(self, mock_ii):
        """qcow3 images are not allowed in default config"""
        CONF.set_override('disable_deep_image_inspection', False)
        fmt = 'qcow3'
        mock_ii.return_value = MockFormatInspectorCls(fmt, 0, True)
        self.assertRaises(InvalidImage,
                          disk_utils.get_and_validate_image_format,
                          '/fake/path', fmt)
        mock_ii.assert_called_once_with('/fake/path')

    @mock.patch.object(disk_utils, '_image_inspection', autospec=True)
    def test_format_mismatch(self, mock_ii):
        """ironic_disk_format=qcow2, but we detect it as a qcow3"""
        CONF.set_override('disable_deep_image_inspection', False)
        fmt = 'qcow2'
        mock_ii.return_value = MockFormatInspectorCls('qcow3', 0, True)
        self.assertRaises(InvalidImage,
                          disk_utils.get_and_validate_image_format,
                          '/fake/path', fmt)

    @mock.patch.object(disk_utils, '_image_inspection', autospec=True)
    @mock.patch.object(qemu_img, 'image_info', autospec=True)
    def test_format_mismatch_but_disabled(self, mock_info, mock_ii):
        """qcow3 ironic_disk_format ignored because deep inspection disabled"""
        CONF.set_override('disable_deep_image_inspection', True)
        fmt = 'qcow2'
        fake_info = _get_fake_qemu_image_info(file_format=fmt, virtual_size=0)
        qemu_img.image_info.return_value = fake_info
        # note the input is qcow3, the output is qcow2: this mismatch is
        # forbidden if CONF.disable_deep_image_inspection is False
        self.assertEqual(
            (fmt, 0),
            disk_utils.get_and_validate_image_format('/fake/path', 'qcow3'))
        mock_ii.assert_not_called()
        mock_info.assert_called_once()

    @mock.patch.object(disk_utils, '_image_inspection', autospec=True)
    @mock.patch.object(qemu_img, 'image_info', autospec=True)
    def test_safety_check_fail_but_disabled(self, mock_info, mock_ii):
        """unsafe image ignored because inspection is disabled"""
        CONF.set_override('disable_deep_image_inspection', True)
        fmt = 'qcow2'
        fake_info = _get_fake_qemu_image_info(file_format=fmt, virtual_size=0)
        qemu_img.image_info.return_value = fake_info
        # note the input is qcow3, the output is qcow2: this mismatch is
        # forbidden if CONF.disable_deep_image_inspection is False
        self.assertEqual(
            (fmt, 0),
            disk_utils.get_and_validate_image_format('/fake/path', 'qcow3'))
        mock_ii.assert_not_called()
        mock_info.assert_called_once()


class ImageInspectionTest(base.IronicLibTestCase):
    @mock.patch.object(format_inspector, 'detect_file_format', autospec=True)
    def test_image_inspection_pass(self, mock_fi):
        inspector = MockFormatInspectorCls('qcow2', 0, True)
        mock_fi.return_value = inspector
        self.assertEqual(inspector, disk_utils._image_inspection('/fake/path'))

    @mock.patch.object(format_inspector, 'detect_file_format', autospec=True)
    def test_image_inspection_fail_safety_check(self, mock_fi):
        inspector = MockFormatInspectorCls('qcow2', 0, False)
        mock_fi.return_value = inspector
        self.assertRaises(InvalidImage, disk_utils._image_inspection,
                          '/fake/path')

    @mock.patch.object(format_inspector, 'detect_file_format', autospec=True)
    def test_image_inspection_fail_format_error(self, mock_fi):
        mock_fi.side_effect = format_inspector.ImageFormatError
        self.assertRaises(InvalidImage, disk_utils._image_inspection,
                          '/fake/path')

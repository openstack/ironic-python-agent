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

import gzip
import shutil
import tempfile
from unittest import mock

from ironic_lib import disk_partitioner
from ironic_lib import disk_utils
from ironic_lib import exception
from ironic_lib import utils
from oslo_concurrency import processutils
import requests

from ironic_python_agent import partition_utils
from ironic_python_agent.tests.unit import base


@mock.patch.object(shutil, 'copyfileobj', autospec=True)
@mock.patch.object(requests, 'get', autospec=True)
class GetConfigdriveTestCase(base.IronicAgentTest):

    @mock.patch.object(gzip, 'GzipFile', autospec=True)
    def test_get_configdrive(self, mock_gzip, mock_requests, mock_copy):
        mock_requests.return_value = mock.MagicMock(content='Zm9vYmFy')
        tempdir = tempfile.mkdtemp()
        (size, path) = partition_utils.get_configdrive('http://1.2.3.4/cd',
                                                       'fake-node-uuid',
                                                       tempdir=tempdir)
        self.assertTrue(path.startswith(tempdir))
        mock_requests.assert_called_once_with('http://1.2.3.4/cd')
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_get_configdrive_binary(self, mock_requests, mock_copy):
        mock_requests.return_value = mock.MagicMock(content=b'content')
        tempdir = tempfile.mkdtemp()
        (size, path) = partition_utils.get_configdrive('http://1.2.3.4/cd',
                                                       'fake-node-uuid',
                                                       tempdir=tempdir)
        self.assertTrue(path.startswith(tempdir))
        self.assertEqual(b'content', open(path, 'rb').read())
        mock_requests.assert_called_once_with('http://1.2.3.4/cd')
        self.assertFalse(mock_copy.called)

    @mock.patch.object(gzip, 'GzipFile', autospec=True)
    def test_get_configdrive_base64_string(self, mock_gzip, mock_requests,
                                           mock_copy):
        partition_utils.get_configdrive('Zm9vYmFy', 'fake-node-uuid')
        self.assertFalse(mock_requests.called)
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_get_configdrive_bad_url(self, mock_requests, mock_copy):
        mock_requests.side_effect = requests.exceptions.RequestException
        self.assertRaises(exception.InstanceDeployFailure,
                          partition_utils.get_configdrive,
                          'http://1.2.3.4/cd', 'fake-node-uuid')
        self.assertFalse(mock_copy.called)

    def test_get_configdrive_base64_error(self, mock_requests, mock_copy):
        self.assertRaises(exception.InstanceDeployFailure,
                          partition_utils.get_configdrive,
                          'malformed', 'fake-node-uuid')
        self.assertFalse(mock_copy.called)

    @mock.patch.object(gzip, 'GzipFile', autospec=True)
    def test_get_configdrive_gzip_error(self, mock_gzip, mock_requests,
                                        mock_copy):
        mock_requests.return_value = mock.MagicMock(content='Zm9vYmFy')
        mock_copy.side_effect = IOError
        self.assertRaises(exception.InstanceDeployFailure,
                          partition_utils.get_configdrive,
                          'http://1.2.3.4/cd', 'fake-node-uuid')
        mock_requests.assert_called_once_with('http://1.2.3.4/cd')
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)


@mock.patch.object(utils, 'execute', autospec=True)
class GetLabelledPartitionTestCases(base.IronicAgentTest):

    def setUp(self):
        super(GetLabelledPartitionTestCases, self).setUp()
        self.dev = "/dev/fake"
        self.config_part_label = "config-2"
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_get_partition_present(self, mock_execute):
        lsblk_output = 'NAME="fake12" LABEL="config-2"\n'
        part_result = '/dev/fake12'
        mock_execute.side_effect = [(None, ''), (lsblk_output, '')]
        result = partition_utils.get_labelled_partition(self.dev,
                                                        self.config_part_label,
                                                        self.node_uuid)
        self.assertEqual(part_result, result)
        execute_calls = [
            mock.call('partprobe', self.dev, run_as_root=True, attempts=10),
            mock.call('lsblk', '-Po', 'name,label', self.dev,
                      check_exit_code=[0, 1],
                      use_standard_locale=True, run_as_root=True)
        ]
        mock_execute.assert_has_calls(execute_calls)

    def test_get_partition_present_uppercase(self, mock_execute):
        lsblk_output = 'NAME="fake12" LABEL="CONFIG-2"\n'
        part_result = '/dev/fake12'
        mock_execute.side_effect = [(None, ''), (lsblk_output, '')]
        result = partition_utils.get_labelled_partition(self.dev,
                                                        self.config_part_label,
                                                        self.node_uuid)
        self.assertEqual(part_result, result)
        execute_calls = [
            mock.call('partprobe', self.dev, run_as_root=True, attempts=10),
            mock.call('lsblk', '-Po', 'name,label', self.dev,
                      check_exit_code=[0, 1],
                      use_standard_locale=True, run_as_root=True)
        ]
        mock_execute.assert_has_calls(execute_calls)

    def test_get_partition_absent(self, mock_execute):
        mock_execute.side_effect = [(None, ''),
                                    (None, '')]
        result = partition_utils.get_labelled_partition(self.dev,
                                                        self.config_part_label,
                                                        self.node_uuid)
        self.assertIsNone(result)
        execute_calls = [
            mock.call('partprobe', self.dev, run_as_root=True, attempts=10),
            mock.call('lsblk', '-Po', 'name,label', self.dev,
                      check_exit_code=[0, 1],
                      use_standard_locale=True, run_as_root=True)
        ]
        mock_execute.assert_has_calls(execute_calls)

    def test_get_partition_DeployFail_exc(self, mock_execute):
        label = 'config-2'
        lsblk_output = ('NAME="fake12" LABEL="%s"\n'
                        'NAME="fake13" LABEL="%s"\n' %
                        (label, label))
        mock_execute.side_effect = [(None, ''), (lsblk_output, '')]
        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'fake .*fake12 .*fake13',
                               partition_utils.get_labelled_partition,
                               self.dev, self.config_part_label,
                               self.node_uuid)
        execute_calls = [
            mock.call('partprobe', self.dev, run_as_root=True, attempts=10),
            mock.call('lsblk', '-Po', 'name,label', self.dev,
                      check_exit_code=[0, 1],
                      use_standard_locale=True, run_as_root=True)
        ]
        mock_execute.assert_has_calls(execute_calls)

    @mock.patch.object(partition_utils.LOG, 'error', autospec=True)
    def test_get_partition_exc(self, mock_log, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Failed to retrieve partition labels',
                               partition_utils.get_labelled_partition,
                               self.dev, self.config_part_label,
                               self.node_uuid)
        execute_calls = [
            mock.call('partprobe', self.dev, run_as_root=True, attempts=10),
            mock.call('lsblk', '-Po', 'name,label', self.dev,
                      check_exit_code=[0, 1],
                      use_standard_locale=True, run_as_root=True)
        ]
        mock_execute.assert_has_calls(execute_calls)
        self.assertEqual(1, mock_log.call_count)


@mock.patch.object(utils, 'execute', autospec=True)
class IsDiskLargerThanMaxSizeTestCases(base.IronicAgentTest):

    dev = "/dev/fake"
    node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def _test_is_disk_larger_than_max_size(self, mock_execute, blk_out):
        mock_execute.return_value = ('%s\n' % blk_out, '')
        result = partition_utils._is_disk_larger_than_max_size(self.dev,
                                                               self.node_uuid)
        mock_execute.assert_called_once_with('blockdev', '--getsize64',
                                             '/dev/fake', run_as_root=True,
                                             use_standard_locale=True)
        return result

    def test_is_disk_larger_than_max_size_false(self, mock_execute):
        blkid_out = "53687091200"
        ret = self._test_is_disk_larger_than_max_size(mock_execute,
                                                      blk_out=blkid_out)
        self.assertFalse(ret)

    def test_is_disk_larger_than_max_size_true(self, mock_execute):
        blkid_out = "4398046511104"
        ret = self._test_is_disk_larger_than_max_size(mock_execute,
                                                      blk_out=blkid_out)
        self.assertTrue(ret)

    @mock.patch.object(partition_utils.LOG, 'error', autospec=True)
    def test_is_disk_larger_than_max_size_exc(self, mock_log, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Failed to get size of disk',
                               partition_utils._is_disk_larger_than_max_size,
                               self.dev, self.node_uuid)
        mock_execute.assert_called_once_with('blockdev', '--getsize64',
                                             '/dev/fake', run_as_root=True,
                                             use_standard_locale=True)
        self.assertEqual(1, mock_log.call_count)


@mock.patch.object(disk_partitioner.DiskPartitioner, 'commit', lambda _: None)
class WorkOnDiskTestCase(base.IronicAgentTest):

    def setUp(self):
        super(WorkOnDiskTestCase, self).setUp()
        self.image_path = '/tmp/xyz/image'
        self.root_mb = 128
        self.swap_mb = 64
        self.ephemeral_mb = 0
        self.ephemeral_format = None
        self.configdrive_mb = 0
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"
        self.dev = '/dev/fake'
        self.swap_part = '/dev/fake-part1'
        self.root_part = '/dev/fake-part2'

        self.mock_ibd_obj = mock.patch.object(
            disk_utils, 'is_block_device', autospec=True)
        self.mock_ibd = self.mock_ibd_obj.start()
        self.addCleanup(self.mock_ibd_obj.stop)
        self.mock_mp_obj = mock.patch.object(
            disk_utils, 'make_partitions', autospec=True)
        self.mock_mp = self.mock_mp_obj.start()
        self.addCleanup(self.mock_mp_obj.stop)
        self.mock_remlbl_obj = mock.patch.object(
            disk_utils, 'destroy_disk_metadata', autospec=True)
        self.mock_remlbl = self.mock_remlbl_obj.start()
        self.addCleanup(self.mock_remlbl_obj.stop)
        self.mock_mp.return_value = {'swap': self.swap_part,
                                     'root': self.root_part}

    def test_no_root_partition(self):
        self.mock_ibd.return_value = False
        self.assertRaises(exception.InstanceDeployFailure,
                          partition_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path,
                          self.node_uuid)
        self.mock_ibd.assert_called_once_with(self.root_part)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios",
                                             disk_label=None,
                                             cpu_arch="")

    def test_no_swap_partition(self):
        self.mock_ibd.side_effect = iter([True, False])
        calls = [mock.call(self.root_part),
                 mock.call(self.swap_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          partition_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path,
                          self.node_uuid)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios",
                                             disk_label=None,
                                             cpu_arch="")

    def test_no_ephemeral_partition(self):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'swap': swap_part,
                                     'root': root_part}
        self.mock_ibd.side_effect = iter([True, True, False])
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(ephemeral_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          partition_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, ephemeral_mb, ephemeral_format,
                          self.image_path, self.node_uuid)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios",
                                             disk_label=None,
                                             cpu_arch="")

    @mock.patch.object(utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive', autospec=True)
    def test_no_configdrive_partition(self, mock_configdrive, mock_unlink):
        mock_configdrive.return_value = (10, 'fake-path')
        swap_part = '/dev/fake-part1'
        configdrive_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        configdrive_url = 'http://1.2.3.4/cd'
        configdrive_mb = 10

        self.mock_mp.return_value = {'swap': swap_part,
                                     'configdrive': configdrive_part,
                                     'root': root_part}
        self.mock_ibd.side_effect = iter([True, True, False])
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(configdrive_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          partition_utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path,
                          self.node_uuid, preserve_ephemeral=False,
                          configdrive=configdrive_url,
                          boot_option="netboot")
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             configdrive_mb, self.node_uuid,
                                             commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios",
                                             disk_label=None,
                                             cpu_arch="")
        mock_unlink.assert_called_once_with('fake-path')

    @mock.patch.object(utils, 'mkfs', lambda fs, path, label=None: None)
    @mock.patch.object(disk_utils, 'block_uuid', lambda p: 'uuid')
    @mock.patch.object(disk_utils, 'populate_image', autospec=True)
    def test_without_image(self, mock_populate):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'swap': swap_part,
                                     'root': root_part}
        self.mock_ibd.return_value = True
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(ephemeral_part)]
        res = partition_utils.work_on_disk(self.dev, self.root_mb,
                                           self.swap_mb, ephemeral_mb,
                                           ephemeral_format,
                                           None, self.node_uuid)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios",
                                             disk_label=None,
                                             cpu_arch="")
        self.assertEqual(root_part, res['partitions']['root'])
        self.assertEqual('uuid', res['root uuid'])
        self.assertFalse(mock_populate.called)

    @mock.patch.object(utils, 'mkfs', lambda fs, path, label=None: None)
    @mock.patch.object(disk_utils, 'block_uuid', lambda p: 'uuid')
    @mock.patch.object(disk_utils, 'populate_image', lambda image_path,
                       root_path, conv_flags=None: None)
    def test_gpt_disk_label(self):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'swap': swap_part,
                                     'root': root_part}
        self.mock_ibd.return_value = True
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(ephemeral_part)]
        partition_utils.work_on_disk(self.dev, self.root_mb,
                                     self.swap_mb, ephemeral_mb,
                                     ephemeral_format,
                                     self.image_path, self.node_uuid,
                                     disk_label='gpt', conv_flags=None)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios",
                                             disk_label='gpt',
                                             cpu_arch="")

    @mock.patch.object(disk_utils, 'block_uuid', autospec=True)
    @mock.patch.object(disk_utils, 'populate_image', autospec=True)
    @mock.patch.object(utils, 'mkfs', autospec=True)
    def test_uefi_localboot(self, mock_mkfs, mock_populate_image,
                            mock_block_uuid):
        """Test that we create a fat filesystem with UEFI localboot."""
        root_part = '/dev/fake-part1'
        efi_part = '/dev/fake-part2'
        self.mock_mp.return_value = {'root': root_part,
                                     'efi system partition': efi_part}
        self.mock_ibd.return_value = True
        mock_ibd_calls = [mock.call(root_part),
                          mock.call(efi_part)]

        partition_utils.work_on_disk(self.dev, self.root_mb,
                                     self.swap_mb, self.ephemeral_mb,
                                     self.ephemeral_format,
                                     self.image_path, self.node_uuid,
                                     boot_option="local", boot_mode="uefi")

        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=True,
                                             boot_option="local",
                                             boot_mode="uefi",
                                             disk_label=None,
                                             cpu_arch="")
        self.assertEqual(self.mock_ibd.call_args_list, mock_ibd_calls)
        mock_mkfs.assert_called_once_with(fs='vfat', path=efi_part,
                                          label='efi-part')
        mock_populate_image.assert_called_once_with(self.image_path,
                                                    root_part, conv_flags=None)
        mock_block_uuid.assert_any_call(root_part)
        mock_block_uuid.assert_any_call(efi_part)

    @mock.patch.object(disk_utils, 'block_uuid', autospec=True)
    @mock.patch.object(disk_utils, 'populate_image', autospec=True)
    @mock.patch.object(utils, 'mkfs', autospec=True)
    def test_preserve_ephemeral(self, mock_mkfs, mock_populate_image,
                                mock_block_uuid):
        """Test that ephemeral partition doesn't get overwritten."""
        ephemeral_part = '/dev/fake-part1'
        root_part = '/dev/fake-part2'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'root': root_part}
        self.mock_ibd.return_value = True
        calls = [mock.call(root_part),
                 mock.call(ephemeral_part)]
        partition_utils.work_on_disk(self.dev, self.root_mb,
                                     self.swap_mb, ephemeral_mb,
                                     ephemeral_format,
                                     self.image_path, self.node_uuid,
                                     preserve_ephemeral=True)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=False,
                                             boot_option="netboot",
                                             boot_mode="bios",
                                             disk_label=None,
                                             cpu_arch="")
        self.assertFalse(mock_mkfs.called)

    @mock.patch.object(disk_utils, 'block_uuid', autospec=True)
    @mock.patch.object(disk_utils, 'populate_image', autospec=True)
    @mock.patch.object(utils, 'mkfs', autospec=True)
    def test_ppc64le_prep_part(self, mock_mkfs, mock_populate_image,
                               mock_block_uuid):
        """Test that PReP partition uuid is returned."""
        prep_part = '/dev/fake-part1'
        root_part = '/dev/fake-part2'

        self.mock_mp.return_value = {'PReP Boot partition': prep_part,
                                     'root': root_part}
        self.mock_ibd.return_value = True
        calls = [mock.call(root_part),
                 mock.call(prep_part)]
        partition_utils.work_on_disk(self.dev, self.root_mb,
                                     self.swap_mb, self.ephemeral_mb,
                                     self.ephemeral_format, self.image_path,
                                     self.node_uuid, boot_option="local",
                                     cpu_arch='ppc64le')
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb,
                                             self.node_uuid, commit=True,
                                             boot_option="local",
                                             boot_mode="bios",
                                             disk_label=None,
                                             cpu_arch="ppc64le")
        self.assertFalse(mock_mkfs.called)

    @mock.patch.object(disk_utils, 'block_uuid', autospec=True)
    @mock.patch.object(disk_utils, 'populate_image', autospec=True)
    @mock.patch.object(utils, 'mkfs', autospec=True)
    def test_convert_to_sparse(self, mock_mkfs, mock_populate_image,
                               mock_block_uuid):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'swap': swap_part,
                                     'root': root_part}
        self.mock_ibd.return_value = True
        partition_utils.work_on_disk(self.dev, self.root_mb,
                                     self.swap_mb, ephemeral_mb,
                                     ephemeral_format,
                                     self.image_path, self.node_uuid,
                                     disk_label='gpt', conv_flags='sparse')

        mock_populate_image.assert_called_once_with(self.image_path,
                                                    root_part,
                                                    conv_flags='sparse')


class CreateConfigDriveTestCases(base.IronicAgentTest):

    def setUp(self):
        super(CreateConfigDriveTestCases, self).setUp()
        self.dev = "/dev/fake"
        self.config_part_label = "config-2"
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(disk_utils, 'dd',
                       autospec=True)
    @mock.patch.object(disk_utils, 'fix_gpt_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def test_create_partition_exists(self, mock_get_configdrive,
                                     mock_get_labelled_partition,
                                     mock_list_partitions, mock_table_type,
                                     mock_fix_gpt_partition,
                                     mock_dd, mock_unlink, mock_execute):
        config_url = 'http://1.2.3.4/cd'
        configdrive_part = '/dev/fake-part1'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 10

        mock_get_labelled_partition.return_value = configdrive_part
        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        partition_utils.create_config_drive_partition(self.node_uuid, self.dev,
                                                      config_url)
        mock_fix_gpt_partition.assert_called_with(self.dev, self.node_uuid)
        mock_get_configdrive.assert_called_with(config_url, self.node_uuid)
        mock_get_labelled_partition.assert_called_with(self.dev,
                                                       self.config_part_label,
                                                       self.node_uuid)
        self.assertFalse(mock_list_partitions.called)
        self.assertFalse(mock_execute.called)
        self.assertFalse(mock_table_type.called)
        mock_dd.assert_called_with(configdrive_file, configdrive_part)
        mock_unlink.assert_called_with(configdrive_file)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(disk_utils, 'dd',
                       autospec=True)
    @mock.patch.object(disk_utils, 'fix_gpt_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def test_create_partition_gpt(self, mock_get_configdrive,
                                  mock_get_labelled_partition,
                                  mock_list_partitions, mock_table_type,
                                  mock_fix_gpt_partition,
                                  mock_dd, mock_unlink, mock_execute):
        config_url = 'http://1.2.3.4/cd'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 10

        initial_partitions = [{'end': 49152, 'number': 1, 'start': 1,
                               'flags': 'boot', 'filesystem': 'ext4',
                               'size': 49151},
                              {'end': 51099, 'number': 3, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 5, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046}]
        updated_partitions = [{'end': 49152, 'number': 1, 'start': 1,
                               'flags': 'boot', 'filesystem': 'ext4',
                               'size': 49151},
                              {'end': 51099, 'number': 3, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 4, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 5, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046}]

        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        mock_get_labelled_partition.return_value = None

        mock_table_type.return_value = 'gpt'
        mock_list_partitions.side_effect = [initial_partitions,
                                            updated_partitions]
        expected_part = '/dev/fake4'
        partition_utils.create_config_drive_partition(self.node_uuid, self.dev,
                                                      config_url)
        mock_execute.assert_has_calls([
            mock.call('sgdisk', '-n', '0:-64MB:0', self.dev,
                      run_as_root=True),
            mock.call('sync'),
            mock.call('udevadm', 'settle'),
            mock.call('partprobe', self.dev, attempts=10, run_as_root=True),
            mock.call('sgdisk', '-v', self.dev, run_as_root=True),

            mock.call('udevadm', 'settle'),
            mock.call('test', '-e', expected_part, attempts=15,
                      delay_on_retry=True)
        ])

        self.assertEqual(2, mock_list_partitions.call_count)
        mock_table_type.assert_called_with(self.dev)
        mock_fix_gpt_partition.assert_called_with(self.dev, self.node_uuid)
        mock_dd.assert_called_with(configdrive_file, expected_part)
        mock_unlink.assert_called_with(configdrive_file)

    @mock.patch.object(disk_utils, 'count_mbr_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(partition_utils.LOG, 'warning', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(disk_utils, 'dd',
                       autospec=True)
    @mock.patch.object(partition_utils, '_is_disk_larger_than_max_size',
                       autospec=True)
    @mock.patch.object(disk_utils, 'fix_gpt_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def _test_create_partition_mbr(self, mock_get_configdrive,
                                   mock_get_labelled_partition,
                                   mock_list_partitions,
                                   mock_table_type,
                                   mock_fix_gpt_partition,
                                   mock_disk_exceeds, mock_dd,
                                   mock_unlink, mock_log, mock_execute,
                                   mock_count, disk_size_exceeds_max=False,
                                   is_iscsi_device=False,
                                   is_nvme_device=False):
        config_url = 'http://1.2.3.4/cd'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 10
        mock_disk_exceeds.return_value = disk_size_exceeds_max

        initial_partitions = [{'end': 49152, 'number': 1, 'start': 1,
                               'flags': 'boot', 'filesystem': 'ext4',
                               'size': 49151},
                              {'end': 51099, 'number': 3, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 5, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046}]
        updated_partitions = [{'end': 49152, 'number': 1, 'start': 1,
                               'flags': 'boot', 'filesystem': 'ext4',
                               'size': 49151},
                              {'end': 51099, 'number': 3, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 4, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 5, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046}]
        mock_list_partitions.side_effect = [initial_partitions,
                                            updated_partitions]
        # 2 primary partitions, 0 logical partitions
        mock_count.return_value = (2, 0)
        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        mock_get_labelled_partition.return_value = None

        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"
        if is_iscsi_device:
            self.dev = ('/dev/iqn.2008-10.org.openstack:%s.fake' %
                        self.node_uuid)
            expected_part = '%s-part4' % self.dev
        elif is_nvme_device:
            self.dev = '/dev/nvmefake0'
            expected_part = '%sp4' % self.dev
        else:
            expected_part = '/dev/fake4'

        partition_utils.create_config_drive_partition(self.node_uuid, self.dev,
                                                      config_url)
        mock_get_configdrive.assert_called_with(config_url, self.node_uuid)
        if disk_size_exceeds_max:
            self.assertEqual(1, mock_log.call_count)
            parted_call = mock.call('parted', '-a', 'optimal', '-s',
                                    '--', self.dev, 'mkpart',
                                    'primary', 'fat32', 2097087,
                                    2097151, run_as_root=True)
        else:
            self.assertEqual(0, mock_log.call_count)
            parted_call = mock.call('parted', '-a', 'optimal', '-s',
                                    '--', self.dev, 'mkpart',
                                    'primary', 'fat32', '-64MiB',
                                    '-0', run_as_root=True)
        mock_execute.assert_has_calls([
            parted_call,
            mock.call('sync'),
            mock.call('udevadm', 'settle'),
            mock.call('partprobe', self.dev, attempts=10, run_as_root=True),
            mock.call('sgdisk', '-v', self.dev, run_as_root=True),
            mock.call('udevadm', 'settle'),
            mock.call('test', '-e', expected_part, attempts=15,
                      delay_on_retry=True)
        ])
        self.assertEqual(2, mock_list_partitions.call_count)
        mock_table_type.assert_called_with(self.dev)
        mock_fix_gpt_partition.assert_called_with(self.dev, self.node_uuid)
        mock_disk_exceeds.assert_called_with(self.dev, self.node_uuid)
        mock_dd.assert_called_with(configdrive_file, expected_part)
        mock_unlink.assert_called_with(configdrive_file)
        mock_count.assert_called_with(self.dev)

    def test__create_partition_mbr_disk_under_2TB(self):
        self._test_create_partition_mbr(disk_size_exceeds_max=False,
                                        is_iscsi_device=True,
                                        is_nvme_device=False)

    def test__create_partition_mbr_disk_under_2TB_nvme(self):
        self._test_create_partition_mbr(disk_size_exceeds_max=False,
                                        is_iscsi_device=False,
                                        is_nvme_device=True)

    def test__create_partition_mbr_disk_exceeds_2TB(self):
        self._test_create_partition_mbr(disk_size_exceeds_max=True,
                                        is_iscsi_device=False,
                                        is_nvme_device=False)

    def test__create_partition_mbr_disk_exceeds_2TB_nvme(self):
        self._test_create_partition_mbr(disk_size_exceeds_max=True,
                                        is_iscsi_device=False,
                                        is_nvme_device=True)

    @mock.patch.object(disk_utils, 'count_mbr_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(disk_utils, 'dd',
                       autospec=True)
    @mock.patch.object(partition_utils, '_is_disk_larger_than_max_size',
                       autospec=True)
    @mock.patch.object(disk_utils, 'fix_gpt_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def test_create_partition_part_create_fail(self, mock_get_configdrive,
                                               mock_get_labelled_partition,
                                               mock_list_partitions,
                                               mock_table_type,
                                               mock_fix_gpt_partition,
                                               mock_disk_exceeds, mock_dd,
                                               mock_unlink, mock_execute,
                                               mock_count):
        config_url = 'http://1.2.3.4/cd'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 10

        initial_partitions = [{'end': 49152, 'number': 1, 'start': 1,
                               'flags': 'boot', 'filesystem': 'ext4',
                               'size': 49151},
                              {'end': 51099, 'number': 3, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 5, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046}]
        updated_partitions = [{'end': 49152, 'number': 1, 'start': 1,
                               'flags': 'boot', 'filesystem': 'ext4',
                               'size': 49151},
                              {'end': 51099, 'number': 3, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 5, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046}]
        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        mock_get_labelled_partition.return_value = None
        mock_disk_exceeds.return_value = False
        mock_list_partitions.side_effect = [initial_partitions,
                                            initial_partitions,
                                            updated_partitions]
        # 2 primary partitions, 0 logical partitions
        mock_count.return_value = (2, 0)

        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Disk partitioning failed on device',
                               partition_utils.create_config_drive_partition,
                               self.node_uuid, self.dev, config_url)

        mock_get_configdrive.assert_called_with(config_url, self.node_uuid)
        mock_execute.assert_has_calls([
            mock.call('parted', '-a', 'optimal', '-s', '--',
                      self.dev, 'mkpart', 'primary',
                      'fat32', '-64MiB', '-0',
                      run_as_root=True),
            mock.call('sync'),
            mock.call('udevadm', 'settle'),
            mock.call('partprobe', self.dev, attempts=10, run_as_root=True),
            mock.call('sgdisk', '-v', self.dev, run_as_root=True),
        ])

        self.assertEqual(2, mock_list_partitions.call_count)
        mock_fix_gpt_partition.assert_called_with(self.dev, self.node_uuid)
        mock_table_type.assert_called_with(self.dev)
        mock_disk_exceeds.assert_called_with(self.dev, self.node_uuid)
        self.assertFalse(mock_dd.called)
        mock_unlink.assert_called_with(configdrive_file)
        mock_count.assert_called_once_with(self.dev)

    @mock.patch.object(disk_utils, 'count_mbr_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(disk_utils, 'dd',
                       autospec=True)
    @mock.patch.object(partition_utils, '_is_disk_larger_than_max_size',
                       autospec=True)
    @mock.patch.object(disk_utils, 'fix_gpt_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def test_create_partition_part_create_exc(self, mock_get_configdrive,
                                              mock_get_labelled_partition,
                                              mock_list_partitions,
                                              mock_table_type,
                                              mock_fix_gpt_partition,
                                              mock_disk_exceeds, mock_dd,
                                              mock_unlink, mock_execute,
                                              mock_count):
        config_url = 'http://1.2.3.4/cd'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 10

        initial_partitions = [{'end': 49152, 'number': 1, 'start': 1,
                               'flags': 'boot', 'filesystem': 'ext4',
                               'size': 49151},
                              {'end': 51099, 'number': 3, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046},
                              {'end': 51099, 'number': 5, 'start': 49153,
                               'flags': '', 'filesystem': '', 'size': 2046}]
        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        mock_get_labelled_partition.return_value = None
        mock_disk_exceeds.return_value = False
        mock_list_partitions.side_effect = [initial_partitions,
                                            initial_partitions]
        # 2 primary partitions, 0 logical partitions
        mock_count.return_value = (2, 0)

        mock_execute.side_effect = processutils.ProcessExecutionError

        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Failed to create config drive on disk',
                               partition_utils.create_config_drive_partition,
                               self.node_uuid, self.dev, config_url)

        mock_get_configdrive.assert_called_with(config_url, self.node_uuid)
        mock_execute.assert_called_with('parted', '-a', 'optimal', '-s', '--',
                                        self.dev, 'mkpart', 'primary',
                                        'fat32', '-64MiB', '-0',
                                        run_as_root=True)
        self.assertEqual(1, mock_list_partitions.call_count)
        mock_fix_gpt_partition.assert_called_with(self.dev, self.node_uuid)
        mock_table_type.assert_called_with(self.dev)
        mock_disk_exceeds.assert_called_with(self.dev, self.node_uuid)
        self.assertFalse(mock_dd.called)
        mock_unlink.assert_called_with(configdrive_file)
        mock_count.assert_called_once_with(self.dev)

    @mock.patch.object(disk_utils, 'count_mbr_partitions', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(disk_utils, 'dd',
                       autospec=True)
    @mock.patch.object(disk_utils, 'fix_gpt_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def test_create_partition_num_parts_exceed(self, mock_get_configdrive,
                                               mock_get_labelled_partition,
                                               mock_list_partitions,
                                               mock_table_type,
                                               mock_fix_gpt_partition,
                                               mock_dd, mock_unlink,
                                               mock_count):
        config_url = 'http://1.2.3.4/cd'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 10

        partitions = [{'end': 49152, 'number': 1, 'start': 1,
                       'flags': 'boot', 'filesystem': 'ext4',
                       'size': 49151},
                      {'end': 51099, 'number': 2, 'start': 49153,
                       'flags': '', 'filesystem': '', 'size': 2046},
                      {'end': 51099, 'number': 3, 'start': 49153,
                       'flags': '', 'filesystem': '', 'size': 2046},
                      {'end': 51099, 'number': 4, 'start': 49153,
                       'flags': '', 'filesystem': '', 'size': 2046}]
        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        mock_get_labelled_partition.return_value = None
        mock_list_partitions.side_effect = [partitions, partitions]
        # 4 primary partitions, 0 logical partitions
        mock_count.return_value = (4, 0)

        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Config drive cannot be created for node',
                               partition_utils.create_config_drive_partition,
                               self.node_uuid, self.dev, config_url)

        mock_get_configdrive.assert_called_with(config_url, self.node_uuid)
        self.assertEqual(1, mock_list_partitions.call_count)
        mock_fix_gpt_partition.assert_called_with(self.dev, self.node_uuid)
        mock_table_type.assert_called_with(self.dev)
        self.assertFalse(mock_dd.called)
        mock_unlink.assert_called_with(configdrive_file)
        mock_count.assert_called_once_with(self.dev)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def test_create_partition_conf_drive_sz_exceed(self, mock_get_configdrive,
                                                   mock_get_labelled_partition,
                                                   mock_unlink, mock_execute):
        config_url = 'http://1.2.3.4/cd'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 65

        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        mock_get_labelled_partition.return_value = None

        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Config drive size exceeds maximum limit',
                               partition_utils.create_config_drive_partition,
                               self.node_uuid, self.dev, config_url)

        mock_get_configdrive.assert_called_with(config_url, self.node_uuid)
        mock_unlink.assert_called_with(configdrive_file)

    @mock.patch.object(disk_utils, 'count_mbr_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(disk_utils, 'fix_gpt_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_partition_table_type',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_labelled_partition',
                       autospec=True)
    @mock.patch.object(partition_utils, 'get_configdrive',
                       autospec=True)
    def test_create_partition_conf_drive_error_counting(
            self, mock_get_configdrive, mock_get_labelled_partition,
            mock_table_type, mock_fix_gpt_partition,
            mock_unlink, mock_execute, mock_count):
        config_url = 'http://1.2.3.4/cd'
        configdrive_file = '/tmp/xyz'
        configdrive_mb = 10

        mock_get_configdrive.return_value = (configdrive_mb, configdrive_file)
        mock_get_labelled_partition.return_value = None
        mock_count.side_effect = ValueError('Booooom')

        self.assertRaisesRegex(exception.InstanceDeployFailure,
                               'Failed to check the number of primary ',
                               partition_utils.create_config_drive_partition,
                               self.node_uuid, self.dev, config_url)

        mock_get_configdrive.assert_called_with(config_url, self.node_uuid)
        mock_unlink.assert_called_with(configdrive_file)
        mock_fix_gpt_partition.assert_called_with(self.dev, self.node_uuid)
        mock_table_type.assert_called_with(self.dev)
        mock_count.assert_called_once_with(self.dev)


# NOTE(TheJulia): trigger_device_rescan is systemwide thus pointless
# to execute in the file test case. Also, CI unit test jobs lack sgdisk.
@mock.patch.object(disk_utils, 'trigger_device_rescan', lambda *_: None)
@mock.patch.object(utils, 'wait_for_disk_to_become_available', lambda *_: None)
@mock.patch.object(disk_utils, 'is_block_device', lambda d: True)
@mock.patch.object(disk_utils, 'block_uuid', lambda p: 'uuid')
@mock.patch.object(disk_utils, 'dd', lambda *_: None)
@mock.patch.object(disk_utils, 'convert_image', lambda *_: None)
@mock.patch.object(utils, 'mkfs', lambda fs, path, label=None: None)
# NOTE(dtantsur): destroy_disk_metadata resets file size, disabling it
@mock.patch.object(disk_utils, 'destroy_disk_metadata', lambda *_: None)
class RealFilePartitioningTestCase(base.IronicAgentTest):
    """This test applies some real-world partitioning scenario to a file.

    This test covers the whole partitioning, mocking everything not possible
    on a file. That helps us assure, that we do all partitioning math properly
    and also conducts integration testing of DiskPartitioner.
    """

    # Allow calls to utils.execute() and related functions
    block_execute = False

    def setUp(self):
        super(RealFilePartitioningTestCase, self).setUp()
        try:
            utils.execute('parted', '--version')
        except OSError as exc:
            self.skipTest('parted utility was not found: %s' % exc)
        self.file = tempfile.NamedTemporaryFile(delete=False)
        # NOTE(ifarkas): the file needs to be closed, so fuser won't report
        #                any usage
        self.file.close()
        # NOTE(dtantsur): 20 MiB file with zeros
        utils.execute('dd', 'if=/dev/zero', 'of=%s' % self.file.name,
                      'bs=1', 'count=0', 'seek=20MiB')

    @staticmethod
    def _run_without_root(func, *args, **kwargs):
        """Make sure root is not required when using utils.execute."""
        real_execute = utils.execute

        def fake_execute(*cmd, **kwargs):
            kwargs['run_as_root'] = False
            return real_execute(*cmd, **kwargs)

        with mock.patch.object(utils, 'execute', fake_execute):
            return func(*args, **kwargs)

    def test_different_sizes(self):
        # NOTE(dtantsur): Keep this list in order with expected partitioning
        fields = ['ephemeral_mb', 'swap_mb', 'root_mb']
        variants = ((0, 0, 12), (4, 2, 8), (0, 4, 10), (5, 0, 10))
        for variant in variants:
            kwargs = dict(zip(fields, variant))
            self._run_without_root(partition_utils.work_on_disk,
                                   self.file.name, ephemeral_format='ext4',
                                   node_uuid='', image_path='path', **kwargs)
            part_table = self._run_without_root(
                disk_utils.list_partitions, self.file.name)
            for part, expected_size in zip(part_table, filter(None, variant)):
                self.assertEqual(expected_size, part['size'],
                                 "comparison failed for %s" % list(variant))

    def test_whole_disk(self):
        # 6 MiB ephemeral + 3 MiB swap + 9 MiB root + 1 MiB for MBR
        # + 1 MiB MAGIC == 20 MiB whole disk
        # TODO(dtantsur): figure out why we need 'magic' 1 more MiB
        # and why the is different on Ubuntu and Fedora (see below)
        self._run_without_root(partition_utils.work_on_disk, self.file.name,
                               root_mb=9, ephemeral_mb=6, swap_mb=3,
                               ephemeral_format='ext4', node_uuid='',
                               image_path='path')
        part_table = self._run_without_root(
            disk_utils.list_partitions, self.file.name)
        sizes = [part['size'] for part in part_table]
        # NOTE(dtantsur): parted in Ubuntu 12.04 will occupy the last MiB,
        # parted in Fedora 20 won't - thus two possible variants for last part
        self.assertEqual([6, 3], sizes[:2],
                         "unexpected partitioning %s" % part_table)
        self.assertIn(sizes[2], (9, 10))

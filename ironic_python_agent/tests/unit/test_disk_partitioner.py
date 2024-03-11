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

from unittest import mock

from ironic_lib import exception
from ironic_lib.tests import base
from ironic_lib import utils

from ironic_python_agent import disk_partitioner


CONF = disk_partitioner.CONF


class DiskPartitionerTestCase(base.IronicLibTestCase):

    def test_add_partition(self):
        dp = disk_partitioner.DiskPartitioner('/dev/fake')
        dp.add_partition(1024)
        dp.add_partition(512, fs_type='linux-swap')
        dp.add_partition(2048, boot_flag='boot')
        dp.add_partition(2048, boot_flag='bios_grub')
        expected = [(1, {'boot_flag': None,
                         'extra_flags': None,
                         'fs_type': '',
                         'type': 'primary',
                         'size': 1024}),
                    (2, {'boot_flag': None,
                         'extra_flags': None,
                         'fs_type': 'linux-swap',
                         'type': 'primary',
                         'size': 512}),
                    (3, {'boot_flag': 'boot',
                         'extra_flags': None,
                         'fs_type': '',
                         'type': 'primary',
                         'size': 2048}),
                    (4, {'boot_flag': 'bios_grub',
                         'extra_flags': None,
                         'fs_type': '',
                         'type': 'primary',
                         'size': 2048})]
        partitions = [(n, p) for n, p in dp.get_partitions()]
        self.assertEqual(4, len(partitions))
        self.assertEqual(expected, partitions)

    @mock.patch.object(disk_partitioner.DiskPartitioner, '_exec',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_commit(self, mock_utils_exc, mock_disk_partitioner_exec):
        dp = disk_partitioner.DiskPartitioner('/dev/fake')
        fake_parts = [(1, {'boot_flag': None,
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1}),
                      (2, {'boot_flag': 'boot',
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1}),
                      (3, {'boot_flag': 'bios_grub',
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1}),
                      (4, {'boot_flag': 'boot',
                           'extra_flags': ['prep', 'fake-flag'],
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1})]
        with mock.patch.object(dp, 'get_partitions', autospec=True) as mock_gp:
            mock_gp.return_value = fake_parts
            mock_utils_exc.return_value = ('', '')
            dp.commit()

        mock_disk_partitioner_exec.assert_called_once_with(
            mock.ANY, 'mklabel', 'msdos',
            'mkpart', 'fake-type', 'fake-fs-type', '1', '2',
            'mkpart', 'fake-type', 'fake-fs-type', '2', '3',
            'set', '2', 'boot', 'on',
            'mkpart', 'fake-type', 'fake-fs-type', '3', '4',
            'set', '3', 'bios_grub', 'on',
            'mkpart', 'fake-type', 'fake-fs-type', '4', '5',
            'set', '4', 'boot', 'on', 'set', '4', 'prep', 'on',
            'set', '4', 'fake-flag', 'on')
        mock_utils_exc.assert_called_once_with(
            'fuser', '/dev/fake', check_exit_code=[0, 1])

    @mock.patch.object(disk_partitioner.DiskPartitioner, '_exec',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_commit_with_device_is_busy_once(self, mock_utils_exc,
                                             mock_disk_partitioner_exec):
        CONF.set_override('check_device_interval', 0, group='disk_partitioner')
        dp = disk_partitioner.DiskPartitioner('/dev/fake')
        fake_parts = [(1, {'boot_flag': None,
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1}),
                      (2, {'boot_flag': 'boot',
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1})]
        # Test as if the 'psmisc' version of 'fuser' which has stderr output
        fuser_outputs = iter([(" 10000 10001", '/dev/fake:\n'), ('', '')])

        with mock.patch.object(dp, 'get_partitions', autospec=True) as mock_gp:
            mock_gp.return_value = fake_parts
            mock_utils_exc.side_effect = fuser_outputs
            dp.commit()

        mock_disk_partitioner_exec.assert_called_once_with(
            mock.ANY, 'mklabel', 'msdos',
            'mkpart', 'fake-type', 'fake-fs-type', '1', '2',
            'mkpart', 'fake-type', 'fake-fs-type', '2', '3',
            'set', '2', 'boot', 'on')
        mock_utils_exc.assert_called_with(
            'fuser', '/dev/fake', check_exit_code=[0, 1])
        self.assertEqual(2, mock_utils_exc.call_count)

    @mock.patch.object(disk_partitioner.DiskPartitioner, '_exec',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_commit_with_device_is_always_busy(self, mock_utils_exc,
                                               mock_disk_partitioner_exec):
        CONF.set_override('check_device_interval', 0, group='disk_partitioner')
        dp = disk_partitioner.DiskPartitioner('/dev/fake')
        fake_parts = [(1, {'boot_flag': None,
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1}),
                      (2, {'boot_flag': 'boot',
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1})]

        with mock.patch.object(dp, 'get_partitions', autospec=True) as mock_gp:
            mock_gp.return_value = fake_parts
            # Test as if the 'busybox' version of 'fuser' which does not have
            # stderr output
            mock_utils_exc.return_value = ("10000 10001", '')
            self.assertRaises(exception.InstanceDeployFailure, dp.commit)

        mock_disk_partitioner_exec.assert_called_once_with(
            mock.ANY, 'mklabel', 'msdos',
            'mkpart', 'fake-type', 'fake-fs-type', '1', '2',
            'mkpart', 'fake-type', 'fake-fs-type', '2', '3',
            'set', '2', 'boot', 'on')
        mock_utils_exc.assert_called_with(
            'fuser', '/dev/fake', check_exit_code=[0, 1])
        self.assertEqual(20, mock_utils_exc.call_count)

    @mock.patch.object(disk_partitioner.DiskPartitioner, '_exec',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_commit_with_device_disconnected(self, mock_utils_exc,
                                             mock_disk_partitioner_exec):
        CONF.set_override('check_device_interval', 0, group='disk_partitioner')
        dp = disk_partitioner.DiskPartitioner('/dev/fake')
        fake_parts = [(1, {'boot_flag': None,
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1}),
                      (2, {'boot_flag': 'boot',
                           'extra_flags': None,
                           'fs_type': 'fake-fs-type',
                           'type': 'fake-type',
                           'size': 1})]

        with mock.patch.object(dp, 'get_partitions', autospec=True) as mock_gp:
            mock_gp.return_value = fake_parts
            mock_utils_exc.return_value = ('', "Specified filename /dev/fake"
                                               " does not exist.")
            self.assertRaises(exception.InstanceDeployFailure, dp.commit)

        mock_disk_partitioner_exec.assert_called_once_with(
            mock.ANY, 'mklabel', 'msdos',
            'mkpart', 'fake-type', 'fake-fs-type', '1', '2',
            'mkpart', 'fake-type', 'fake-fs-type', '2', '3',
            'set', '2', 'boot', 'on')
        mock_utils_exc.assert_called_with(
            'fuser', '/dev/fake', check_exit_code=[0, 1])
        self.assertEqual(20, mock_utils_exc.call_count)

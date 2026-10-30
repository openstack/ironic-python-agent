# Copyright 2026 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os
import tempfile

from oslo_concurrency import processutils
from oslotest import base

from ironic_python_agent import disk_utils
from ironic_python_agent import utils


class LoopbackDiskTestCase(base.BaseTestCase):
    """Exercise disk metadata operations on a real loopback device."""

    def setUp(self):
        super().setUp()
        try:
            processutils.execute('sudo', '-n', 'true')
        except processutils.ProcessExecutionError:
            self.skipTest('passwordless sudo is required for loopback tests')
        self.image = tempfile.NamedTemporaryFile(delete=False)
        self.image.close()
        self.addCleanup(os.unlink, self.image.name)
        os.truncate(self.image.name, 128 * 1024 * 1024)
        self.loopdev, _ = processutils.execute(
            'sudo', '-n', 'losetup', '--find', '--show', '--partscan',
            self.image.name)
        self.loopdev = self.loopdev.strip()
        self.addCleanup(self._detach_loopdev)

    def _detach_loopdev(self):
        processutils.execute('sudo', '-n', 'losetup', '--detach',
                             self.loopdev, check_exit_code=[0, 1])

    def _execute_as_root(self, *cmd, **kwargs):
        if kwargs.pop('use_standard_locale', False):
            env = kwargs.pop('env_variables', os.environ.copy())
            env['LC_ALL'] = 'C'
            kwargs['env_variables'] = env
        kwargs.pop('log_stdout', None)
        return processutils.execute('sudo', '-n', *cmd, **kwargs)

    def test_destroy_gpt_metadata(self):
        """Destroy a real GPT and verify the device can be reused."""
        original_execute = utils.execute
        utils.execute = self._execute_as_root
        self.addCleanup(setattr, utils, 'execute', original_execute)

        utils.execute('sfdisk', '--quiet', self.loopdev,
                      process_input='label: gpt\n,64M,U\n')
        disk_utils.trigger_device_rescan(self.loopdev)
        self.assertTrue(disk_utils.list_partitions(self.loopdev))

        disk_utils.destroy_disk_metadata(
            self.loopdev, '00000000-0000-0000-0000-000000000000')

        disk_utils.trigger_device_rescan(self.loopdev)

        # A disk without a label makes parted exit with an error, so check for
        # remaining signatures with wipefs instead of list_partitions().
        output, _ = utils.execute(
            'wipefs', '--noheadings', '--output', 'TYPE', self.loopdev)
        self.assertEqual('', output.strip())

        # Verify the primary and backup GPT areas that destroy_disk_metadata
        # zeroes; wipefs alone only verifies that signatures are no longer
        # recognized.
        sector_size, _ = utils.execute(
            'blockdev', '--getss', self.loopdev, use_standard_locale=True)
        sector_size = int(sector_size.strip())
        self.assertIn(sector_size, (512, 4096))
        gpt_sectors = 33 if sector_size == 512 else 5
        zeroed_bytes = gpt_sectors * sector_size
        disk_size = os.path.getsize(self.image.name)
        for region, offset in (('head', 0),
                               ('tail', disk_size - zeroed_bytes)):
            with self.subTest(region=region):
                output, _ = utils.execute(
                    'od', '-An', '-v', '-t', 'x1', '-j', str(offset),
                    '-N', str(zeroed_bytes), self.loopdev,
                    use_standard_locale=True)
                self.assertEqual({'00'}, set(output.split()))

        # Verify that the device can be partitioned again after cleanup.
        utils.execute('parted', '-s', '--', self.loopdev,
                      'mklabel', 'gpt', 'mkpart', 'primary', 'fat32',
                      '1MiB', '64MiB')
        disk_utils.trigger_device_rescan(self.loopdev)
        self.assertTrue(disk_utils.list_partitions(self.loopdev))

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

from oslo_concurrency import processutils

from ironic_python_agent import errors
from ironic_python_agent import raid_utils
from ironic_python_agent.tests.unit import base
from ironic_python_agent.tests.unit.samples import hardware_samples as hws
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
            '--metadata=1', '--level', '1', '--raid-devices', 3,
            '/dev/sda1', '/dev/sdb1', '/dev/sdc1')

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
                      '--metadata=1', '--level', '1', '--raid-devices', 3,
                      '/dev/sda1', '/dev/sdb1', '/dev/sdc1'),
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

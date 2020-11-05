# Copyright 2015 Rackspace, Inc.
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

from unittest import mock

from ironic_python_agent import errors
from ironic_python_agent.extensions import clean
from ironic_python_agent.tests.unit import base


@mock.patch('ironic_python_agent.hardware.cache_node', autospec=True)
class TestCleanExtension(base.IronicAgentTest):
    def setUp(self):
        """
        Sets the extension.

        Args:
            self: (todo): write your description
        """
        super(TestCleanExtension, self).setUp()
        self.agent_extension = clean.CleanExtension()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244'}
        self.ports = []
        self.step = {
            'GenericHardwareManager':
                [{'step': 'erase_devices',
                  'priority': 10,
                  'interface': 'deploy'}]
        }
        self.version = {'generic': '1', 'specific': '1'}

    @mock.patch('ironic_python_agent.hardware.get_current_versions',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_all_managers',
                autospec=True)
    def test_get_clean_steps(self, mock_dispatch, mock_version,
                             mock_cache_node):
        """
        Perform information about a node.

        Args:
            self: (todo): write your description
            mock_dispatch: (str): write your description
            mock_version: (str): write your description
            mock_cache_node: (todo): write your description
        """
        mock_version.return_value = self.version

        manager_steps = {
            'SpecificHardwareManager': [
                {
                    'step': 'erase_devices',
                    'priority': 10,
                    'interface': 'deploy',
                    'reboot_requested': False
                },
                {
                    'step': 'upgrade_bios',
                    'priority': 20,
                    'interface': 'deploy',
                    'reboot_requested': True
                },
                {
                    'step': 'upgrade_firmware',
                    'priority': 60,
                    'interface': 'deploy',
                    'reboot_requested': False
                },
            ],
            'FirmwareHardwareManager': [
                {
                    'step': 'upgrade_firmware',
                    'priority': 10,
                    'interface': 'deploy',
                    'reboot_requested': False
                },
                {
                    'step': 'erase_devices',
                    'priority': 40,
                    'interface': 'deploy',
                    'reboot_requested': False
                },
            ],
            'DiskHardwareManager': [
                {
                    'step': 'erase_devices',
                    'priority': 50,
                    'interface': 'deploy',
                    'reboot_requested': False
                },
            ]
        }

        expected_steps = {
            'SpecificHardwareManager': [
                # Only manager upgrading BIOS
                {
                    'step': 'upgrade_bios',
                    'priority': 20,
                    'interface': 'deploy',
                    'reboot_requested': True
                }
            ],
            'FirmwareHardwareManager': [
                # Higher support than specific, even though lower priority
                {
                    'step': 'upgrade_firmware',
                    'priority': 10,
                    'interface': 'deploy',
                    'reboot_requested': False
                },
            ],
            'DiskHardwareManager': [
                # Higher support than specific, higher priority than firmware
                {
                    'step': 'erase_devices',
                    'priority': 50,
                    'interface': 'deploy',
                    'reboot_requested': False
                },
            ]

        }

        hardware_support = {
            'SpecificHardwareManager': 3,
            'FirmwareHardwareManager': 4,
            'DiskHardwareManager': 4
        }

        mock_dispatch.side_effect = [manager_steps, hardware_support]
        expected_return = {
            'hardware_manager_version': self.version,
            'clean_steps': expected_steps
        }

        async_results = self.agent_extension.get_clean_steps(node=self.node,
                                                             ports=self.ports)

        # Ordering of the clean steps doesn't matter; they're sorted by
        # 'priority' in Ironic
        self.assertEqual(expected_return,
                         async_results.join().command_result)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_clean_step(self, mock_version, mock_dispatch,
                                mock_cache_node):
        """
        Execute a single test step.

        Args:
            self: (todo): write your description
            mock_version: (todo): write your description
            mock_dispatch: (todo): write your description
            mock_cache_node: (todo): write your description
        """
        result = 'cleaned'
        mock_dispatch.return_value = result

        expected_result = {
            'clean_step': self.step['GenericHardwareManager'][0],
            'clean_result': result
        }
        async_result = self.agent_extension.execute_clean_step(
            step=self.step['GenericHardwareManager'][0],
            node=self.node, ports=self.ports,
            clean_version=self.version)
        async_result.join()

        mock_version.assert_called_once_with(self.version)
        mock_dispatch.assert_called_once_with(
            self.step['GenericHardwareManager'][0]['step'],
            self.node, self.ports)
        self.assertEqual(expected_result, async_result.command_result)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_clean_step_tuple_result(self, mock_version,
                                             mock_dispatch, mock_cache_node):
        """
        Execute a test result of the test_version_tuple.

        Args:
            self: (todo): write your description
            mock_version: (todo): write your description
            mock_dispatch: (todo): write your description
            mock_cache_node: (todo): write your description
        """
        result = ('stdout', 'stderr')
        mock_dispatch.return_value = result

        expected_result = {
            'clean_step': self.step['GenericHardwareManager'][0],
            'clean_result': ['stdout', 'stderr']
        }
        async_result = self.agent_extension.execute_clean_step(
            step=self.step['GenericHardwareManager'][0],
            node=self.node, ports=self.ports,
            clean_version=self.version)
        async_result.join()

        mock_version.assert_called_once_with(self.version)
        mock_dispatch.assert_called_once_with(
            self.step['GenericHardwareManager'][0]['step'],
            self.node, self.ports)
        self.assertEqual(expected_result, async_result.command_result)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_clean_step_no_step(self, mock_version, mock_cache_node):
        """
        Execute a single step of a step.

        Args:
            self: (todo): write your description
            mock_version: (todo): write your description
            mock_cache_node: (todo): write your description
        """
        async_result = self.agent_extension.execute_clean_step(
            step={}, node=self.node, ports=self.ports,
            clean_version=self.version)
        async_result.join()

        self.assertEqual('FAILED', async_result.command_status)
        mock_version.assert_called_once_with(self.version)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_clean_step_fail(self, mock_version, mock_dispatch,
                                     mock_cache_node):
        """
        Execute the test_version of the step.

        Args:
            self: (todo): write your description
            mock_version: (todo): write your description
            mock_dispatch: (todo): write your description
            mock_cache_node: (todo): write your description
        """
        mock_dispatch.side_effect = RuntimeError

        async_result = self.agent_extension.execute_clean_step(
            step=self.step['GenericHardwareManager'][0], node=self.node,
            ports=self.ports, clean_version=self.version)
        async_result.join()

        self.assertEqual('FAILED', async_result.command_status)

        mock_version.assert_called_once_with(self.version)
        mock_dispatch.assert_called_once_with(
            self.step['GenericHardwareManager'][0]['step'],
            self.node, self.ports)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_clean_step_version_mismatch(self, mock_version,
                                                 mock_dispatch,
                                                 mock_cache_node):
        """
        Execute the cached version of the test_execute.

        Args:
            self: (todo): write your description
            mock_version: (todo): write your description
            mock_dispatch: (str): write your description
            mock_cache_node: (todo): write your description
        """
        mock_version.side_effect = errors.VersionMismatch(
            {'GenericHardwareManager': 1}, {'GenericHardwareManager': 2})

        async_result = self.agent_extension.execute_clean_step(
            step=self.step['GenericHardwareManager'][0], node=self.node,
            ports=self.ports, clean_version=self.version)
        async_result.join()
        self.assertEqual('CLEAN_VERSION_MISMATCH', async_result.command_status)

        mock_version.assert_called_once_with(self.version)

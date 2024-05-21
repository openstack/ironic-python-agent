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
from ironic_python_agent.extensions import service
from ironic_python_agent.tests.unit import base


@mock.patch('ironic_python_agent.hardware.cache_node', autospec=True)
class TestServiceExtension(base.IronicAgentTest):
    def setUp(self):
        super(TestServiceExtension, self).setUp()
        self.agent_extension = service.ServiceExtension()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244'}
        self.ports = []
        self.step = {
            'GenericHardwareManager':
                [{'step': 'erase_devices',
                  'priority': 10,
                  'interface': 'deploy'}]
        }
        self.version = {'generic': '1', 'specific': '1'}

    @mock.patch('ironic_python_agent.hardware.get_managers_detail',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.get_current_versions',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.dispatch_to_all_managers',
                autospec=True)
    def test_get_service_steps(self, mock_dispatch, mock_version,
                               mock_managers, mock_cache_node):
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

        # NOTE(JayF): The real dict also has manager: hwm-object
        #             but we don't use it in the code under test
        hwms = [
            {'name': 'SpecificHardwareManager', 'support': 3},
            {'name': 'FirmwareHardwareManager', 'support': 4},
            {'name': 'DiskHardwareManager', 'support': 4},
        ]

        mock_dispatch.side_effect = [manager_steps]
        mock_managers.return_value = hwms

        expected_return = {
            'hardware_manager_version': self.version,
            'service_steps': expected_steps
        }

        async_results = self.agent_extension.get_service_steps(
            node=self.node,
            ports=self.ports)

        # Ordering of the service steps doesn't matter; they're sorted by
        # 'priority' in Ironic, and executed upon by user submission order
        # in ironic.
        self.assertEqual(expected_return,
                         async_results.join().command_result)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_service_step(self, mock_version, mock_dispatch,
                                  mock_cache_node):
        result = 'cleaned'
        mock_dispatch.return_value = result

        expected_result = {
            'service_step': self.step['GenericHardwareManager'][0],
            'service_result': result
        }
        async_result = self.agent_extension.execute_service_step(
            step=self.step['GenericHardwareManager'][0],
            node=self.node, ports=self.ports,
            service_version=self.version)
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
    def test_execute_service_step_tuple_result(self, mock_version,
                                               mock_dispatch, mock_cache_node):
        result = ('stdout', 'stderr')
        mock_dispatch.return_value = result

        expected_result = {
            'service_step': self.step['GenericHardwareManager'][0],
            'service_result': ['stdout', 'stderr']
        }
        async_result = self.agent_extension.execute_service_step(
            step=self.step['GenericHardwareManager'][0],
            node=self.node, ports=self.ports,
            service_version=self.version)
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
    def test_execute_service_step_with_args(self, mock_version, mock_dispatch,
                                            mock_cache_node):
        result = 'cleaned'
        mock_dispatch.return_value = result

        step = self.step['GenericHardwareManager'][0]
        step['args'] = {'foo': 'bar'}
        expected_result = {
            'service_step': step,
            'service_result': result
        }
        async_result = self.agent_extension.execute_service_step(
            step=self.step['GenericHardwareManager'][0],
            node=self.node, ports=self.ports,
            service_version=self.version)
        async_result.join()

        mock_version.assert_called_once_with(self.version)
        mock_dispatch.assert_called_once_with(
            self.step['GenericHardwareManager'][0]['step'],
            self.node, self.ports, foo='bar')
        self.assertEqual(expected_result, async_result.command_result)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_service_step_no_step(self, mock_version, mock_cache_node):
        async_result = self.agent_extension.execute_service_step(
            step={}, node=self.node, ports=self.ports,
            service_version=self.version)
        async_result.join()

        self.assertEqual('FAILED', async_result.command_status)
        mock_version.assert_called_once_with(self.version)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_service_step_fail(self, mock_version, mock_dispatch,
                                       mock_cache_node):
        err = errors.BlockDeviceError("I'm a teapot")
        mock_dispatch.side_effect = err

        async_result = self.agent_extension.execute_service_step(
            step=self.step['GenericHardwareManager'][0], node=self.node,
            ports=self.ports, service_version=self.version)
        async_result.join()

        self.assertEqual('FAILED', async_result.command_status)
        self.assertEqual(err, async_result.command_error)

        mock_version.assert_called_once_with(self.version)
        mock_dispatch.assert_called_once_with(
            self.step['GenericHardwareManager'][0]['step'],
            self.node, self.ports)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_service_step_exception(self, mock_version, mock_dispatch,
                                            mock_cache_node):
        mock_dispatch.side_effect = RuntimeError('boom')

        async_result = self.agent_extension.execute_service_step(
            step=self.step['GenericHardwareManager'][0], node=self.node,
            ports=self.ports, service_version=self.version)
        async_result.join()

        self.assertEqual('FAILED', async_result.command_status)
        self.assertIn('RuntimeError: boom', str(async_result.command_error))

        mock_version.assert_called_once_with(self.version)
        mock_dispatch.assert_called_once_with(
            self.step['GenericHardwareManager'][0]['step'],
            self.node, self.ports)
        mock_cache_node.assert_called_once_with(self.node)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch('ironic_python_agent.hardware.check_versions',
                autospec=True)
    def test_execute_service_step_version_mismatch(self, mock_version,
                                                   mock_dispatch,
                                                   mock_cache_node):
        mock_version.side_effect = errors.VersionMismatch(
            {'GenericHardwareManager': 1}, {'GenericHardwareManager': 2})

        async_result = self.agent_extension.execute_service_step(
            step=self.step['GenericHardwareManager'][0], node=self.node,
            ports=self.ports, service_version=self.version)
        async_result.join()
        # NOTE(TheJulia): This remains CLEAN_VERSION_MISMATCH for backwards
        # compatibility with base.py and API consumers.
        self.assertEqual('CLEAN_VERSION_MISMATCH',
                         async_result.command_status)

        mock_version.assert_called_once_with(self.version)

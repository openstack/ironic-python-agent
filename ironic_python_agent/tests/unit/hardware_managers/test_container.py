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

from oslo_config import cfg

from ironic_python_agent import hardware
from ironic_python_agent.hardware_managers import container
from ironic_python_agent.tests.unit import base

CONF = cfg.CONF


class TestContainerHardwareManager(base.IronicAgentTest):
    def setUp(self):
        super(TestContainerHardwareManager, self).setUp()
        self.hardware = container.ContainerHardwareManager()
        self.config(
            runner='podman',
            pull_options=['--tls-verify=false'],
            run_options=['--rm', '--network=host', '--tls-verify=false'],
            container_steps_file='/tmp/steps.yaml',
            allow_arbitrary_containers=False,
            allowed_containers=[],
            group='container'
        )

    def test_evaluate_hardware_support_docker_available(self):
        with mock.patch('ironic_python_agent.utils.execute',
                        autospec=True) as mock_execute:
            mock_execute.side_effect = [
                mock.Mock(side_effect=Exception('Podman not found')),
                ('/usr/bin/docker', '')
            ]

            support_level = self.hardware.evaluate_hardware_support()
            mock_execute.assert_called_with('which', 'docker')
            self.assertEqual(support_level, hardware.HardwareSupport.MAINLINE)

    def test_evaluate_hardware_support_podman_available(self):
        with mock.patch('ironic_python_agent.utils.execute',
                        autospec=True) as mock_execute:
            mock_execute.return_value = ('/usr/bin/podman', '')
            support_level = self.hardware.evaluate_hardware_support()
            mock_execute.assert_called_with('which', 'podman')
            self.assertEqual(support_level, hardware.HardwareSupport.MAINLINE)

    def test_evaluate_hardware_support_no_runners(self):
        with mock.patch('ironic_python_agent.utils.execute',
                        autospec=True) as mock_execute:
            mock_execute.side_effect = Exception('Runner not found')
            support_level = self.hardware.evaluate_hardware_support()
            expected_calls = [
                mock.call('which', 'podman'),
                mock.call('which', 'docker')
            ]
            mock_execute.assert_has_calls(expected_calls, any_order=True)
            self.assertEqual(support_level, hardware.HardwareSupport.NONE)

    def test_container_runners_list(self):
        expected_runners = ["podman", "docker"]
        runners = getattr(self.hardware, 'CONTAINERS_RUNNERS',
                          ["podman", "docker"])
        self.assertEqual(runners, expected_runners)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_container_clean_step_with_custom_options(self, mock_execute):
        node = mock.MagicMock()
        ports = mock.MagicMock()
        container_url = 'test-image:latest'
        pull_options = ['--tls-verify=false', '-q']
        run_options = ['--rm', '--network=host', '--tls-verify=false', '-q']

        self.hardware.container_clean_step(
            node,
            ports,
            container_url,
            pull_options=pull_options,
            run_options=run_options
        )
        mock_execute.assert_any_call(
            CONF.container.runner,
            "pull",
            *pull_options,
            container_url
        )
        mock_execute.assert_any_call(
            CONF.container.runner,
            "run",
            *run_options,
            container_url
        )

    def test_create_container_step(self):
        step = self.hardware._create_container_step()

        self.assertEqual(step['step'], 'container_clean_step')
        self.assertEqual(step['priority'], 0)
        self.assertEqual(step['interface'], 'deploy')
        self.assertFalse(step['reboot_requested'])
        self.assertTrue(step['abortable'])

        self.assertIn('container_url', step['argsinfo'])
        self.assertIn('pull_options', step['argsinfo'])
        self.assertIn('run_options', step['argsinfo'])

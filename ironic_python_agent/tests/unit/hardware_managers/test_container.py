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

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent.hardware_managers import container
from ironic_python_agent.tests.unit import base

CONF = cfg.CONF

ALLOWED_IMAGE = 'docker://registry.example.com/allowed:latest'
OTHER_IMAGE = 'docker://registry.example.com/other:latest'


class ContainerTestCase(base.IronicAgentTest):
    def setUp(self):
        super(ContainerTestCase, self).setUp()
        self.hardware = container.ContainerHardwareManager()
        self.node = mock.MagicMock()
        self.ports = mock.MagicMock()
        self.config(
            runner='podman',
            pull_options=['--tls-verify=false'],
            run_options=['--rm', '--network=host'],
            container_steps_file='/nonexistent/steps.yaml',
            allow_arbitrary_containers=False,
            allowed_containers=[],
            group='container'
        )

    @staticmethod
    def _run_argv(mock_execute):
        """Return the argv of the ``run`` call, ignoring the pull."""
        for call in mock_execute.call_args_list:
            if len(call.args) > 1 and call.args[1] == 'run':
                return list(call.args)
        return None


class TestContainerHardwareManager(ContainerTestCase):
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


class TestContainerPolicy(ContainerTestCase):
    """The check every execution path passes through."""

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_untrusted_image_not_in_allowlist_is_refused(self, mock_execute):
        self.assertRaises(
            errors.ContainerNotPermittedError,
            self.hardware.container_clean_step,
            self.node, self.ports, OTHER_IMAGE)
        # Nothing was pulled or run.
        mock_execute.assert_not_called()

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_untrusted_image_in_allowlist_runs(self, mock_execute):
        self.config(allowed_containers=[ALLOWED_IMAGE], group='container')
        mock_execute.return_value = ('', '')
        self.hardware.container_clean_step(self.node, self.ports,
                                           ALLOWED_IMAGE)
        self.assertEqual(
            ['podman', 'run', '--rm', '--network=host', ALLOWED_IMAGE],
            self._run_argv(mock_execute))

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_allow_arbitrary_containers_bypasses_allowlist(self,
                                                           mock_execute):
        self.config(allow_arbitrary_containers=True, group='container')
        mock_execute.return_value = ('', '')
        self.hardware.container_clean_step(self.node, self.ports, OTHER_IMAGE)
        self.assertIn(OTHER_IMAGE, self._run_argv(mock_execute))

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_trusted_step_bypasses_allowlist(self, mock_execute):
        # Ramdisk-baked steps are authored by the operator at build time.
        mock_execute.return_value = ('', '')
        self.hardware._container_step(self.node, self.ports, OTHER_IMAGE,
                                      trusted=True)
        self.assertIn(OTHER_IMAGE, self._run_argv(mock_execute))

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_caller_options_ignored_when_locked_down(self, mock_execute):
        # An allowlisted image plus attacker-chosen flags is still a full
        # host compromise, so the flags are discarded along with the choice.
        self.config(allowed_containers=[ALLOWED_IMAGE], group='container')
        mock_execute.return_value = ('', '')
        self.hardware.container_clean_step(
            self.node, self.ports, ALLOWED_IMAGE,
            run_options=['--privileged', '-v', '/:/host'])
        argv = self._run_argv(mock_execute)
        self.assertNotIn('--privileged', argv)
        self.assertNotIn('/:/host', argv)
        self.assertEqual(
            ['podman', 'run', '--rm', '--network=host', ALLOWED_IMAGE], argv)

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_caller_options_honored_when_arbitrary_allowed(self,
                                                           mock_execute):
        self.config(allow_arbitrary_containers=True, group='container')
        mock_execute.return_value = ('', '')
        self.hardware.container_clean_step(
            self.node, self.ports, OTHER_IMAGE,
            run_options=['--rm', '--network=host', '-q'])
        self.assertEqual(
            ['podman', 'run', '--rm', '--network=host', '-q', OTHER_IMAGE],
            self._run_argv(mock_execute))

    def test_trusted_is_not_reachable_as_a_step_argument(self):
        # A runbook must not be able to assert its own trust.
        self.assertRaises(
            TypeError,
            self.hardware.container_clean_step,
            self.node, self.ports, OTHER_IMAGE, trusted=True)

    def test_yaml_step_is_created_trusted(self):
        method = self.hardware._create_cleanup_method(
            container_url=OTHER_IMAGE)
        self.assertTrue(method.keywords['trusted'])
        self.assertEqual(OTHER_IMAGE, method.keywords['container_url'])

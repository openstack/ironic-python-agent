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

import copy
import os
import tempfile
from unittest import mock

from oslo_config import cfg
import yaml

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
        # Reserved names are cached on the class once the managers are
        # loaded, so a test that loads them would otherwise decide what
        # every later test sees.
        container.ContainerHardwareManager._RESERVED_NAMES = None
        self.addCleanup(setattr, container.ContainerHardwareManager,
                        '_RESERVED_NAMES', None)
        self.config(
            runner='podman',
            pull_options=['--tls-verify=false'],
            run_options=['--rm', '--network=host'],
            container_steps_file='/nonexistent/steps.yaml',
            allow_arbitrary_containers=False,
            allowed_containers=[],
            group='container'
        )

    def _write_steps(self, steps):
        """Write a steps file and point the config at it."""
        fd, path = tempfile.mkstemp(suffix='.yaml')
        with os.fdopen(fd, 'w') as f:
            yaml.safe_dump(steps, f)
        self.addCleanup(os.unlink, path)
        self.config(container_steps_file=path, group='container')
        return path

    @staticmethod
    def _run_argv(mock_execute):
        """Return the argv of the ``run`` call, ignoring the pull."""
        for call in mock_execute.call_args_list:
            if len(call.args) > 1 and call.args[1] == 'run':
                return list(call.args)
        return None


class TestOptionNormalization(ContainerTestCase):
    def test_nothing_to_normalize(self):
        self.assertEqual([], container._as_options(None))
        self.assertEqual([], container._as_options([]))

    def test_already_split(self):
        self.assertEqual(['--rm', '--network=host'],
                         container._as_options(['--rm', '--network=host']))

    def test_space_separated_single_element(self):
        # What a conductor sending a StrOpt through a ListOpt produces.
        self.assertEqual(
            ['--rm', '--network=host', '--tls-verify=false'],
            container._as_options(['--rm --network=host --tls-verify=false']))

    def test_bare_string(self):
        # A runbook can pass one directly as a step argument.
        self.assertEqual(['--rm', '--network=host'],
                         container._as_options('--rm --network=host'))


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


class TestStepNameResolution(ContainerTestCase):
    def _step(self, name, **kw):
        step = {'name': name, 'image': OTHER_IMAGE, 'interface': 'deploy',
                'reboot_requested': False, 'abortable': True, 'priority': 10}
        step.update(kw)
        return step

    def test_resolves_yaml_step(self):
        self._write_steps({'steps': [self._step('my_container_step')]})
        method = self.hardware.my_container_step
        self.assertEqual(OTHER_IMAGE, method.keywords['container_url'])

    def test_refuses_to_shadow_generic_hardware_manager(self):
        # A step named after a real one would otherwise run a container in
        # place of wiping the disk, and be reported as successful.
        self._write_steps({'steps': [self._step('erase_devices_metadata')]})
        self.assertRaises(AttributeError,
                          getattr, self.hardware, 'erase_devices_metadata')

    def test_refuses_to_shadow_any_loaded_manager(self):
        # An operator's own manager is as shadowable as the generic one, and
        # its methods are not knowable from GenericHardwareManager alone.
        class VendorHardwareManager(hardware.HardwareManager):
            def evaluate_hardware_support(self):
                return hardware.HardwareSupport.SERVICE_PROVIDER

            def flash_vendor_firmware(self, node, ports):
                pass

        self._write_steps({'steps': [self._step('flash_vendor_firmware')]})
        hardware._global_managers = [
            {'name': 'ContainerHardwareManager', 'manager': self.hardware,
             'support': hardware.HardwareSupport.MAINLINE},
            {'name': 'VendorHardwareManager',
             'manager': VendorHardwareManager(),
             'support': hardware.HardwareSupport.SERVICE_PROVIDER},
        ]
        self.assertRaises(AttributeError, getattr, self.hardware,
                          'flash_vendor_firmware')

    def test_reserved_names_are_not_cached_before_managers_load(self):
        # Caching the fallback would freeze an incomplete set for the life of
        # the process, leaving third party manager methods shadowable.
        hardware._global_managers = None
        self.hardware._reserved_names()
        self.assertIsNone(container.ContainerHardwareManager._RESERVED_NAMES)

    def test_shadowing_step_is_not_advertised(self):
        self._write_steps({'steps': [self._step('erase_devices_metadata')]})
        self.assertRaises(errors.HardwareManagerConfigurationError,
                          self.hardware.get_clean_steps, self.node, self.ports)

    def test_dispatch_reaches_the_real_generic_step(self):
        self._write_steps({'steps': [self._step('erase_devices_metadata')]})
        generic = hardware.GenericHardwareManager()
        hardware._global_managers = [
            {'name': 'ContainerHardwareManager', 'manager': self.hardware,
             'support': hardware.HardwareSupport.MAINLINE},
            {'name': 'GenericHardwareManager', 'manager': generic,
             'support': hardware.HardwareSupport.GENERIC},
        ]
        with mock.patch.object(generic, 'erase_devices_metadata',
                               autospec=True) as mock_erase:
            hardware.dispatch_to_managers('erase_devices_metadata',
                                          self.node, self.ports)
        mock_erase.assert_called_once_with(self.node, self.ports)

    def test_private_names_are_never_synthesized(self):
        self._write_steps({'steps': [self._step('_sneaky')]})
        self.assertRaises(AttributeError, getattr, self.hardware, '_sneaky')

    def test_deepcopy_does_not_recurse(self):
        # __getattr__ used to send copy/pickle protocol lookups back into
        # itself, and into a YAML read, on every probe.
        self.assertIsInstance(copy.deepcopy(self.hardware),
                              container.ContainerHardwareManager)

    def test_unknown_attribute_message_is_interpolated(self):
        exc = self.assertRaises(AttributeError,
                                getattr, self.hardware, 'no_such_step')
        self.assertIn('ContainerHardwareManager', str(exc))
        self.assertIn('no_such_step', str(exc))
        self.assertNotIn('%s', str(exc))

    def test_uninitialized_instance_does_not_recurse(self):
        obj = container.ContainerHardwareManager.__new__(
            container.ContainerHardwareManager)
        self.assertRaises(AttributeError, getattr, obj, 'anything')


class TestGetSteps(ContainerTestCase):
    def _priority_of(self, steps, name):
        return [s for s in steps if s['step'] == name][0]['priority']

    def test_builtin_step_advertised(self):
        steps = self.hardware.get_clean_steps(self.node, self.ports)
        self.assertIn('container_clean_step', [s['step'] for s in steps])

    def test_yaml_steps_advertised(self):
        self._write_steps({'steps': [{
            'name': 'my_step', 'image': OTHER_IMAGE, 'interface': 'deploy',
            'reboot_requested': False, 'abortable': True, 'priority': 10}]})
        steps = self.hardware.get_clean_steps(self.node, self.ports)
        my_step = [s for s in steps if s['step'] == 'my_step'][0]
        self.assertEqual(10, my_step['priority'])
        self.assertEqual('deploy', my_step['interface'])

    def test_same_steps_offered_in_every_phase(self):
        names = [s['step'] for s in
                 self.hardware.get_clean_steps(self.node, self.ports)]
        for getter in (self.hardware.get_deploy_steps,
                       self.hardware.get_service_steps):
            self.assertEqual(names,
                             [s['step'] for s in getter(self.node,
                                                        self.ports)])

    def test_yaml_priority_applies_to_cleaning_only(self):
        # A deploy step with priority > 0 runs automatically, so a cleaning
        # container must not be advertised with its priority intact.
        self._write_steps({'steps': [{
            'name': 'my_step', 'image': OTHER_IMAGE, 'interface': 'deploy',
            'reboot_requested': False, 'abortable': True, 'priority': 20}]})
        self.assertEqual(20, self._priority_of(
            self.hardware.get_clean_steps(self.node, self.ports), 'my_step'))
        self.assertEqual(0, self._priority_of(
            self.hardware.get_deploy_steps(self.node, self.ports), 'my_step'))
        self.assertEqual(0, self._priority_of(
            self.hardware.get_service_steps(self.node, self.ports), 'my_step'))

    def test_missing_priority_reported_in_every_phase(self):
        self._write_steps({'steps': [{
            'name': 'my_step', 'image': OTHER_IMAGE, 'interface': 'deploy',
            'reboot_requested': False, 'abortable': True}]})
        for getter in (self.hardware.get_clean_steps,
                       self.hardware.get_deploy_steps,
                       self.hardware.get_service_steps):
            self.assertRaises(errors.HardwareManagerConfigurationError,
                              getter, self.node, self.ports)


class TestConductorConfigRoundTrip(ContainerTestCase):
    """Regression test for the conductor sending StrOpt into a ListOpt."""

    @mock.patch('ironic_python_agent.utils.execute', autospec=True)
    def test_space_separated_conductor_options_produce_valid_argv(
            self, mock_execute):
        # Exactly the shape the lookup response carries.
        for opt, val in {
            'allow_arbitrary_containers': True,
            'runner': 'podman',
            'pull_options': '--tls-verify=false',
            'run_options': '--rm --network=host --tls-verify=false',
        }.items():
            CONF.set_override(opt, val, group='container')

        mock_execute.return_value = ('', '')
        self.hardware.container_clean_step(self.node, self.ports, OTHER_IMAGE)
        self.assertEqual(
            ['podman', 'run', '--rm', '--network=host', '--tls-verify=false',
             OTHER_IMAGE],
            self._run_argv(mock_execute))

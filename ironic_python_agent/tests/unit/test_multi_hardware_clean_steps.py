# Copyright 2013 Rackspace, Inc.
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

import mock
from stevedore import extension

from ironic_python_agent.extensions import clean
from ironic_python_agent import hardware
from ironic_python_agent.tests.unit import base


def _build_clean_step(name, priority, reboot=False, abort=False):
    return {'step': name, 'priority': priority,
            'reboot_requested': reboot, 'abortable': abort}


class AFakeMainlineHardwareManager(hardware.HardwareManager):
    def evaluate_hardware_support(self):
        return hardware.HardwareSupport.MAINLINE

    def get_clean_steps(self, node, ports):
        return [_build_clean_step('duped_ml', 20)]


class AFakeGenericHardwareManager(hardware.HardwareManager):
    def evaluate_hardware_support(self):
        return hardware.HardwareSupport.GENERIC

    def get_clean_steps(self, node, ports):
        return [_build_clean_step('duped_ml', 20),
                _build_clean_step('duped_gn', 30),
                _build_clean_step('ZHigherPrio', 1)]


class ZFakeGenericHardwareManager(hardware.HardwareManager):
    def evaluate_hardware_support(self):
        return hardware.HardwareSupport.GENERIC

    def get_clean_steps(self, node, ports):
        return [_build_clean_step('duped_ml', 20),
                _build_clean_step('duped_gn', 30),
                _build_clean_step('ZHigherPrio', 100)]


class TestMultipleHardwareManagerCleanSteps(base.IronicAgentTest):
    def setUp(self):
        super(TestMultipleHardwareManagerCleanSteps, self).setUp()

        self.agent_extension = clean.CleanExtension()

        fake_ep = mock.Mock()
        fake_ep.module_name = 'fake'
        fake_ep.attrs = ['fake attrs']
        self.ag_hwm = extension.Extension(
            'fake_ageneric', fake_ep, None, AFakeGenericHardwareManager())
        self.zg_hwm = extension.Extension(
            'fake_zgeneric', fake_ep, None, ZFakeGenericHardwareManager())
        self.ml_hwm = extension.Extension(
            'fake_amainline', fake_ep, None, AFakeMainlineHardwareManager())
        self.fake_ext_mgr = extension.ExtensionManager.make_test_instance(
            [self.ag_hwm, self.zg_hwm, self.ml_hwm])

        self.extension_mgr_patcher = mock.patch('stevedore.ExtensionManager',
                                                autospec=True)
        self.addCleanup(self.extension_mgr_patcher.stop)
        self.mocked_extension_mgr = self.extension_mgr_patcher.start()
        self.mocked_extension_mgr.return_value = self.fake_ext_mgr
        hardware._global_managers = None

    def test_clean_step_ordering(self):
        as_results = self.agent_extension.get_clean_steps(node={}, ports=[])
        results = as_results.join().command_result
        expected_steps = {
            'clean_steps': {
                'AFakeGenericHardwareManager': [
                    {'step': 'duped_gn',
                     'reboot_requested': False,
                     'abortable': False,
                     'priority': 30}],
                'ZFakeGenericHardwareManager': [
                    {'step': 'ZHigherPrio',
                     'reboot_requested': False,
                     'abortable': False,
                     'priority': 100}],
                'AFakeMainlineHardwareManager': [
                    {'step': 'duped_ml',
                     'reboot_requested': False,
                     'abortable': False,
                     'priority': 20}]},
            'hardware_manager_version': {
                'AFakeGenericHardwareManager': '1.0',
                'AFakeMainlineHardwareManager': '1.0',
                'ZFakeGenericHardwareManager': '1.0'}}

        for manager, steps in results['clean_steps'].items():
            steps.sort(key=lambda x: (x['priority'], x['step']))

        for manager, steps in expected_steps['clean_steps'].items():
            steps.sort(key=lambda x: (x['priority'], x['step']))

        self.assertEqual(expected_steps, results)

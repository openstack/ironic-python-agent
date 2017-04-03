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

import collections

import mock
from stevedore import extension

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent.tests.unit import base


def counted(fn):
    def wrapper(self, *args, **kwargs):
        try:
            counts = self._call_counts
        except AttributeError:
            counts = self._call_counts = collections.Counter()
        counts[fn.__name__] += 1
        return fn(self, *args, **kwargs)
    return wrapper


class FakeGenericHardwareManager(hardware.HardwareManager):
    @counted
    def generic_only(self):
        return 'generic_only'

    @counted
    def generic_none(self):
        return None

    @counted
    def specific_none(self):
        return 'generic'

    @counted
    def return_list(self):
        return ['generic']

    @counted
    def specific_only(self):
        raise Exception("Test fail: This method should not be called")

    @counted
    def mainline_fail(self):
        return 'generic_mainline_fail'

    @counted
    def both_succeed(self):
        return 'generic_both'

    @counted
    def unexpected_fail(self):
        raise Exception("Test fail: This method should not be called")

    @counted
    def evaluate_hardware_support(self):
        return hardware.HardwareSupport.GENERIC


class FakeMainlineHardwareManager(hardware.HardwareManager):
    @counted
    def specific_only(self):
        return 'specific_only'

    @counted
    def generic_none(self):
        return 'specific'

    @counted
    def specific_none(self):
        return None

    @counted
    def return_list(self):
        return ['specific']

    @counted
    def mainline_fail(self):
        raise errors.IncompatibleHardwareMethodError

    @counted
    def both_succeed(self):
        return 'specific_both'

    @counted
    def unexpected_fail(self):
        raise RuntimeError('A problem was encountered')

    @counted
    def evaluate_hardware_support(self):
        return hardware.HardwareSupport.MAINLINE


class TestMultipleHardwareManagerLoading(base.IronicAgentTest):
    def setUp(self):
        super(TestMultipleHardwareManagerLoading, self).setUp()
        fake_ep = mock.Mock()
        fake_ep.module_name = 'fake'
        fake_ep.attrs = ['fake attrs']
        self.generic_hwm = extension.Extension(
            'fake_generic', fake_ep, None, FakeGenericHardwareManager())
        self.mainline_hwm = extension.Extension(
            'fake_mainline', fake_ep, None, FakeMainlineHardwareManager())
        self.fake_ext_mgr = extension.ExtensionManager.make_test_instance(
            [self.generic_hwm, self.mainline_hwm])

        self.extension_mgr_patcher = mock.patch('stevedore.ExtensionManager',
                                                autospec=True)
        self.addCleanup(self.extension_mgr_patcher.stop)
        self.mocked_extension_mgr = self.extension_mgr_patcher.start()
        self.mocked_extension_mgr.return_value = self.fake_ext_mgr
        hardware._global_managers = None

    def test_mainline_method_only(self):
        hardware.dispatch_to_managers('specific_only')

        self.assertEqual(
            1, self.mainline_hwm.obj._call_counts['specific_only'])

    def test_generic_method_only(self):
        hardware.dispatch_to_managers('generic_only')

        self.assertEqual(1, self.generic_hwm.obj._call_counts['generic_only'])

    def test_both_succeed(self):
        # In the case where both managers will work; only the most specific
        # manager should have it's function called.
        hardware.dispatch_to_managers('both_succeed')

        self.assertEqual(1, self.mainline_hwm.obj._call_counts['both_succeed'])
        self.assertEqual(0, self.generic_hwm.obj._call_counts['both_succeed'])

    def test_mainline_fails(self):
        # Ensure that if the mainline manager is unable to run the method
        # that we properly fall back to generic.
        hardware.dispatch_to_managers('mainline_fail')

        self.assertEqual(
            1, self.mainline_hwm.obj._call_counts['mainline_fail'])
        self.assertEqual(1, self.generic_hwm.obj._call_counts['mainline_fail'])

    def test_manager_method_not_found(self):
        self.assertRaises(errors.HardwareManagerMethodNotFound,
                          hardware.dispatch_to_managers,
                          'fake_method')

    def test_method_fails(self):
        self.assertRaises(RuntimeError,
                          hardware.dispatch_to_managers,
                          'unexpected_fail')

    def test_dispatch_to_all_managers_mainline_only(self):
        results = hardware.dispatch_to_all_managers('generic_none')

        self.assertEqual(1, self.generic_hwm.obj._call_counts['generic_none'])
        self.assertEqual({'FakeGenericHardwareManager': None,
                          'FakeMainlineHardwareManager': 'specific'},
                         results)

    def test_dispatch_to_all_managers_generic_method_only(self):
        results = hardware.dispatch_to_all_managers('specific_none')

        self.assertEqual(1, self.generic_hwm.obj._call_counts['specific_none'])
        self.assertEqual({'FakeGenericHardwareManager': 'generic',
                          'FakeMainlineHardwareManager': None}, results)

    def test_dispatch_to_all_managers_both_succeed(self):
        # In the case where both managers will work; only the most specific
        # manager should have it's function called.
        results = hardware.dispatch_to_all_managers('both_succeed')

        self.assertEqual({'FakeGenericHardwareManager': 'generic_both',
                          'FakeMainlineHardwareManager': 'specific_both'},
                         results)
        self.assertEqual(1, self.mainline_hwm.obj._call_counts['both_succeed'])
        self.assertEqual(1, self.generic_hwm.obj._call_counts['both_succeed'])

    def test_dispatch_to_all_managers_mainline_fails(self):
        # Ensure that if the mainline manager is unable to run the method
        # that we properly fall back to generic.
        hardware.dispatch_to_all_managers('mainline_fail')

        self.assertEqual(
            1, self.mainline_hwm.obj._call_counts['mainline_fail'])
        self.assertEqual(1, self.generic_hwm.obj._call_counts['mainline_fail'])

    def test_dispatch_to_all_managers_manager_method_not_found(self):
        self.assertRaises(errors.HardwareManagerMethodNotFound,
                          hardware.dispatch_to_all_managers,
                          'unknown_method')

    def test_dispatch_to_all_managers_method_fails(self):
        self.assertRaises(RuntimeError,
                          hardware.dispatch_to_all_managers,
                          'unexpected_fail')


class TestNoHardwareManagerLoading(base.IronicAgentTest):
    def setUp(self):
        super(TestNoHardwareManagerLoading, self).setUp()
        self.empty_ext_mgr = extension.ExtensionManager.make_test_instance([])

    @mock.patch('stevedore.ExtensionManager', autospec=True)
    def test_no_managers_found(self, mocked_extension_mgr_constructor):
        mocked_extension_mgr_constructor.return_value = self.empty_ext_mgr
        hardware._global_managers = None

        self.assertRaises(errors.HardwareManagerNotFound,
                          hardware.dispatch_to_managers,
                          'some_method')

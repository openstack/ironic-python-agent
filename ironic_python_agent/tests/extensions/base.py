# Copyright 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
from oslotest import base as test_base
from stevedore import extension

from ironic_python_agent import errors
from ironic_python_agent.extensions import base


class FakeExtension(base.BaseAgentExtension):
    def __init__(self):
        super(FakeExtension, self).__init__('FAKE')


class FakeAgent(base.ExecuteCommandMixin):
    def __init__(self):
        super(FakeAgent, self).__init__()

    def get_extension_manager(self):
        return extension.ExtensionManager.make_test_instance(
            [extension.Extension('fake', None, FakeExtension,
                                 FakeExtension())])


class TestExecuteCommandMixin(test_base.BaseTestCase):
    def setUp(self):
        super(TestExecuteCommandMixin, self).setUp()
        self.agent = FakeAgent()

    def test_execute_command(self):
        do_something_impl = mock.Mock()
        fake_extension = FakeExtension()
        fake_extension.command_map['do_something'] = do_something_impl
        self.agent.ext_mgr = extension.ExtensionManager.make_test_instance(
            [extension.Extension('fake', None, FakeExtension, fake_extension)])

        self.agent.execute_command('fake.do_something', foo='bar')
        do_something_impl.assert_called_once_with('do_something', foo='bar')

    def test_execute_invalid_command(self):
        self.assertRaises(errors.InvalidCommandError,
                          self.agent.execute_command,
                          'do_something',
                          foo='bar')

    def test_execute_unknown_extension(self):
        self.assertRaises(errors.RequestedObjectNotFoundError,
                          self.agent.execute_command,
                          'do.something',
                          foo='bar')

    def test_execute_command_success(self):
        expected_result = base.SyncCommandResult('fake', None, True, None)
        fake_ext = self.agent.ext_mgr['fake'].obj
        fake_ext.execute = mock.Mock()
        fake_ext.execute.return_value = expected_result
        result = self.agent.execute_command('fake.sleep',
                                            sleep_info={"time": 1})
        self.assertEqual(expected_result, result)

    def test_execute_command_invalid_content(self):
        fake_ext = self.agent.ext_mgr['fake'].obj
        fake_ext.execute = mock.Mock()
        fake_ext.execute.side_effect = errors.InvalidContentError('baz')
        self.assertRaises(errors.InvalidContentError,
                          self.agent.execute_command,
                          'fake.sleep', sleep_info={"time": 1})

    def test_execute_command_other_exception(self):
        msg = 'foo bar baz'
        fake_ext = self.agent.ext_mgr['fake'].obj
        fake_ext.execute = mock.Mock()
        fake_ext.execute.side_effect = Exception(msg)
        result = self.agent.execute_command(
            'fake.sleep', sleep_info={"time": 1}
        )
        self.assertEqual(result.command_status,
                         base.AgentCommandStatus.FAILED)
        self.assertEqual(result.command_error, msg)

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


def _fake_validator(ext, **kwargs):
    if not kwargs.get('is_valid', True):
        raise errors.InvalidCommandParamsError('error')


class ExecutionError(errors.RESTError):
    def __init__(self):
        super(ExecutionError, self).__init__('failed')


class FakeExtension(base.BaseAgentExtension):
    def __init__(self):
        super(FakeExtension, self).__init__()
        self.command_map['fake_async_command'] = self.fake_async_command
        self.command_map['fake_sync_command'] = self.fake_sync_command

    @base.async_command(_fake_validator)
    def fake_async_command(self, command_name, is_valid=False, param=None):
        if param == 'v2':
            raise ExecutionError()
        return param

    @base.sync_command(_fake_validator)
    def fake_sync_command(self, command_name, is_valid=False, param=None):
        if param == 'v2':
            raise ExecutionError()
        return param


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


class TestExtensionDecorators(test_base.BaseTestCase):
    def setUp(self):
        super(TestExtensionDecorators, self).setUp()
        self.extension = FakeExtension()

    def test_async_command_success(self):
        result = self.extension.execute('fake_async_command', param='v1')
        self.assertIsInstance(result, base.AsyncCommandResult)
        result.join()
        self.assertEqual('fake_async_command', result.command_name)
        self.assertEqual({'param': 'v1'}, result.command_params)
        self.assertEqual(base.AgentCommandStatus.SUCCEEDED,
                         result.command_status)
        self.assertEqual(None, result.command_error)
        self.assertEqual('v1', result.command_result)

    def test_async_command_validation_failure(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.extension.execute,
                          'fake_async_command',
                          is_valid=False)

    def test_async_command_execution_failure(self):
        result = self.extension.execute('fake_async_command', param='v2')
        self.assertIsInstance(result, base.AsyncCommandResult)
        result.join()
        self.assertEqual('fake_async_command', result.command_name)
        self.assertEqual({'param': 'v2'}, result.command_params)
        self.assertEqual(base.AgentCommandStatus.FAILED,
                         result.command_status)
        self.assertIsInstance(result.command_error, ExecutionError)
        self.assertEqual(None, result.command_result)

    def test_sync_command_success(self):
        result = self.extension.execute('fake_sync_command', param='v1')
        self.assertIsInstance(result, base.SyncCommandResult)
        self.assertEqual('fake_sync_command', result.command_name)
        self.assertEqual({'param': 'v1'}, result.command_params)
        self.assertEqual(base.AgentCommandStatus.SUCCEEDED,
                         result.command_status)
        self.assertEqual(None, result.command_error)
        self.assertEqual('v1', result.command_result)

    def test_sync_command_validation_failure(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.extension.execute,
                          'fake_sync_command',
                          is_valid=False)

    def test_sync_command_execution_failure(self):
        self.assertRaises(ExecutionError,
                          self.extension.execute,
                          'fake_sync_command',
                          param='v2')

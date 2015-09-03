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
    @base.async_command('fake_async_command', _fake_validator)
    def fake_async_command(self, is_valid=False, param=None):
        if param == 'v2':
            raise ExecutionError()
        return param

    @base.sync_command('fake_sync_command', _fake_validator)
    def fake_sync_command(self, is_valid=False, param=None):
        if param == 'v2':
            raise ExecutionError()
        return param

    @base.async_command('other_async_name')
    def second_async_command(self):
        pass

    @base.sync_command('other_sync_name')
    def second_sync_command(self):
        pass


class FakeAgent(base.ExecuteCommandMixin):
    def __init__(self):
        super(FakeAgent, self).__init__()
        self.ext_mgr = extension.ExtensionManager.make_test_instance(
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
        do_something_impl.assert_called_once_with(foo='bar')

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
        fake_ext = self.agent.get_extension('fake')
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
        fake_ext = self.agent.ext_mgr['fake'].obj
        fake_ext.execute = mock.Mock()
        exc = errors.CommandExecutionError('foo bar baz')
        fake_ext.execute.side_effect = exc
        result = self.agent.execute_command(
            'fake.sleep', sleep_info={"time": 1}
        )
        self.assertEqual(base.AgentCommandStatus.FAILED,
                         result.command_status)
        self.assertEqual(exc, result.command_error)


class TestExtensionDecorators(test_base.BaseTestCase):
    def setUp(self):
        super(TestExtensionDecorators, self).setUp()
        self.agent = FakeAgent()
        self.agent.force_heartbeat = mock.Mock()
        self.extension = FakeExtension(agent=self.agent)

    def test_async_command_success(self):
        result = self.extension.execute('fake_async_command', param='v1')
        self.assertIsInstance(result, base.AsyncCommandResult)
        result.join()
        self.assertEqual('fake_async_command', result.command_name)
        self.assertEqual({'param': 'v1'}, result.command_params)
        self.assertEqual(base.AgentCommandStatus.SUCCEEDED,
                         result.command_status)
        self.assertEqual(None, result.command_error)
        self.assertEqual({'result': 'fake_async_command: v1'},
                          result.command_result)
        self.agent.force_heartbeat.assert_called_once_with()

    def test_async_command_success_without_agent(self):
        extension = FakeExtension(agent=None)
        result = extension.execute('fake_async_command', param='v1')
        self.assertIsInstance(result, base.AsyncCommandResult)
        result.join()
        self.assertEqual('fake_async_command', result.command_name)
        self.assertEqual({'param': 'v1'}, result.command_params)
        self.assertEqual(base.AgentCommandStatus.SUCCEEDED,
                         result.command_status)
        self.assertEqual(None, result.command_error)
        self.assertEqual({'result': 'fake_async_command: v1'},
                          result.command_result)

    def test_async_command_validation_failure(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.extension.execute,
                          'fake_async_command',
                          is_valid=False)
        # validation is synchronous, no need to force a heartbeat
        self.assertEqual(0, self.agent.force_heartbeat.call_count)

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
        self.agent.force_heartbeat.assert_called_once_with()

    def test_async_command_name(self):
        self.assertEqual(
            'other_async_name',
            self.extension.second_async_command.command_name)

    def test_sync_command_success(self):
        result = self.extension.execute('fake_sync_command', param='v1')
        self.assertIsInstance(result, base.SyncCommandResult)
        self.assertEqual('fake_sync_command', result.command_name)
        self.assertEqual({'param': 'v1'}, result.command_params)
        self.assertEqual(base.AgentCommandStatus.SUCCEEDED,
                         result.command_status)
        self.assertEqual(None, result.command_error)
        self.assertEqual({'result': 'v1'}, result.command_result)
        # no need to force heartbeat on a sync command
        self.assertEqual(0, self.agent.force_heartbeat.call_count)

    def test_sync_command_validation_failure(self):
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.extension.execute,
                          'fake_sync_command',
                          is_valid=False)
        # validation is synchronous, no need to force a heartbeat
        self.assertEqual(0, self.agent.force_heartbeat.call_count)

    def test_sync_command_execution_failure(self):
        self.assertRaises(ExecutionError,
                          self.extension.execute,
                          'fake_sync_command',
                          param='v2')
        # no need to force heartbeat on a sync command
        self.assertEqual(0, self.agent.force_heartbeat.call_count)

    def test_sync_command_name(self):
        self.assertEqual(
            'other_sync_name',
            self.extension.second_sync_command.command_name)

    def test_command_map(self):
        expected_map = {
            'fake_async_command': self.extension.fake_async_command,
            'fake_sync_command': self.extension.fake_sync_command,
            'other_async_name': self.extension.second_async_command,
            'other_sync_name': self.extension.second_sync_command,
        }
        self.assertEqual(expected_map, self.extension.command_map)

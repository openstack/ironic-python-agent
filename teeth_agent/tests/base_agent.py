"""
Copyright 2013 Rackspace, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import json
import time
import unittest

import mock
import pkg_resources

from teeth_rest import encoding

from teeth_agent import base
from teeth_agent import errors


EXPECTED_ERROR = RuntimeError('command execution failed')


class FooTeethAgentCommandResult(base.AsyncCommandResult):
    def execute(self):
        if self.command_params['fail']:
            raise EXPECTED_ERROR
        else:
            return 'command execution succeeded'


class TestBaseTeethAgent(unittest.TestCase):
    def setUp(self):
        self.encoder = encoding.RESTJSONEncoder(
            encoding.SerializationViews.PUBLIC,
            indent=4)
        self.agent = base.BaseTeethAgent('fake_host',
                                         'fake_port',
                                         'fake_api',
                                         'TEST_MODE')

    def assertEqualEncoded(self, a, b):
        # Evidently JSONEncoder.default() can't handle None (??) so we have to
        # use encode() to generate JSON, then json.loads() to get back a python
        # object.
        a_encoded = self.encoder.encode(a)
        b_encoded = self.encoder.encode(b)
        self.assertEqual(json.loads(a_encoded), json.loads(b_encoded))

    def test_get_status(self):
        started_at = time.time()
        self.agent.started_at = started_at

        status = self.agent.get_status()
        self.assertIsInstance(status, base.TeethAgentStatus)
        self.assertEqual(status.mode, 'TEST_MODE')
        self.assertEqual(status.started_at, started_at)
        self.assertEqual(status.version,
                         pkg_resources.get_distribution('teeth-agent').version)

    def test_execute_command(self):
        do_something_impl = mock.Mock()
        self.agent.command_map = {
            'do_something': do_something_impl,
        }

        self.agent.execute_command('do_something', foo='bar')
        do_something_impl.assert_called_once_with('do_something', foo='bar')

    def test_execute_invalid_command(self):
        self.assertRaises(errors.InvalidCommandError,
                          self.agent.execute_command,
                          'do_something',
                          foo='bar')

    @mock.patch('werkzeug.serving.run_simple')
    def test_run(self, mocked_run_simple):
        self.agent.heartbeater = mock.Mock()
        self.agent.run()
        mocked_run_simple.assert_called_once_with('fake_host',
                                                  'fake_port',
                                                  self.agent.api)
        self.agent.heartbeater.start.assert_called_once_with()

        self.assertRaises(RuntimeError, self.agent.run)

    def test_async_command_success(self):
        result = FooTeethAgentCommandResult('foo_command', {'fail': False})
        expected_result = {
            'id': result.id,
            'command_name': 'foo_command',
            'command_params': {
                'fail': False,
            },
            'command_status': 'RUNNING',
            'command_result': None,
            'command_error': None,
        }
        self.assertEqualEncoded(result, expected_result)

        result.start()
        result.join()

        expected_result['command_status'] = 'SUCCEEDED'
        expected_result['command_result'] = 'command execution succeeded'

        self.assertEqualEncoded(result, expected_result)

    def test_async_command_failure(self):
        result = FooTeethAgentCommandResult('foo_command', {'fail': True})
        expected_result = {
            'id': result.id,
            'command_name': 'foo_command',
            'command_params': {
                'fail': True,
            },
            'command_status': 'RUNNING',
            'command_result': None,
            'command_error': None,
        }
        self.assertEqualEncoded(result, expected_result)

        result.start()
        result.join()

        expected_result['command_status'] = 'FAILED'
        expected_result['command_error'] = errors.CommandExecutionError(
            str(EXPECTED_ERROR))

        self.assertEqualEncoded(result, expected_result)

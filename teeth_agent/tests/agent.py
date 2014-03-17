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
from wsgiref import simple_server


from teeth_agent import agent
from teeth_agent import base
from teeth_agent import encoding
from teeth_agent import errors
from teeth_agent import hardware

EXPECTED_ERROR = RuntimeError('command execution failed')


def foo_execute(*args, **kwargs):
    if kwargs['fail']:
        raise EXPECTED_ERROR
    else:
        return 'command execution succeeded'


class FakeMode(base.BaseAgentMode):
    def __init__(self):
        super(FakeMode, self).__init__('FAKE')


class TestHeartbeater(unittest.TestCase):
    def setUp(self):
        self.mock_agent = mock.Mock()
        self.heartbeater = agent.TeethAgentHeartbeater(self.mock_agent)
        self.heartbeater.api = mock.Mock()
        self.heartbeater.hardware = mock.create_autospec(
            hardware.HardwareManager)
        self.heartbeater.stop_event = mock.Mock()

    @mock.patch('teeth_agent.agent._time')
    @mock.patch('random.uniform')
    def test_heartbeat(self, mocked_uniform, mocked_time):
        time_responses = []
        uniform_responses = []
        heartbeat_responses = []
        wait_responses = []
        expected_stop_event_calls = []

        # FIRST RUN:
        # initial delay is 0
        expected_stop_event_calls.append(mock.call(0))
        wait_responses.append(False)
        # next heartbeat due at t=100
        heartbeat_responses.append(100)
        # random interval multiplier is 0.5
        uniform_responses.append(0.5)
        # time is now 50
        time_responses.append(50)

        # SECOND RUN:
        # (100 - 50) * .5 = 25 (t becomes ~75)
        expected_stop_event_calls.append(mock.call(25.0))
        wait_responses.append(False)
        # next heartbeat due at t=180
        heartbeat_responses.append(180)
        # random interval multiplier is 0.4
        uniform_responses.append(0.4)
        # time is now 80
        time_responses.append(80)

        # THIRD RUN:
        # (180 - 80) * .4 = 40 (t becomes ~120)
        expected_stop_event_calls.append(mock.call(40.0))
        wait_responses.append(False)
        # this heartbeat attempt fails
        heartbeat_responses.append(Exception('uh oh!'))
        # we check the time to generate a fake deadline, now t=125
        time_responses.append(125)
        # random interval multiplier is 0.5
        uniform_responses.append(0.5)
        # time is now 125.5
        time_responses.append(125.5)

        # FOURTH RUN:
        # (125.5 - 125.0) * .5 = 0.25
        expected_stop_event_calls.append(mock.call(0.25))
        # Stop now
        wait_responses.append(True)

        # Hook it up and run it
        mocked_time.side_effect = time_responses
        mocked_uniform.side_effect = uniform_responses
        self.heartbeater.api.heartbeat.side_effect = heartbeat_responses
        self.heartbeater.stop_event.wait.side_effect = wait_responses
        self.heartbeater.run()

        # Validate expectations
        self.assertEqual(self.heartbeater.stop_event.wait.call_args_list,
                         expected_stop_event_calls)
        self.assertEqual(self.heartbeater.error_delay, 2.7)


class TestBaseAgent(unittest.TestCase):
    def setUp(self):
        self.encoder = encoding.RESTJSONEncoder(indent=4)
        self.agent = agent.TeethAgent('https://fake_api.example.org:8081/',
                                      ('localhost', 9999),
                                      '192.168.1.1')

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
        self.assertIsInstance(status, agent.TeethAgentStatus)
        self.assertEqual(status.started_at, started_at)
        self.assertEqual(status.version,
                         pkg_resources.get_distribution('teeth-agent').version)

    def test_execute_command(self):
        do_something_impl = mock.Mock()
        self.agent.mode_implementation = FakeMode()
        command_map = self.agent.mode_implementation.command_map
        command_map['do_something'] = do_something_impl

        self.agent.execute_command('fake.do_something', foo='bar')
        do_something_impl.assert_called_once_with('do_something', foo='bar')

    def test_execute_invalid_command(self):
        self.assertRaises(errors.InvalidCommandError,
                          self.agent.execute_command,
                          'do_something',
                          foo='bar')

    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    def test_run(self, wsgi_server_cls):
        wsgi_server = wsgi_server_cls.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.heartbeater = mock.Mock()
        self.agent.run()

        listen_addr = ('localhost', 9999)
        wsgi_server_cls.assert_called_once_with(
            listen_addr[0],
            listen_addr[1],
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once()

        self.agent.heartbeater.start.assert_called_once_with()

    def test_async_command_success(self):
        result = base.AsyncCommandResult('foo_command', {'fail': False},
                                         foo_execute)
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
        result = base.AsyncCommandResult('foo_command', {'fail': True},
                                         foo_execute)
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

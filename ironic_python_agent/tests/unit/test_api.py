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

import time
from unittest import mock

from oslo_config import cfg
from werkzeug import test as http_test
from werkzeug import wrappers

from ironic_python_agent import agent
from ironic_python_agent.api import app
from ironic_python_agent.extensions import base
from ironic_python_agent.tests.unit import base as ironic_agent_base


PATH_PREFIX = '/v1'


class Response(wrappers.Response):
    pass


class TestIronicAPI(ironic_agent_base.IronicAgentTest):

    def setUp(self):
        super(TestIronicAPI, self).setUp()
        self.mock_agent = mock.MagicMock()
        self.app = app.Application(self.mock_agent, cfg.CONF)
        self.client = http_test.Client(self.app, Response)

    def _request_json(self, path, params=None, expect_errors=False,
                      headers=None, method="post", path_prefix=PATH_PREFIX):
        """Sends simulated HTTP request to the test app.

        :param path: url path of target service
        :param params: content for wsgi.input of request
        :param expect_errors: Boolean value; whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        :param method: Request method type. Appropriate method function call
                       should be used rather than passing attribute in.
        :param path_prefix: prefix of the url path
        """
        full_path = path_prefix + path
        print('%s: %s %s' % (method.upper(), full_path, params))
        response = self.client.open(
            str(full_path),
            method=method.upper(),
            json=params,
            headers=headers,
            follow_redirects=True,
        )
        print('GOT:%s' % response)
        if not expect_errors:
            self.assertLess(response.status_code, 400)
        return response

    def put_json(self, path, params, expect_errors=False, headers=None):
        """Sends simulated HTTP PUT request to the test app.

        :param path: url path of target service
        :param params: content for wsgi.input of request
        :param expect_errors: Boolean value; whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        """
        return self._request_json(path=path, params=params,
                                  expect_errors=expect_errors,
                                  headers=headers, method="put")

    def post_json(self, path, params, expect_errors=False, headers=None):
        """Sends simulated HTTP POST request to the test app.

        :param path: url path of target service
        :param params: content for wsgi.input of request
        :param expect_errors: Boolean value; whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        """
        return self._request_json(path=path, params=params,
                                  expect_errors=expect_errors,
                                  headers=headers, method="post")

    def get_json(self, path, expect_errors=False, headers=None,
                 path_prefix=PATH_PREFIX):
        """Sends simulated HTTP GET request to the test app.

        :param path: url path of target service
        :param expect_errors: Boolean value;whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        :param path_prefix: prefix of the url path
        """
        return self._request_json(path=path, expect_errors=expect_errors,
                                  headers=headers, method="get",
                                  path_prefix=path_prefix)

    def test_root(self):
        response = self.get_json('/', path_prefix='')
        data = response.json
        self.assertEqual('OpenStack Ironic Python Agent API', data['name'])

    def test_v1_root(self):
        response = self.get_json('/v1', path_prefix='')
        data = response.json
        self.assertIn('status', data)
        self.assertIn('commands', data)

    def test_not_found(self):
        response = self.get_json('/v1/foo', path_prefix='',
                                 expect_errors=True)
        self.assertEqual(404, response.status_code)
        data = response.json
        self.assertEqual('Client', data['faultcode'])

    def test_get_agent_status(self):
        status = agent.IronicPythonAgentStatus(time.time(),
                                               'v72ac9')
        self.mock_agent.get_status.return_value = status

        response = self.get_json('/status')
        self.mock_agent.get_status.assert_called_once_with()

        self.assertEqual(200, response.status_code)
        data = response.json
        self.assertEqual(status.started_at, data['started_at'])
        self.assertEqual(status.version, data['version'])

    def test_execute_agent_command_success_no_wait(self):
        command = {
            'name': 'do_things',
            'params': {'key': 'value'},
        }

        result = base.SyncCommandResult(command['name'],
                                        command['params'],
                                        True,
                                        {'test': 'result'})

        self.mock_agent.execute_command.return_value = result

        with mock.patch.object(result, 'join', autospec=True) as join_mock:
            response = self.post_json('/commands', command)
            self.assertFalse(join_mock.called)

        self.assertEqual(200, response.status_code)

        self.assertEqual(1, self.mock_agent.execute_command.call_count)
        args, kwargs = self.mock_agent.execute_command.call_args
        self.assertEqual(('do_things',), args)
        self.assertEqual({'key': 'value'}, kwargs)
        expected_result = result.serialize()
        data = response.json
        self.assertEqual(expected_result, data)

    def test_execute_agent_command_success_with_true_wait(self):
        command = {
            'name': 'do_things',
            'params': {'key': 'value'},
        }

        result = base.SyncCommandResult(command['name'],
                                        command['params'],
                                        True,
                                        {'test': 'result'})

        self.mock_agent.execute_command.return_value = result

        with mock.patch.object(result, 'join', autospec=True) as join_mock:
            response = self.post_json('/commands?wait=true', command)
            join_mock.assert_called_once_with()

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, self.mock_agent.execute_command.call_count)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        args, kwargs = self.mock_agent.execute_command.call_args
        self.assertEqual(('do_things',), args)
        self.assertEqual({'key': 'value'}, kwargs)
        expected_result = result.serialize()
        data = response.json
        self.assertEqual(expected_result, data)

    def test_execute_agent_command_success_with_false_wait(self):
        command = {
            'name': 'do_things',
            'params': {'key': 'value'},
        }

        result = base.SyncCommandResult(command['name'],
                                        command['params'],
                                        True,
                                        {'test': 'result'})

        self.mock_agent.execute_command.return_value = result

        with mock.patch.object(result, 'join', autospec=True) as join_mock:
            response = self.post_json('/commands?wait=false', command)
            self.assertFalse(join_mock.called)

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, self.mock_agent.execute_command.call_count)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        args, kwargs = self.mock_agent.execute_command.call_args
        self.assertEqual(('do_things',), args)
        self.assertEqual({'key': 'value'}, kwargs)
        expected_result = result.serialize()
        data = response.json
        self.assertEqual(expected_result, data)

    def test_execute_agent_command_validation(self):
        invalid_command = {}
        response = self.post_json('/commands',
                                  invalid_command,
                                  expect_errors=True)
        self.assertEqual(400, response.status_code)
        data = response.json
        self.assertEqual('Client', data['faultcode'])
        msg = 'Missing or invalid name or params'
        self.assertIn(msg, data['faultstring'])

    def test_execute_agent_command_params_validation(self):
        invalid_command = {'name': 'do_things', 'params': []}
        response = self.post_json('/commands',
                                  invalid_command,
                                  expect_errors=True)
        self.assertEqual(400, response.status_code)
        data = response.json
        self.assertEqual('Client', data['faultcode'])
        # this message is actually much longer, but I'm ok with this
        msg = 'Missing or invalid name or params'
        self.assertIn(msg, data['faultstring'])

    def test_list_command_results(self):
        cmd_result = base.SyncCommandResult(u'do_things',
                                            {u'key': u'value'},
                                            True,
                                            {u'test': u'result'})

        self.mock_agent.list_command_results.return_value = [
            cmd_result,
        ]

        response = self.get_json('/commands')
        self.assertEqual(200, response.status_code)
        self.assertEqual({
            u'commands': [
                cmd_result.serialize(),
            ],
        }, response.json)

    def test_get_command_result(self):
        cmd_result = base.SyncCommandResult('do_things',
                                            {'key': 'value'},
                                            True,
                                            {'test': 'result'})
        serialized_cmd_result = cmd_result.serialize()

        self.mock_agent.get_command_result.return_value = cmd_result

        response = self.get_json('/commands/abc123')
        self.assertEqual(200, response.status_code)
        data = response.json
        self.assertEqual(serialized_cmd_result, data)

    def test_execute_agent_command_with_token(self):
        agent_token = str('0123456789' * 10)
        command = {
            'name': 'do_things',
            'params': {'key': 'value',
                       'wait': False,
                       'agent_token': agent_token},
        }

        result = base.SyncCommandResult(command['name'],
                                        command['params'],
                                        True,
                                        {'test': 'result'})

        self.mock_agent.validate_agent_token.return_value = True
        self.mock_agent.execute_command.return_value = result

        with mock.patch.object(result, 'join', autospec=True) as join_mock:
            response = self.post_json(
                '/commands?wait=false?agent_token=%s' % agent_token,
                command)
            self.assertFalse(join_mock.called)

        self.assertEqual(200, response.status_code)

        self.assertEqual(1, self.mock_agent.execute_command.call_count)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        args, kwargs = self.mock_agent.execute_command.call_args
        self.assertEqual(('do_things',), args)
        expected_result = result.serialize()
        data = response.json
        self.assertEqual(expected_result, data)

    def test_execute_agent_command_with_token_invalid(self):
        agent_token = str('0123456789' * 10)
        command = {
            'name': 'do_things',
            'params': {'key': 'value',
                       'wait': False,
                       'agent_token': agent_token},
        }

        self.mock_agent.validate_agent_token.return_value = False
        response = self.post_json(
            '/commands?wait=false?agent_token=%s' % agent_token,
            command,
            expect_errors=True)

        self.assertEqual(401, response.status_code)

        self.assertEqual(0, self.mock_agent.execute_command.call_count)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)

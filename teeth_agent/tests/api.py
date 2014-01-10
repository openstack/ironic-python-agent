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
import mock
import time
import unittest

from werkzeug import test
from werkzeug import wrappers

from teeth_rest import encoding

from teeth_agent import api
from teeth_agent import base


class TestTeethAPI(unittest.TestCase):
    def _get_env_builder(self, method, path, data=None, query=None):
        if data is not None:
            data = json.dumps(data)

        return test.EnvironBuilder(method=method,
                                   path=path,
                                   data=data,
                                   content_type='application/json',
                                   query_string=query)

    def _make_request(self, api, method, path, data=None, query=None):
        client = test.Client(api, wrappers.BaseResponse)
        return client.open(self._get_env_builder(method, path, data, query))

    def test_get_agent_status(self):
        status = base.TeethAgentStatus('TEST_MODE', time.time(), 'v72ac9')
        mock_agent = mock.MagicMock()
        mock_agent.get_status.return_value = status
        api_server = api.TeethAgentAPIServer(mock_agent)

        response = self._make_request(api_server, 'GET', '/v1.0/status')
        mock_agent.get_status.assert_called_once_with()

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['mode'], status.mode)
        self.assertEqual(data['started_at'], status.started_at)
        self.assertEqual(data['version'], status.version)

    def test_execute_agent_command_success(self):
        command = {
            'name': 'do_things',
            'params': {'key': 'value'},
        }

        result = base.SyncCommandResult(command['name'],
                                        command['params'],
                                        True,
                                        {'test': 'result'})

        mock_agent = mock.MagicMock()
        mock_agent.execute_command.return_value = result
        api_server = api.TeethAgentAPIServer(mock_agent)

        response = self._make_request(api_server,
                                      'POST',
                                      '/v1.0/commands',
                                      data=command)

        self.assertEqual(mock_agent.execute_command.call_count, 1)
        args, kwargs = mock_agent.execute_command.call_args
        self.assertEqual(args, ('do_things',))
        self.assertEqual(kwargs, {'key': 'value'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        expected_result = result.serialize(encoding.SerializationViews.PUBLIC)
        self.assertEqual(data, expected_result)

    def test_execute_agent_command_validation(self):
        mock_agent = mock.MagicMock()
        api_server = api.TeethAgentAPIServer(mock_agent)

        invalid_command = {}
        response = self._make_request(api_server,
                                      'POST',
                                      '/v1.0/commands',
                                      data=invalid_command)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertEqual(data['details'], 'Missing command \'name\' field.')

    def test_execute_agent_command_params_validation(self):
        mock_agent = mock.MagicMock()
        api_server = api.TeethAgentAPIServer(mock_agent)

        invalid_command = {'name': 'do_things', 'params': []}
        response = self._make_request(api_server,
                                      'POST',
                                      '/v1.0/commands',
                                      data=invalid_command)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.data)
        self.assertEqual(data['details'],
                         'Command params must be a dictionary.')

    def test_list_command_results(self):
        cmd_result = base.SyncCommandResult('do_things',
                                            {'key': 'value'},
                                            True,
                                            {'test': 'result'})

        mock_agent = mock.create_autospec(base.BaseTeethAgent)
        mock_agent.list_command_results.return_value = [
            cmd_result,
        ]

        api_server = api.TeethAgentAPIServer(mock_agent)
        response = self._make_request(api_server, 'GET', '/v1.0/commands')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.data), {
            'items': [
                cmd_result.serialize(encoding.SerializationViews.PUBLIC),
            ],
            'links': [],
        })

    def test_get_command_result(self):
        cmd_result = base.SyncCommandResult('do_things',
                                            {'key': 'value'},
                                            True,
                                            {'test': 'result'})

        serialized_cmd_result = cmd_result.serialize(
            encoding.SerializationViews.PUBLIC)

        mock_agent = mock.create_autospec(base.BaseTeethAgent)
        mock_agent.get_command_result.return_value = cmd_result

        api_server = api.TeethAgentAPIServer(mock_agent)
        response = self._make_request(api_server,
                                      'GET',
                                      '/v1.0/commands/abc123')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data, serialized_cmd_result)

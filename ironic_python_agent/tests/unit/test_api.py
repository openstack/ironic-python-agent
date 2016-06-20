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

import mock
from oslotest import base as test_base
import pecan
import pecan.testing

from ironic_python_agent import agent
from ironic_python_agent.extensions import base


PATH_PREFIX = '/v1'


class TestIronicAPI(test_base.BaseTestCase):

    def setUp(self):
        super(TestIronicAPI, self).setUp()
        self.mock_agent = mock.MagicMock()
        self.app = self._make_app()

    def tearDown(self):
        super(TestIronicAPI, self).tearDown()
        pecan.set_config({}, overwrite=True)

    def _make_app(self):
        self.config = {
            'app': {
                'root': 'ironic_python_agent.api.controllers.root.'
                        'RootController',
                'modules': ['ironic_python_agent.api'],
                'static_root': '',
                'debug': True,
            },
        }

        return pecan.testing.load_test_app(config=self.config,
                                           agent=self.mock_agent)

    def _request_json(self, path, params, expect_errors=False, headers=None,
                      method="post", extra_environ=None, status=None,
                      path_prefix=PATH_PREFIX):
        """Sends simulated HTTP request to Pecan test app.

        :param path: url path of target service
        :param params: content for wsgi.input of request
        :param expect_errors: Boolean value; whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        :param method: Request method type. Appropriate method function call
                       should be used rather than passing attribute in.
        :param extra_environ: a dictionary of environ variables to send along
                              with the request
        :param status: expected status code of response
        :param path_prefix: prefix of the url path
        """
        full_path = path_prefix + path
        print('%s: %s %s' % (method.upper(), full_path, params))
        response = getattr(self.app, "%s_json" % method)(
            str(full_path),
            params=params,
            headers=headers,
            status=status,
            extra_environ=extra_environ,
            expect_errors=expect_errors
        )
        print('GOT:%s' % response)
        return response

    def put_json(self, path, params, expect_errors=False, headers=None,
                 extra_environ=None, status=None):
        """Sends simulated HTTP PUT request to Pecan test app.

        :param path: url path of target service
        :param params: content for wsgi.input of request
        :param expect_errors: Boolean value; whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        :param extra_environ: a dictionary of environ variables to send along
                              with the request
        :param status: expected status code of response
        """
        return self._request_json(path=path, params=params,
                                  expect_errors=expect_errors,
                                  headers=headers, extra_environ=extra_environ,
                                  status=status, method="put")

    def post_json(self, path, params, expect_errors=False, headers=None,
                  extra_environ=None, status=None):
        """Sends simulated HTTP POST request to Pecan test app.

        :param path: url path of target service
        :param params: content for wsgi.input of request
        :param expect_errors: Boolean value; whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        :param extra_environ: a dictionary of environ variables to send along
                              with the request
        :param status: expected status code of response
        """
        return self._request_json(path=path, params=params,
                                  expect_errors=expect_errors,
                                  headers=headers, extra_environ=extra_environ,
                                  status=status, method="post")

    def get_json(self, path, expect_errors=False, headers=None,
                 extra_environ=None, q=None, path_prefix=PATH_PREFIX,
                 **params):
        """Sends simulated HTTP GET request to Pecan test app.

        :param path: url path of target service
        :param expect_errors: Boolean value;whether an error is expected based
                              on request
        :param headers: a dictionary of headers to send along with the request
        :param extra_environ: a dictionary of environ variables to send along
                              with the request
        :param q: list of queries consisting of: field, value, op, and type
                  keys
        :param path_prefix: prefix of the url path
        :param params: content for wsgi.input of request
        """
        full_path = path_prefix + path
        query_params = {'q.field': [],
                        'q.value': [],
                        'q.op': [],
                        }
        q = [] if q is None else q
        for query in q:
            for name in ['field', 'op', 'value']:
                query_params['q.%s' % name].append(query.get(name, ''))
        all_params = {}
        all_params.update(params)
        if q:
            all_params.update(query_params)
        print('GET: %s %r' % (full_path, all_params))
        response = self.app.get(full_path,
                                params=all_params,
                                headers=headers,
                                extra_environ=extra_environ,
                                expect_errors=expect_errors)
        print('GOT:%s' % response)
        return response

    def test_root(self):
        response = self.get_json('/', path_prefix='')
        data = response.json
        self.assertEqual('OpenStack Ironic Python Agent API', data['name'])

    def test_v1_root(self):
        response = self.get_json('/v1', path_prefix='')
        data = response.json
        self.assertIn('status', data)
        self.assertIn('commands', data)

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

        with mock.patch.object(result, 'join') as join_mock:
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

        with mock.patch.object(result, 'join') as join_mock:
            response = self.post_json('/commands?wait=true', command)
            join_mock.assert_called_once_with()

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, self.mock_agent.execute_command.call_count)
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

        with mock.patch.object(result, 'join') as join_mock:
            response = self.post_json('/commands?wait=false', command)
            self.assertFalse(join_mock.called)

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, self.mock_agent.execute_command.call_count)
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
        msg = 'Invalid input for field/attribute name.'
        self.assertIn(msg, data['faultstring'])
        msg = 'Mandatory field missing'
        self.assertIn(msg, data['faultstring'])

    def test_execute_agent_command_params_validation(self):
        invalid_command = {'name': 'do_things', 'params': []}
        response = self.post_json('/commands',
                                  invalid_command,
                                  expect_errors=True)
        self.assertEqual(400, response.status_code)
        data = response.json
        # this message is actually much longer, but I'm ok with this
        msg = 'Invalid input for field/attribute params.'
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

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

import ssl
import tempfile
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

    def test_list_commands_with_token(self):
        agent_token = str('0123456789' * 10)
        cmd_result = base.SyncCommandResult('do_things',
                                            {'key': 'value'},
                                            True,
                                            {'test': 'result'})
        self.mock_agent.list_command_results.return_value = [cmd_result]
        self.mock_agent.validate_agent_token.return_value = True

        response = self.get_json('/commands?agent_token=%s' % agent_token)

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        self.assertEqual(1, self.mock_agent.list_command_results.call_count)

    def test_list_commands_with_token_invalid(self):
        agent_token = str('0123456789' * 10)
        self.mock_agent.validate_agent_token.return_value = False

        response = self.get_json('/commands?agent_token=%s' % agent_token,
                                 expect_errors=True)

        self.assertEqual(401, response.status_code)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        self.assertEqual(0, self.mock_agent.list_command_results.call_count)

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

    def test_get_command_with_token(self):
        agent_token = str('0123456789' * 10)
        cmd_result = base.SyncCommandResult('do_things',
                                            {'key': 'value'},
                                            True,
                                            {'test': 'result'})
        self.mock_agent.get_command_result.return_value = cmd_result
        self.mock_agent.validate_agent_token.return_value = True

        response = self.get_json(
            '/commands/abc123?agent_token=%s' % agent_token)

        self.assertEqual(200, response.status_code)
        self.assertEqual(cmd_result.serialize(), response.json)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        self.assertEqual(1, self.mock_agent.get_command_result.call_count)

    def test_get_command_with_token_invalid(self):
        agent_token = str('0123456789' * 10)
        self.mock_agent.validate_agent_token.return_value = False

        response = self.get_json(
            '/commands/abc123?agent_token=%s' % agent_token,
            expect_errors=True)

        self.assertEqual(401, response.status_code)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        self.assertEqual(0, self.mock_agent.get_command_result.call_count)

    def test_get_command_locks_out_with_token(self):
        """Tests agent backwards compatibility and verifies upgrade lockout."""
        cmd_result = base.SyncCommandResult('do_things',
                                            {'key': 'value'},
                                            True,
                                            {'test': 'result'})
        cmd_result.serialize()
        self.mock_agent.get_command_result.return_value = cmd_result
        agent_token = str('0123456789' * 10)
        self.mock_agent.validate_agent_token.return_value = False

        # Backwards compatible operation check.
        response = self.get_json(
            '/commands/abc123')
        self.assertEqual(200, response.status_code)
        self.assertFalse(self.app.security_get_token_support)
        self.assertEqual(1, self.mock_agent.get_command_result.call_count)
        self.mock_agent.reset_mock()

        # Check with a newer ironic sending an agent_token upon the command.
        # For context, in this case the token is wrong intentionally.
        # It doesn't have to be right, but what we're testing is the
        # submission of any value triggers the lockout
        response = self.get_json(
            '/commands/abc123?agent_token=%s' % agent_token,
            expect_errors=True)
        self.assertTrue(self.app.security_get_token_support)
        self.assertEqual(401, response.status_code)
        self.assertEqual(1, self.mock_agent.validate_agent_token.call_count)
        self.assertEqual(0, self.mock_agent.get_command_result.call_count)

        # Verifying the lockout is now being enforced and that agent token
        # is now required by the agent.
        response = self.get_json(
            '/commands/abc123', expect_errors=True)
        self.assertTrue(self.app.security_get_token_support)
        self.assertEqual(401, response.status_code)
        self.assertEqual(0, self.mock_agent.get_command_result.call_count)
        # Verify we still called validate_agent_token
        self.assertEqual(2, self.mock_agent.validate_agent_token.call_count)

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


class TestApplicationStart(ironic_agent_base.IronicAgentTest):
    """Tests for Application.start() method."""

    def setUp(self):
        super(TestApplicationStart, self).setUp()
        self.mock_agent = mock.MagicMock()
        self.mock_agent.listen_address.hostname = '0.0.0.0'
        self.mock_agent.listen_address.port = 9999
        self.app = app.Application(self.mock_agent, cfg.CONF)

    @mock.patch('ironic_python_agent.api.app.wsgi.Server', autospec=True)
    @mock.patch('ironic_python_agent.api.app.TLSEnforcingSSLAdapter',
                autospec=True)
    @mock.patch('ironic_python_agent.utils.create_ssl_context',
                autospec=True)
    def test_start_with_tls(self, mock_create_ssl_context,
                            mock_ssl_adapter, mock_server_cls):
        """Test that start() properly configures TLS with SSL adapter."""
        # Create temporary cert and key files
        with tempfile.NamedTemporaryFile(mode='w', delete=False,
                                         suffix='.crt') as cert_file:
            cert_file.write('FAKE CERT')
            cert_path = cert_file.name

        with tempfile.NamedTemporaryFile(mode='w', delete=False,
                                         suffix='.key') as key_file:
            key_file.write('FAKE KEY')
            key_path = key_file.name

        try:
            # Mock SSL context
            mock_ssl_ctx = mock.Mock()
            mock_create_ssl_context.return_value = mock_ssl_ctx

            # Mock the server instance
            mock_server = mock.Mock()
            mock_server_cls.return_value = mock_server

            # Start the app with TLS
            self.app.start(tls_cert_file=cert_path,
                           tls_key_file=key_path)

            # Verify SSL context was created with 'server' mode
            mock_create_ssl_context.assert_called_once_with('server')

            # Verify SSL context was configured
            mock_ssl_ctx.load_cert_chain.assert_called_once_with(
                certfile=cert_path,
                keyfile=key_path
            )
            self.assertFalse(mock_ssl_ctx.check_hostname)
            self.assertEqual(ssl.CERT_NONE, mock_ssl_ctx.verify_mode)

            # Verify TLSEnforcingSSLAdapter was created with correct params
            mock_ssl_adapter.assert_called_once_with(
                certificate=cert_path,
                private_key=key_path,
                ssl_context=mock_ssl_ctx
            )

            # Verify ssl_adapter was assigned to server
            self.assertEqual(mock_ssl_adapter.return_value,
                             mock_server.ssl_adapter)

            # Verify server was prepared and started
            mock_server.prepare.assert_called_once()
            self.assertIsNotNone(self.app.server)

            # Stop the server
            self.app.stop()
        finally:
            # Clean up temp files
            import os
            try:
                os.unlink(cert_path)
                os.unlink(key_path)
            except Exception:
                pass

    @mock.patch('ironic_python_agent.api.app.wsgi.Server', autospec=True)
    def test_start_without_tls(self, mock_server_cls):
        """Test that start() works without TLS."""
        # Mock the server instance
        mock_server = mock.Mock()
        mock_server_cls.return_value = mock_server

        self.app.start()

        # Verify server was started without SSL adapter
        self.assertIsNotNone(self.app.server)
        # The mock server won't have ssl_adapter attribute set
        # since we don't assign it in the non-TLS path
        mock_server.prepare.assert_called_once()

        # Stop the server
        self.app.stop()

    @mock.patch('cheroot.ssl.builtin.BuiltinSSLAdapter.__init__',
                autospec=True, return_value=None)
    def test_tls_adapter_wrap_returns_tuple(self, mock_parent_init):
        """Test that TLSEnforcingSSLAdapter.wrap() returns tuple."""
        # Create a mock SSL context
        mock_ssl_ctx = mock.Mock()
        mock_wrapped_socket = mock.Mock()
        mock_ssl_ctx.wrap_socket.return_value = mock_wrapped_socket

        # Create the adapter with SSL context
        # The parent __init__ is mocked so no cert validation occurs
        adapter = app.TLSEnforcingSSLAdapter(
            certificate='/fake/cert.pem',
            private_key='/fake/key.pem',
            ssl_context=mock_ssl_ctx
        )

        # Manually set _custom_context since we bypassed __init__
        adapter._custom_context = mock_ssl_ctx

        # Create a mock socket to wrap
        mock_sock = mock.Mock()

        # Mock get_environ to return a dict
        with mock.patch.object(adapter, 'get_environ', autospec=True,
                               return_value={'SSL_PROTOCOL': 'TLSv1.2'}):
            # Call wrap and verify it returns a tuple
            result = adapter.wrap(mock_sock)

        # Verify result is a tuple
        self.assertIsInstance(result, tuple)
        self.assertEqual(2, len(result))

        # Verify first element is the wrapped socket
        self.assertEqual(mock_wrapped_socket, result[0])

        # Verify second element is a dict (SSL environ)
        self.assertIsInstance(result[1], dict)

        # Verify wrap_socket was called correctly
        mock_ssl_ctx.wrap_socket.assert_called_once_with(
            mock_sock,
            server_side=True,
            do_handshake_on_connect=True
        )

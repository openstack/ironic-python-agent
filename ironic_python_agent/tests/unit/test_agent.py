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

import json
import time

import mock
from oslo_config import cfg
from oslotest import base as test_base
import pkg_resources
from stevedore import extension
from wsgiref import simple_server

from ironic_python_agent import agent
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import inspector

EXPECTED_ERROR = RuntimeError('command execution failed')

CONF = cfg.CONF


def foo_execute(*args, **kwargs):
    if kwargs['fail']:
        raise EXPECTED_ERROR
    else:
        return 'command execution succeeded'


class FakeExtension(base.BaseAgentExtension):
    pass


class TestHeartbeater(test_base.BaseTestCase):
    def setUp(self):
        super(TestHeartbeater, self).setUp()
        self.mock_agent = mock.Mock()
        self.mock_agent.api_url = 'https://fake_api.example.org:8081/'
        self.heartbeater = agent.IronicPythonAgentHeartbeater(self.mock_agent)
        self.heartbeater.api = mock.Mock()
        self.heartbeater.hardware = mock.create_autospec(
            hardware.HardwareManager)
        self.heartbeater.stop_event = mock.Mock()

    @mock.patch('os.read')
    @mock.patch('select.poll')
    @mock.patch('ironic_python_agent.agent._time')
    @mock.patch('random.uniform')
    def test_heartbeat(self, mocked_uniform, mocked_time, mock_poll,
                       mock_read):
        time_responses = []
        uniform_responses = []
        heartbeat_responses = []
        poll_responses = []
        expected_poll_calls = []

        # FIRST RUN:
        # initial delay is 0
        expected_poll_calls.append(mock.call(0))
        poll_responses.append(False)
        # next heartbeat due at t=100
        heartbeat_responses.append(100)
        # random interval multiplier is 0.5
        uniform_responses.append(0.5)
        # time is now 50
        time_responses.append(50)

        # SECOND RUN:
        # 50 * .5 = 25
        expected_poll_calls.append(mock.call(1000 * 25.0))
        poll_responses.append(False)
        # next heartbeat due at t=180
        heartbeat_responses.append(180)
        # random interval multiplier is 0.4
        uniform_responses.append(0.4)
        # time is now 80
        time_responses.append(80)

        # THIRD RUN:
        # 50 * .4 = 20
        expected_poll_calls.append(mock.call(1000 * 20.0))
        poll_responses.append(False)
        # this heartbeat attempt fails
        heartbeat_responses.append(Exception('uh oh!'))
        # we check the time to generate a fake deadline, now t=125
        time_responses.append(125)
        # random interval multiplier is 0.5
        uniform_responses.append(0.5)
        # time is now 125.5
        time_responses.append(125.5)

        # FOURTH RUN:
        # 50 * .5 = 25
        expected_poll_calls.append(mock.call(1000 * 25.0))
        # Stop now
        poll_responses.append(True)
        mock_read.return_value = 'a'

        # Hook it up and run it
        mocked_time.side_effect = time_responses
        mocked_uniform.side_effect = uniform_responses
        self.mock_agent.heartbeat_timeout = 50
        self.heartbeater.api.heartbeat.side_effect = heartbeat_responses
        mock_poll.return_value.poll.side_effect = poll_responses
        self.heartbeater.run()

        # Validate expectations
        self.assertEqual(expected_poll_calls,
                         mock_poll.return_value.poll.call_args_list)
        self.assertEqual(self.heartbeater.error_delay, 2.7)


class TestBaseAgent(test_base.BaseTestCase):

    def setUp(self):
        super(TestBaseAgent, self).setUp()
        self.encoder = encoding.RESTJSONEncoder(indent=4)

        self.agent = agent.IronicPythonAgent('https://fake_api.example.'
                                             'org:8081/',
                                             ('203.0.113.1', 9990),
                                             ('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             'agent_ipmitool',
                                             False)
        self.agent.ext_mgr = extension.ExtensionManager.\
            make_test_instance([extension.Extension('fake', None,
                                                    FakeExtension,
                                                    FakeExtension())])

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
        self.assertTrue(isinstance(status, agent.IronicPythonAgentStatus))
        self.assertEqual(status.started_at, started_at)
        self.assertEqual(status.version,
                         pkg_resources.get_distribution('ironic-python-agent')
                         .version)

    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run(self, mocked_list_hardware, wsgi_server_cls):
        CONF.set_override('inspection_callback_url', '')
        wsgi_server = wsgi_server_cls.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'heartbeat_timeout': 300
        }
        self.agent.run()

        listen_addr = ('192.0.2.1', 9999)
        wsgi_server_cls.assert_called_once_with(
            listen_addr[0],
            listen_addr[1],
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()

        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch.object(inspector, 'inspect', autospec=True)
    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run_with_inspection(self, mocked_list_hardware, wsgi_server_cls,
                                 mocked_inspector):
        CONF.set_override('inspection_callback_url', 'http://foo/bar')

        wsgi_server = wsgi_server_cls.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        mocked_inspector.return_value = 'uuid'

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'heartbeat_timeout': 300,
        }
        self.agent.run()

        listen_addr = ('192.0.2.1', 9999)
        wsgi_server_cls.assert_called_once_with(
            listen_addr[0],
            listen_addr[1],
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()
        mocked_inspector.assert_called_once_with()
        self.assertEqual(1, self.agent.api_client.lookup_node.call_count)
        self.assertEqual(
            'uuid',
            self.agent.api_client.lookup_node.call_args[1]['node_uuid'])

        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch('os.read')
    @mock.patch('select.poll')
    @mock.patch('time.sleep', return_value=None)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_network_interfaces')
    @mock.patch.object(hardware.GenericHardwareManager, 'get_ipv4_addr')
    def test_ipv4_lookup(self,
                         mock_get_ipv4,
                         mock_list_net,
                         mock_time_sleep,
                         mock_poll,
                         mock_read):
        homeless_agent = agent.IronicPythonAgent('https://fake_api.example.'
                                                 'org:8081/',
                                                 (None, 9990),
                                                 ('192.0.2.1', 9999),
                                                 3,
                                                 10,
                                                 None,
                                                 300,
                                                 1,
                                                 'agent_ipmitool',
                                                 False)

        mock_poll.return_value.poll.return_value = True
        mock_read.return_value = 'a'

        # Can't find network interfaces, and therefore can't find IP
        mock_list_net.return_value = []
        mock_get_ipv4.return_value = None
        self.assertRaises(errors.LookupAgentInterfaceError,
                          homeless_agent.set_agent_advertise_addr)

        # Can look up network interfaces, but not IP.  Network interface not
        # set, because no interface yields an IP.
        mock_ifaces = [hardware.NetworkInterface('eth0', '00:00:00:00:00:00'),
                       hardware.NetworkInterface('eth1', '00:00:00:00:00:01')]
        mock_list_net.return_value = mock_ifaces

        self.assertRaises(errors.LookupAgentIPError,
                          homeless_agent.set_agent_advertise_addr)
        self.assertEqual(6, mock_get_ipv4.call_count)
        self.assertEqual(None, homeless_agent.network_interface)

        # First interface eth0 has no IP, second interface eth1 has an IP
        mock_get_ipv4.side_effect = [None, '1.1.1.1']
        homeless_agent.heartbeater.run()
        self.assertEqual(('1.1.1.1', 9990), homeless_agent.advertise_address)
        self.assertEqual('eth1', homeless_agent.network_interface)

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
        expected_result['command_result'] = {'result': ('foo_command: command '
                                                        'execution succeeded')}

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

    def test_get_node_uuid(self):
        self.agent.node = {'uuid': 'fake-node'}
        self.assertEqual('fake-node', self.agent.get_node_uuid())

    def test_get_node_uuid_unassociated(self):
        self.assertRaises(errors.UnknownNodeError,
                          self.agent.get_node_uuid)

    def test_get_node_uuid_invalid_node(self):
        self.agent.node = {}
        self.assertRaises(errors.UnknownNodeError,
                          self.agent.get_node_uuid)


class TestAgentStandalone(test_base.BaseTestCase):

    def setUp(self):
        super(TestAgentStandalone, self).setUp()
        self.agent = agent.IronicPythonAgent('https://fake_api.example.'
                                             'org:8081/',
                                             ('203.0.113.1', 9990),
                                             ('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             'agent_ipmitool',
                                             True)

    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run(self, mocked_list_hardware, wsgi_server_cls):
        wsgi_server = wsgi_server_cls.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'heartbeat_timeout': 300
        }
        self.agent.run()

        listen_addr = ('192.0.2.1', 9999)
        wsgi_server_cls.assert_called_once_with(
            listen_addr[0],
            listen_addr[1],
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()

        self.assertFalse(self.agent.heartbeater.called)
        self.assertFalse(self.agent.api_client.lookup_node.called)

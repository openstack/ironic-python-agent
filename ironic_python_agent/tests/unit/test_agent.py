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

import socket
import time

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_serialization import jsonutils
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
from ironic_python_agent import netutils
from ironic_python_agent import utils

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
    def test_heartbeat(self, mock_uniform, mock_time, mock_poll, mock_read):
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
        mock_time.side_effect = time_responses
        mock_uniform.side_effect = uniform_responses
        self.mock_agent.heartbeat_timeout = 50
        self.heartbeater.api.heartbeat.side_effect = heartbeat_responses
        mock_poll.return_value.poll.side_effect = poll_responses
        self.heartbeater.run()

        # Validate expectations
        self.assertEqual(expected_poll_calls,
                         mock_poll.return_value.poll.call_args_list)
        self.assertEqual(2.7, self.heartbeater.error_delay)


@mock.patch.object(hardware.GenericHardwareManager, '_wait_for_disks',
                   lambda self: None)
class TestBaseAgent(test_base.BaseTestCase):

    def setUp(self):
        super(TestBaseAgent, self).setUp()
        self.encoder = encoding.RESTJSONEncoder(indent=4)

        self.agent = agent.IronicPythonAgent('https://fake_api.example.'
                                             'org:8081/',
                                             agent.Host('203.0.113.1', 9990),
                                             agent.Host('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             False)
        self.agent.ext_mgr = extension.ExtensionManager.\
            make_test_instance([extension.Extension('fake', None,
                                                    FakeExtension,
                                                    FakeExtension())])
        self.sample_nw_iface = hardware.NetworkInterface(
            "eth9", "AA:BB:CC:DD:EE:FF", "1.2.3.4", True)

    def assertEqualEncoded(self, a, b):
        # Evidently JSONEncoder.default() can't handle None (??) so we have to
        # use encode() to generate JSON, then json.loads() to get back a python
        # object.
        a_encoded = self.encoder.encode(a)
        b_encoded = self.encoder.encode(b)
        self.assertEqual(jsonutils.loads(a_encoded),
                         jsonutils.loads(b_encoded))

    def test_get_status(self):
        started_at = time.time()
        self.agent.started_at = started_at

        status = self.agent.get_status()
        self.assertIsInstance(status, agent.IronicPythonAgentStatus)
        self.assertEqual(started_at, status.started_at)
        self.assertEqual(pkg_resources.get_distribution('ironic-python-agent')
                         .version, status.version)

    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface')
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    def test_run(self, mock_make_server, mock_dispatch, mock_wait):
        CONF.set_override('inspection_callback_url', '', enforce_type=True)
        wsgi_server = mock_make_server.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        self.agent.run()

        listen_addr = agent.Host('192.0.2.1', 9999)
        mock_make_server.assert_called_once_with(
            listen_addr.hostname,
            listen_addr.port,
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()
        mock_wait.assert_called_once_with()
        mock_dispatch.assert_called_once_with("list_hardware_info")
        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface')
    @mock.patch.object(inspector, 'inspect', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run_with_inspection(self, mock_list_hardware, mock_make_server,
                                 mock_dispatch, mock_inspector, mock_wait):
        CONF.set_override('inspection_callback_url', 'http://foo/bar',
                          enforce_type=True)

        wsgi_server = mock_make_server.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        mock_inspector.return_value = 'uuid'

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300,
            }
        }
        self.agent.run()

        listen_addr = agent.Host('192.0.2.1', 9999)
        mock_make_server.assert_called_once_with(
            listen_addr.hostname,
            listen_addr.port,
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()
        mock_inspector.assert_called_once_with()
        self.assertEqual(1, self.agent.api_client.lookup_node.call_count)
        self.assertEqual(
            'uuid',
            self.agent.api_client.lookup_node.call_args[1]['node_uuid'])

        mock_wait.assert_called_once_with()
        mock_dispatch.assert_called_once_with("list_hardware_info")
        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface')
    @mock.patch.object(inspector, 'inspect', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run_with_inspection_without_apiurl(self,
                                                mock_list_hardware,
                                                mock_make_server,
                                                mock_dispatch,
                                                mock_inspector,
                                                mock_wait):
        # If inspection_callback_url is configured and api_url is not when the
        # agent starts, ensure that the inspection will be called and wsgi
        # server will work as usual. Also, make sure api_client and heartbeater
        # will not be initialized in this case.
        CONF.set_override('inspection_callback_url', 'http://foo/bar',
                          enforce_type=True)

        self.agent = agent.IronicPythonAgent(None,
                                             agent.Host('203.0.113.1', 9990),
                                             agent.Host('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             False)
        self.assertFalse(hasattr(self.agent, 'api_client'))
        self.assertFalse(hasattr(self.agent, 'heartbeater'))

        wsgi_server = mock_make_server.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.run()

        listen_addr = agent.Host('192.0.2.1', 9999)
        mock_make_server.assert_called_once_with(
            listen_addr.hostname,
            listen_addr.port,
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()
        mock_inspector.assert_called_once_with()

        self.assertFalse(mock_wait.called)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface')
    @mock.patch.object(inspector, 'inspect', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run_without_inspection_and_apiurl(self,
                                               mock_list_hardware,
                                               mock_make_server,
                                               mock_dispatch,
                                               mock_inspector,
                                               mock_wait):
        # If both api_url and inspection_callback_url are not configured when
        # the agent starts, ensure that the inspection will be skipped and wsgi
        # server will work as usual. Also, make sure api_client and heartbeater
        # will not be initialized in this case.
        CONF.set_override('inspection_callback_url', None,
                          enforce_type=True)

        self.agent = agent.IronicPythonAgent(None,
                                             agent.Host('203.0.113.1', 9990),
                                             agent.Host('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             False)
        self.assertFalse(hasattr(self.agent, 'api_client'))
        self.assertFalse(hasattr(self.agent, 'heartbeater'))

        wsgi_server = mock_make_server.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.run()

        listen_addr = agent.Host('192.0.2.1', 9999)
        mock_make_server.assert_called_once_with(
            listen_addr.hostname,
            listen_addr.port,
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()

        self.assertFalse(mock_inspector.called)
        self.assertFalse(mock_wait.called)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(time, 'time', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test__wait_for_interface(self, mock_dispatch, mock_sleep, mock_time):
        mock_dispatch.return_value = [self.sample_nw_iface, {}]
        mock_time.return_value = 10
        self.agent._wait_for_interface()
        mock_dispatch.assert_called_once_with('list_network_interfaces')
        self.assertFalse(mock_sleep.called)

    @mock.patch.object(time, 'time', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test__wait_for_interface_expired(self, mock_dispatch, mock_sleep,
                                         mock_time):
        mock_time.side_effect = [10, 11, 20, 25, 30]
        mock_dispatch.side_effect = [[], [], [self.sample_nw_iface], {}]
        expected_sleep_calls = [mock.call(agent.NETWORK_WAIT_RETRY)] * 2
        expected_dispatch_calls = [mock.call("list_network_interfaces")] * 3
        self.agent._wait_for_interface()
        mock_dispatch.assert_has_calls(expected_dispatch_calls)
        mock_sleep.assert_has_calls(expected_sleep_calls)

    @mock.patch('ironic_python_agent.hardware_managers.cna._detect_cna_card',
                autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent, '_wait_for_interface',
                       autospec=True)
    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware, '_check_for_iscsi', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run_with_sleep(self, mock_check_for_iscsi, mock_list_hardware,
                            mock_make_server, mock_wait, mock_sleep,
                            mock_cna):
        CONF.set_override('inspection_callback_url', '', enforce_type=True)
        wsgi_server = mock_make_server.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.hardware_initialization_delay = 10
        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        mock_cna.return_value = False
        self.agent.run()

        listen_addr = agent.Host('192.0.2.1', 9999)
        mock_make_server.assert_called_once_with(
            listen_addr.hostname,
            listen_addr.port,
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()

        self.agent.heartbeater.start.assert_called_once_with()
        mock_sleep.assert_called_once_with(10)
        self.assertTrue(mock_check_for_iscsi.called)

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
        self.assertEqualEncoded(expected_result, result)

        result.start()
        result.join()

        expected_result['command_status'] = 'SUCCEEDED'
        expected_result['command_result'] = {'result': ('foo_command: command '
                                                        'execution succeeded')}

        self.assertEqualEncoded(expected_result, result)

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
        self.assertEqualEncoded(expected_result, result)

        result.start()
        result.join()

        expected_result['command_status'] = 'FAILED'
        expected_result['command_error'] = errors.CommandExecutionError(
            str(EXPECTED_ERROR))

        self.assertEqualEncoded(expected_result, result)

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

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_route_source_ipv4(self, mock_execute):
        mock_execute.return_value = ('XXX src 1.2.3.4 XXX\n    cache', None)

        source = self.agent._get_route_source('XXX')
        self.assertEqual('1.2.3.4', source)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_route_source_ipv6(self, mock_execute):
        mock_execute.return_value = ('XXX src 1:2::3:4 metric XXX\n    cache',
                                     None)

        source = self.agent._get_route_source('XXX')
        self.assertEqual('1:2::3:4', source)

    @mock.patch.object(agent, 'LOG', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_route_source_indexerror(self, mock_execute, mock_log):
        mock_execute.return_value = ('XXX src \n    cache', None)

        source = self.agent._get_route_source('XXX')
        self.assertIsNone(source)
        mock_log.warning.assert_called_once()


@mock.patch.object(hardware.GenericHardwareManager, '_wait_for_disks',
                   lambda self: None)
class TestAgentStandalone(test_base.BaseTestCase):

    def setUp(self):
        super(TestAgentStandalone, self).setUp()
        self.agent = agent.IronicPythonAgent('https://fake_api.example.'
                                             'org:8081/',
                                             agent.Host(hostname='203.0.113.1',
                                                        port=9990),
                                             agent.Host(hostname='192.0.2.1',
                                                        port=9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             'agent_ipmitool',
                                             True)

    @mock.patch('wsgiref.simple_server.make_server', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info')
    def test_run(self, mock_list_hardware, mock_make_server):
        wsgi_server = mock_make_server.return_value
        wsgi_server.start.side_effect = KeyboardInterrupt()

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        self.agent.run()

        listen_addr = agent.Host('192.0.2.1', 9999)
        mock_make_server.assert_called_once_with(
            listen_addr.hostname,
            listen_addr.port,
            self.agent.api,
            server_class=simple_server.WSGIServer)
        wsgi_server.serve_forever.assert_called_once_with()

        self.assertFalse(self.agent.heartbeater.called)
        self.assertFalse(self.agent.api_client.lookup_node.called)


@mock.patch.object(hardware, '_check_for_iscsi', lambda: None)
@mock.patch.object(hardware.GenericHardwareManager, '_wait_for_disks',
                   lambda self: None)
@mock.patch.object(socket, 'gethostbyname', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
class TestAdvertiseAddress(test_base.BaseTestCase):
    def setUp(self):
        super(TestAdvertiseAddress, self).setUp()

        self.agent = agent.IronicPythonAgent(
            api_url='https://fake_api.example.org:8081/',
            advertise_address=agent.Host(None, 9990),
            listen_address=agent.Host('0.0.0.0', 9999),
            ip_lookup_attempts=5,
            ip_lookup_sleep=10,
            network_interface=None,
            lookup_timeout=300,
            lookup_interval=1,
            standalone=False)

    def test_advertise_address_provided(self, mock_exec, mock_gethostbyname):
        self.agent.advertise_address = agent.Host('1.2.3.4', 9990)

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('1.2.3.4', 9990), self.agent.advertise_address)
        self.assertFalse(mock_exec.called)
        self.assertFalse(mock_gethostbyname.called)

    @mock.patch.object(netutils, 'get_ipv4_addr',
                       autospec=True)
    @mock.patch('ironic_python_agent.hardware_managers.cna._detect_cna_card',
                autospec=True)
    def test_with_network_interface(self, mock_cna, mock_get_ipv4, mock_exec,
                                    mock_gethostbyname):
        self.agent.network_interface = 'em1'
        mock_get_ipv4.return_value = '1.2.3.4'
        mock_cna.return_value = False

        self.agent.set_agent_advertise_addr()

        self.assertEqual(agent.Host('1.2.3.4', 9990),
                         self.agent.advertise_address)
        mock_get_ipv4.assert_called_once_with('em1')
        self.assertFalse(mock_exec.called)
        self.assertFalse(mock_gethostbyname.called)

    @mock.patch.object(netutils, 'get_ipv4_addr',
                       autospec=True)
    @mock.patch('ironic_python_agent.hardware_managers.cna._detect_cna_card',
                autospec=True)
    def test_with_network_interface_failed(self, mock_cna, mock_get_ipv4,
                                           mock_exec, mock_gethostbyname):
        self.agent.network_interface = 'em1'
        mock_get_ipv4.return_value = None
        mock_cna.return_value = False

        self.assertRaises(errors.LookupAgentIPError,
                          self.agent.set_agent_advertise_addr)

        mock_get_ipv4.assert_called_once_with('em1')
        self.assertFalse(mock_exec.called)
        self.assertFalse(mock_gethostbyname.called)

    def test_route_with_ip(self, mock_exec, mock_gethostbyname):
        self.agent.api_url = 'http://1.2.1.2:8081/v1'
        mock_gethostbyname.side_effect = socket.gaierror()
        mock_exec.return_value = (
            """1.2.1.2 via 192.168.122.1 dev eth0  src 192.168.122.56
                cache """,
            ""
        )

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('192.168.122.56', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_once_with('ip', 'route', 'get', '1.2.1.2')
        mock_gethostbyname.assert_called_once_with('1.2.1.2')

    def test_route_with_ipv6(self, mock_exec, mock_gethostbyname):
        self.agent.api_url = 'http://[fc00:1111::1]:8081/v1'
        mock_gethostbyname.side_effect = socket.gaierror()
        mock_exec.return_value = (
            """fc00:101::1 dev br-ctlplane  src fc00:101::4  metric 0
                cache """,
            ""
        )

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('fc00:101::4', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_once_with('ip', 'route', 'get', 'fc00:1111::1')
        mock_gethostbyname.assert_called_once_with('fc00:1111::1')

    def test_route_with_host(self, mock_exec, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.1.2'
        mock_exec.return_value = (
            """1.2.1.2 via 192.168.122.1 dev eth0  src 192.168.122.56
                cache """,
            ""
        )

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('192.168.122.56', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_once_with('ip', 'route', 'get', '1.2.1.2')
        mock_gethostbyname.assert_called_once_with('fake_api.example.org')

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_route_retry(self, mock_sleep, mock_exec, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.1.2'
        mock_exec.side_effect = [
            processutils.ProcessExecutionError('boom'),
            (
                "Error: some error text",
                ""
            ),
            (
                """1.2.1.2 via 192.168.122.1 dev eth0  src 192.168.122.56
                    cache """,
                ""
            )
        ]

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('192.168.122.56', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_with('ip', 'route', 'get', '1.2.1.2')
        mock_gethostbyname.assert_called_once_with('fake_api.example.org')
        mock_sleep.assert_called_with(10)
        self.assertEqual(3, mock_exec.call_count)
        self.assertEqual(2, mock_sleep.call_count)

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_route_failed(self, mock_sleep, mock_exec, mock_gethostbyname):
        mock_gethostbyname.return_value = '1.2.1.2'
        mock_exec.side_effect = processutils.ProcessExecutionError('boom')

        self.assertRaises(errors.LookupAgentIPError,
                          self.agent.set_agent_advertise_addr)

        mock_exec.assert_called_with('ip', 'route', 'get', '1.2.1.2')
        mock_gethostbyname.assert_called_once_with('fake_api.example.org')
        self.assertEqual(5, mock_exec.call_count)
        self.assertEqual(5, mock_sleep.call_count)

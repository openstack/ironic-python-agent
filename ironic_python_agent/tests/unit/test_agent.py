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

import importlib.metadata
import json
import socket
import time
from unittest import mock
from unittest.mock import sentinel

from oslo_concurrency import processutils
from oslo_config import cfg
import requests
from stevedore import extension

from ironic_python_agent import agent
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import inspector
from ironic_python_agent import netutils
from ironic_python_agent.tests.unit import base as ironic_agent_base
from ironic_python_agent import tls_utils
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


class FakeClock:
    current = 0
    last_wait = None
    wait_result = False

    def get(self):
        return self.current

    def wait(self, interval):
        self.last_wait = interval
        self.current += interval
        return self.wait_result


class TestHeartbeater(ironic_agent_base.IronicAgentTest):
    def setUp(self):
        super(TestHeartbeater, self).setUp()
        self.mock_agent = mock.Mock()
        self.mock_agent.api_url = 'https://fake_api.example.org:8081/'
        self.heartbeater = agent.IronicPythonAgentHeartbeater(self.mock_agent)
        self.heartbeater.api = mock.Mock()
        self.heartbeater.hardware = mock.create_autospec(
            hardware.HardwareManager)
        self.heartbeater.stop_event = mock.Mock()

    @mock.patch('ironic_python_agent.agent._time', autospec=True)
    @mock.patch('random.uniform', autospec=True)
    def test_heartbeat(self, mock_uniform, mock_time):
        clock = FakeClock()
        mock_time.side_effect = clock.get
        self.heartbeater.stop_event.wait.side_effect = clock.wait

        heartbeat_mock = self.heartbeater.api.heartbeat
        self.mock_agent.heartbeat_timeout = 20

        # First run right after start
        mock_uniform.return_value = 0.6
        self.assertTrue(self.heartbeater._run_next())
        self.assertEqual(0, clock.last_wait)
        heartbeat_mock.assert_called_once_with(
            uuid=self.mock_agent.get_node_uuid.return_value,
            advertise_address=self.mock_agent.advertise_address,
            advertise_protocol=self.mock_agent.advertise_protocol,
            generated_cert=self.mock_agent.generated_cert)
        heartbeat_mock.reset_mock()
        self.assertEqual(12, self.heartbeater.interval)  # 20*0.6
        self.assertEqual(0, self.heartbeater.previous_heartbeat)

        # A few empty runs before reaching the next heartbeat
        for ts in [5, 10]:
            self.assertTrue(self.heartbeater._run_next())
            self.assertEqual(5, clock.last_wait)
            self.assertEqual(ts, clock.current)
            heartbeat_mock.assert_not_called()
            self.assertEqual(0, self.heartbeater.previous_heartbeat)

        # Second run when the heartbeat is due
        mock_uniform.return_value = 0.4
        self.assertTrue(self.heartbeater._run_next())
        self.assertEqual(2, clock.last_wait)  # 12-2*5
        self.assertTrue(heartbeat_mock.called)
        heartbeat_mock.reset_mock()
        self.assertEqual(8, self.heartbeater.interval)  # 20*0.4
        self.assertEqual(12, self.heartbeater.previous_heartbeat)

        # One empty run before reaching the next heartbeat
        self.assertTrue(self.heartbeater._run_next())
        self.assertEqual(5, clock.last_wait)
        heartbeat_mock.assert_not_called()
        self.assertEqual(12, self.heartbeater.previous_heartbeat)

        # Failed run resulting in a fast retry
        mock_uniform.return_value = 1.2
        heartbeat_mock.side_effect = Exception('uh oh!')
        self.assertTrue(self.heartbeater._run_next())
        self.assertEqual(3, clock.last_wait)  # 8-5
        self.assertTrue(heartbeat_mock.called)
        heartbeat_mock.reset_mock(side_effect=True)
        self.assertEqual(6, self.heartbeater.interval)  # 5*1.2
        self.assertEqual(20, self.heartbeater.previous_heartbeat)

        # One empty run because 6>5
        self.assertTrue(self.heartbeater._run_next())
        self.assertEqual(5, clock.last_wait)
        heartbeat_mock.assert_not_called()
        self.assertEqual(20, self.heartbeater.previous_heartbeat)

        # Retry after the remaining 1 second
        mock_uniform.return_value = 0.5
        self.assertTrue(self.heartbeater._run_next())
        self.assertEqual(1, clock.last_wait)
        self.assertTrue(heartbeat_mock.called)
        heartbeat_mock.reset_mock()
        self.assertEqual(10, self.heartbeater.interval)  # 20*0.5
        self.assertEqual(26, self.heartbeater.previous_heartbeat)

        # Stop on the next empty run
        clock.wait_result = True
        self.assertFalse(self.heartbeater._run_next())
        heartbeat_mock.assert_not_called()
        self.assertEqual(26, self.heartbeater.previous_heartbeat)

    @mock.patch('ironic_python_agent.agent._time', autospec=True)
    def test__heartbeat_expected(self, mock_time):

        # initial setting
        self.heartbeater.previous_heartbeat = 0
        self.heartbeater.interval = 0
        self.heartbeater.heartbeat_forced = False
        mock_time.return_value = 0
        self.assertTrue(self.heartbeater._heartbeat_expected())

        # 1st cadence
        self.heartbeater.previous_heartbeat = 0
        self.heartbeater.interval = 100
        self.heartbeater.heartbeat_forced = False
        mock_time.return_value = 5
        self.assertFalse(self.heartbeater._heartbeat_expected())

        # 2nd cadence with a forced heartbeat
        self.heartbeater.previous_heartbeat = 0
        self.heartbeater.interval = 100
        self.heartbeater.heartbeat_forced = True
        mock_time.return_value = 10
        self.assertTrue(self.heartbeater._heartbeat_expected())

        # 11th cadence with a scheduled heartbeat
        self.heartbeater.previous_heartbeat = 0
        self.heartbeater.interval = 100
        self.heartbeater.heartbeat_forced = False
        mock_time.return_value = 110
        self.assertTrue(self.heartbeater._heartbeat_expected())

    def test_stop_not_started(self):
        """Test stop() when thread was never started."""
        # Thread is not alive, should not call join()
        self.assertFalse(self.heartbeater.is_alive())
        result = self.heartbeater.stop()
        self.assertIsNone(result)
        self.assertTrue(self.heartbeater.stop_event.set.called)

    @mock.patch.object(agent.IronicPythonAgentHeartbeater, 'join',
                       autospec=True)
    def test_stop_when_alive(self, mock_join):
        """Test stop() when thread is alive."""
        # Mock the thread as alive
        with mock.patch.object(self.heartbeater, 'is_alive',
                               autospec=True, return_value=True):
            self.heartbeater.stop()
            mock_join.assert_called_once_with(self.heartbeater)
            self.assertTrue(self.heartbeater.stop_event.set.called)


@mock.patch.object(hardware, '_md_scan_and_assemble', lambda: None)
@mock.patch.object(hardware, '_check_for_iscsi', lambda: None)
@mock.patch.object(hardware, '_load_ipmi_modules', lambda: None)
@mock.patch.object(hardware.GenericHardwareManager, 'wait_for_disks',
                   lambda self: None)
class TestBaseAgent(ironic_agent_base.IronicAgentTest):

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
                                             False,
                                             None)
        self.agent.ext_mgr = extension.ExtensionManager.\
            make_test_instance([extension.Extension('fake', None,
                                                    FakeExtension,
                                                    FakeExtension())])
        self.sample_nw_iface = hardware.NetworkInterface(
            "eth9", "AA:BB:CC:DD:EE:FF", "1.2.3.4", True)
        hardware.NODE = None

    def assertEqualEncoded(self, a, b):
        # Evidently JSONEncoder.default() can't handle None (??) so we have to
        # use encode() to generate JSON, then json.loads() to get back a python
        # object.
        a_encoded = self.encoder.encode(a)
        b_encoded = self.encoder.encode(b)
        self.assertEqual(json.loads(a_encoded),
                         json.loads(b_encoded))

    def test_get_status(self):
        started_at = time.time()
        self.agent.started_at = started_at

        status = self.agent.get_status()
        self.assertIsInstance(status, agent.IronicPythonAgentStatus)
        self.assertEqual(started_at, status.started_at)
        self.assertEqual(importlib.metadata.version('ironic-python-agent'),
                         status.version)

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run(self, mock_get_managers, mock_wait, mock_dispatch):
        CONF.set_override('inspection_callback_url', '')

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300,
                'agent_md5_checksum_enable': False
            }
        }

        self.agent.run()

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()
        self.assertFalse(CONF.md5_enabled)

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run_with_ssl(self, mock_get_managers,
                          mock_wait, mock_dispatch):
        CONF.set_override('inspection_callback_url', '')
        CONF.set_override('listen_tls', True)
        CONF.set_override('md5_enabled', False)

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300,
                'agent_md5_checksum_enable': True
            }
        }

        self.agent.run()

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()
        self.assertTrue(CONF.md5_enabled)

    @mock.patch('ironic_python_agent.mdns.get_endpoint', autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_url_from_mdns_by_default(self, mock_get_managers,
                                      mock_wait, mock_dispatch, mock_mdns):
        CONF.set_override('inspection_callback_url', '')
        mock_mdns.return_value = 'https://example.com', {}

        self.agent = agent.IronicPythonAgent(None,
                                             agent.Host('203.0.113.1', 9990),
                                             agent.Host('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             False,
                                             None)

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
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

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch('ironic_python_agent.mdns.get_endpoint', autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_url_from_mdns_explicitly(self, mock_get_managers,
                                      mock_wait, mock_dispatch, mock_mdns):
        CONF.set_override('inspection_callback_url', '')
        CONF.set_override('disk_wait_attempts', 0)
        mock_mdns.return_value = 'https://example.com', {
            # configuration via mdns
            'ipa_disk_wait_attempts': '42',
        }

        self.agent = agent.IronicPythonAgent('mdns',
                                             agent.Host('203.0.113.1', 9990),
                                             agent.Host('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             False,
                                             None)

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
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

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()
        # changed via mdns
        self.assertEqual(42, CONF.disk_wait_attempts)

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run_agent_token(self, mock_get_managers,
                             mock_wait, mock_dispatch):
        CONF.set_override('inspection_callback_url', '')

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300,
                'agent_token': '1' * 128,
            }
        }

        self.agent.run()

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()
        self.assertEqual('1' * 128, self.agent.agent_token)
        self.assertEqual('1' * 128, self.agent.api_client.agent_token)

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run_listen_host_port(self, mock_get_managers,
                                  mock_wait, mock_dispatch):
        CONF.set_override('inspection_callback_url', '')

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
        self.agent.heartbeater = mock.Mock()
        self.agent.listen_address = mock.Mock()
        self.agent.listen_address.hostname = '2001:db8:dead:beef::cafe'
        self.agent.listen_address.port = 9998
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

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch('time.sleep', autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run_raise_keyboard_interrupt(self, mock_get_managers,
                                          mock_dispatch, mock_wait,
                                          mock_sleep):
        CONF.set_override('inspection_callback_url', '')
        mock_sleep.side_effect = KeyboardInterrupt()
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

        self.agent.api.start = mock.Mock()

        self.agent.run()

        self.assertTrue(mock_wait.called)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch.object(hardware, '_enable_multipath', autospec=True)
    @mock.patch('ironic_python_agent.hardware_managers.cna._detect_cna_card',
                mock.Mock())
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(inspector, 'inspect', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info',
                       autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.container.'
        'ContainerHardwareManager.evaluate_hardware_support',
        autospec=True
    )
    def test_run_with_inspection(self, mock_hardware, mock_list_hardware,
                                 mock_dispatch, mock_inspector,
                                 mock_wait, mock_mpath):
        CONF.set_override('inspection_callback_url', 'http://foo/bar')
        mock_hardware.return_value = 0

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False
        self.agent.api.start = mock.Mock(side_effect=set_serve_api)

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

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)

        mock_inspector.assert_called_once_with()
        self.assertEqual(1, self.agent.api_client.lookup_node.call_count)
        self.assertEqual(
            'uuid',
            self.agent.api_client.lookup_node.call_args[1]['node_uuid'])

        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch.object(hardware, '_enable_multipath', autospec=True)
    @mock.patch('ironic_python_agent.mdns.get_endpoint', autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(inspector, 'inspect', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info',
                       autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.container.'
        'ContainerHardwareManager.evaluate_hardware_support',
        autospec=True
    )
    def test_run_with_inspection_without_apiurl(self,
                                                mock_hardware,
                                                mock_list_hardware,
                                                mock_dispatch,
                                                mock_inspector,
                                                mock_wait,
                                                mock_mdns,
                                                mock_mpath):
        mock_mdns.side_effect = errors.ServiceLookupFailure()
        # If inspection_callback_url is configured and api_url is not when the
        # agent starts, ensure that the inspection will be called and wsgi
        # server will work as usual. Also, make sure api_client and heartbeater
        # will not be initialized in this case.
        CONF.set_override('inspection_callback_url', 'http://foo/bar')
        mock_hardware.return_value = 0

        self.agent = agent.IronicPythonAgent(None,
                                             agent.Host('203.0.113.1', 9990),
                                             agent.Host('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             False,
                                             None)
        self.assertFalse(hasattr(self.agent, 'api_client'))
        self.assertFalse(hasattr(self.agent, 'heartbeater'))

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False
        self.agent.api.start = mock.Mock(side_effect=set_serve_api)

        self.agent.run()

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)

        mock_inspector.assert_called_once_with()

        self.assertTrue(mock_wait.called)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(hardware, '_enable_multipath', autospec=True)
    @mock.patch('ironic_python_agent.mdns.get_endpoint', autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(inspector, 'inspect', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info',
                       autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.container.'
        'ContainerHardwareManager.evaluate_hardware_support',
        autospec=True
    )
    def test_run_without_inspection_and_apiurl(self,
                                               mock_hardware,
                                               mock_list_hardware,
                                               mock_dispatch,
                                               mock_inspector,
                                               mock_wait,
                                               mock_mdns,
                                               mock_mpath):
        mock_mdns.side_effect = errors.ServiceLookupFailure()
        mock_hardware.return_value = 0
        # If both api_url and inspection_callback_url are not configured when
        # the agent starts, ensure that the inspection will be skipped and wsgi
        # server will work as usual. Also, make sure api_client and heartbeater
        # will not be initialized in this case.
        CONF.set_override('inspection_callback_url', None)

        self.agent = agent.IronicPythonAgent(None,
                                             agent.Host('203.0.113.1', 9990),
                                             agent.Host('192.0.2.1', 9999),
                                             3,
                                             10,
                                             'eth0',
                                             300,
                                             1,
                                             False,
                                             None)
        self.assertFalse(hasattr(self.agent, 'api_client'))
        self.assertFalse(hasattr(self.agent, 'heartbeater'))

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False
        self.agent.api.start = mock.Mock(side_effect=set_serve_api)

        self.agent.run()

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)

        self.assertFalse(mock_inspector.called)
        self.assertTrue(mock_wait.called)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(netutils, 'list_interfaces', autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run_then_lockdown(self, mock_get_managers,
                               mock_wait, mock_dispatch, mock_interfaces,
                               mock_exec, mock_sleep):
        CONF.set_override('inspection_callback_url', '')

        def set_serve_api(*args, **kwargs):
            self.agent.lockdown = True
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300,
                'agent_md5_checksum_enable': False
            }
        }
        mock_interfaces.return_value = ['em1', 'em2']

        class StopTesting(Exception):
            """Exception to exit the infinite loop."""

        mock_sleep.side_effect = StopTesting

        self.assertRaises(StopTesting, self.agent.run)

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()
        self.agent.heartbeater.stop.assert_called_once_with()
        mock_exec.assert_has_calls([
            mock.call('ip', 'link', 'set', iface, 'down')
            for iface in ['em1', 'em2']
        ])

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

    @mock.patch.object(hardware, 'get_managers', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent, '_wait_for_interface',
                       autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test_run_with_sleep(self, mock_dispatch,
                            mock_wait, mock_sleep, mock_get_managers):
        CONF.set_override('inspection_callback_url', '')

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False
        self.agent.api.start = mock.Mock(side_effect=set_serve_api)

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
        self.agent.run()

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)

        self.agent.heartbeater.start.assert_called_once_with()
        mock_sleep.assert_called_once_with(10)
        self.assertTrue(mock_get_managers.called)
        self.assertTrue(mock_wait.called)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch('os.path.exists', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent, '_wait_for_interface',
                       autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test_run_rescue_mode_heartbeater_not_started(
            self, mock_dispatch, mock_wait, mock_sleep, mock_get_managers,
            mock_exists):
        """Test rescue mode doesn't fail when heartbeater not started."""
        CONF.set_override('inspection_callback_url', '')

        # Mock rescue mode marker file exists
        mock_exists.return_value = True

        self.agent.heartbeater = mock.Mock()
        self.agent.heartbeater.is_alive.return_value = False
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }

        # Setup to exit the infinite loop after first iteration
        mock_sleep.side_effect = [None, KeyboardInterrupt()]

        try:
            self.agent.run()
        except KeyboardInterrupt:
            pass

        # Heartbeater should not be started or stopped in rescue mode
        self.agent.heartbeater.start.assert_not_called()
        self.agent.heartbeater.stop.assert_not_called()
        self.assertFalse(self.agent.serve_api)

    def test_async_command_success(self):
        result = base.AsyncCommandResult('foo_command', {'fail': False},
                                         foo_execute)
        expected_result = {
            'id': result.id,
            'command_name': 'foo_command',
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

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_route_source_ipv6_linklocal(self, mock_execute):
        mock_execute.return_value = (
            'XXX src fe80::1234:1234:1234:1234 metric XXX\n    cache', None)

        source = self.agent._get_route_source('XXX')
        self.assertIsNone(source)

    @mock.patch.object(agent, 'LOG', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_route_source_indexerror(self, mock_execute, mock_log):
        mock_execute.return_value = ('XXX src \n    cache', None)

        source = self.agent._get_route_source('XXX')
        self.assertIsNone(source)
        mock_log.warning.assert_called_once()

    @mock.patch('requests.get', autospec=True)
    def test_test_ip_reachability_success(self, mock_get):
        """Test _test_ip_reachability with successful HTTP response."""
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = self.agent._test_ip_reachability('http://192.168.1.1:6385/v1')
        self.assertTrue(result)
        mock_get.assert_called_once_with('http://192.168.1.1:6385/v1',
                                         timeout=30, verify=False)

    @mock.patch('requests.get', autospec=True)
    def test_test_ip_reachability_https_success(self, mock_get):
        """Test _test_ip_reachability with HTTPS URL."""
        mock_response = mock.Mock()
        mock_response.status_code = 404  # Any status code is acceptable
        mock_get.return_value = mock_response

        result = self.agent._test_ip_reachability(
            'https://192.168.1.1:6385/v1')
        self.assertTrue(result)
        mock_get.assert_called_once_with('https://192.168.1.1:6385/v1',
                                         timeout=30, verify=False)

    @mock.patch('requests.get', autospec=True)
    def test_test_ip_reachability_failure(self, mock_get):
        """Test _test_ip_reachability with connection failure."""
        mock_get.side_effect = requests.exceptions.ConnectionError(
            'Connection failed')

        result = self.agent._test_ip_reachability('http://192.168.1.1:6385/v1')
        self.assertFalse(result)
        mock_get.assert_called_once_with('http://192.168.1.1:6385/v1',
                                         timeout=30, verify=False)

    @mock.patch('requests.get', autospec=True)
    @mock.patch.object(socket, 'getaddrinfo', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_find_routable_addr_filters_api_urls(self, mock_exec,
                                                 mock_getaddrinfo,
                                                 mock_requests_get):
        """Test that _find_routable_addr filters unreachable API URLs."""
        # Set up multiple API URLs - some reachable, some not
        self.agent.api_urls = [
            'http://reachable1.example.com:8081/v1',
            'http://unreachable.example.com:8081/v1',
            'http://reachable2.example.com:8081/v1'
        ]

        # Mock reachability tests - only reachable1 and reachable2 are
        # reachable
        def mock_reachability_side_effect(url, **kwargs):
            mock_response = mock.Mock()
            mock_response.status_code = 200
            if 'reachable1' in url or 'reachable2' in url:
                return mock_response
            else:
                raise requests.exceptions.ConnectionError('Connection failed')

        mock_requests_get.side_effect = mock_reachability_side_effect

        # Mock DNS resolution for reachable hosts
        mock_getaddrinfo.return_value = [
            (sentinel.a, sentinel.b, sentinel.c, sentinel.d,
             ('192.168.1.1', sentinel.e)),
        ]

        # Mock successful route lookup
        mock_exec.return_value = (
            """192.168.1.1 via 192.168.122.1 dev eth0  src 192.168.122.56
                cache """,
            ""
        )

        result = self.agent._find_routable_addr()

        # Should return the found IP
        self.assertEqual('192.168.122.56', result)

        # Should have filtered API URLs to only include reachable ones
        self.assertEqual(2, len(self.agent.api_urls))
        self.assertIn('http://reachable1.example.com:8081/v1',
                      self.agent.api_urls)
        self.assertIn('http://reachable2.example.com:8081/v1',
                      self.agent.api_urls)
        self.assertNotIn('http://unreachable.example.com:8081/v1',
                         self.agent.api_urls)

    @mock.patch('requests.get', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_find_routable_addr_no_reachable_urls(self, mock_exec,
                                                  mock_requests_get):
        """Test _find_routable_addr when no API URLs are reachable."""
        # Set up API URLs that are all unreachable
        self.agent.api_urls = [
            'http://unreachable1.example.com:8081/v1',
            'http://unreachable2.example.com:8081/v1'
        ]

        # Mock all reachability tests to fail
        mock_requests_get.side_effect = requests.exceptions.ConnectionError(
            'Connection failed')

        # Mock execute to raise an exception (no route found)
        mock_exec.side_effect = processutils.ProcessExecutionError('No route')

        # Should keep original URLs with warning
        original_urls = self.agent.api_urls.copy()
        result = self.agent._find_routable_addr()

        # Should return None (no routable address found)
        self.assertIsNone(result)

        # Should keep original URLs when none are reachable
        self.assertEqual(original_urls, self.agent.api_urls)


@mock.patch.object(hardware, '_md_scan_and_assemble', lambda: None)
@mock.patch.object(hardware, '_check_for_iscsi', lambda: None)
@mock.patch.object(hardware.GenericHardwareManager, 'wait_for_disks',
                   lambda self: None)
class TestAgentStandalone(ironic_agent_base.IronicAgentTest):

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
                                             None,
                                             True)

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info',
                       autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run(self, mock_get_managers, mock_list_hardware,
                 mock_dispatch):

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)

        mock_dispatch.return_value = tls_utils.TlsCertificate(
            'I am a cert', '/path/to/cert', '/path/to/key')

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()

        self.agent.run()

        self.assertTrue(mock_get_managers.called)
        self.agent.api.start.assert_called_once_with(
            '/path/to/cert', '/path/to/key')
        mock_dispatch.assert_called_once_with('generate_tls_certificate',
                                              mock.ANY)

        self.assertEqual('https', self.agent.advertise_protocol)

        self.assertFalse(self.agent.heartbeater.called)
        self.assertFalse(self.agent.api_client.lookup_node.called)

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware.HardwareManager, 'list_hardware_info',
                       autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run_no_tls(self, mock_get_managers, mock_list_hardware):
        CONF.set_override('enable_auto_tls', False)

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)

        self.agent.heartbeater = mock.Mock()
        self.agent.api_client = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()

        self.agent.run()

        self.assertTrue(mock_get_managers.called)
        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual('http', self.agent.advertise_protocol)

        self.assertFalse(self.agent.heartbeater.called)
        self.assertFalse(self.agent.api_client.lookup_node.called)


@mock.patch.object(hardware, '_md_scan_and_assemble', lambda: None)
@mock.patch.object(hardware, '_check_for_iscsi', lambda: None)
@mock.patch.object(hardware, '_load_ipmi_modules', lambda: None)
@mock.patch.object(hardware.GenericHardwareManager, 'wait_for_disks',
                   lambda self: None)
@mock.patch('requests.get', autospec=True)
@mock.patch.object(socket, 'getaddrinfo', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
class TestAdvertiseAddress(ironic_agent_base.IronicAgentTest):
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
            agent_token=None,
            standalone=False)

    def test_advertise_address_provided(self, mock_exec, mock_getaddrinfo,
                                        mock_requests_get):
        self.agent.advertise_address = agent.Host('1.2.3.4', 9990)

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('1.2.3.4', 9990), self.agent.advertise_address)
        self.assertFalse(mock_exec.called)
        self.assertFalse(mock_getaddrinfo.called)

    @mock.patch.object(hardware, '_enable_multipath', autospec=True)
    @mock.patch.object(netutils, 'get_ipv4_addr',
                       autospec=True)
    @mock.patch('ironic_python_agent.hardware_managers.cna._detect_cna_card',
                autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.container.'
        'ContainerHardwareManager.evaluate_hardware_support',
        autospec=True
    )
    def test_with_network_interface(self, mock_hardware, mock_cna,
                                    mock_get_ipv4, mock_mpath,
                                    mock_exec, mock_getaddrinfo,
                                    mock_requests_get):
        self.agent.network_interface = 'em1'
        mock_get_ipv4.return_value = '1.2.3.4'
        mock_cna.return_value = False
        mock_hardware.return_value = 0

        self.agent.set_agent_advertise_addr()

        self.assertEqual(agent.Host('1.2.3.4', 9990),
                         self.agent.advertise_address)
        mock_get_ipv4.assert_called_once_with('em1')
        self.assertFalse(mock_exec.called)
        self.assertFalse(mock_getaddrinfo.called)

    @mock.patch.object(hardware, '_enable_multipath', autospec=True)
    @mock.patch.object(netutils, 'get_ipv4_addr',
                       autospec=True)
    @mock.patch('ironic_python_agent.hardware_managers.cna._detect_cna_card',
                autospec=True)
    @mock.patch(
        'ironic_python_agent.hardware_managers.container.'
        'ContainerHardwareManager.evaluate_hardware_support',
        autospec=True
    )
    def test_with_network_interface_failed(self, mock_hardware,
                                           mock_cna, mock_get_ipv4,
                                           mock_mpath, mock_exec,
                                           mock_getaddrinfo,
                                           mock_requests_get):
        self.agent.network_interface = 'em1'
        mock_get_ipv4.return_value = None
        mock_cna.return_value = False
        mock_hardware.return_value = 0

        self.assertRaises(errors.LookupAgentIPError,
                          self.agent.set_agent_advertise_addr)

        mock_get_ipv4.assert_called_once_with('em1')
        self.assertFalse(mock_exec.called)
        self.assertFalse(mock_getaddrinfo.called)

    def test_route_with_ip(self, mock_exec, mock_getaddrinfo,
                           mock_requests_get):
        self.agent.api_urls = ['http://1.2.1.2:8081/v1']
        mock_getaddrinfo.side_effect = socket.gaierror()
        mock_exec.return_value = (
            """1.2.1.2 via 192.168.122.1 dev eth0  src 192.168.122.56
                cache """,
            ""
        )
        # Mock successful HTTP reachability test
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_requests_get.return_value = mock_response

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('192.168.122.56', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_once_with('ip', 'route', 'get', '1.2.1.2')
        mock_getaddrinfo.assert_called_once_with('1.2.1.2', 0)

    def test_route_with_ipv6(self, mock_exec, mock_getaddrinfo,
                             mock_requests_get):
        self.agent.api_urls = ['http://[fc00:1111::1]:8081/v1']
        mock_getaddrinfo.side_effect = socket.gaierror()
        mock_exec.return_value = (
            """fc00:101::1 dev br-ctlplane  src fc00:101::4  metric 0
                cache """,
            ""
        )
        # Mock successful HTTP reachability test
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_requests_get.return_value = mock_response

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('fc00:101::4', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_once_with('ip', 'route', 'get', 'fc00:1111::1')
        mock_getaddrinfo.assert_called_once_with('fc00:1111::1', 0)

    def test_route_with_host(self, mock_exec, mock_getaddrinfo,
                             mock_requests_get):
        mock_getaddrinfo.return_value = [
            (sentinel.a, sentinel.b, sentinel.c, sentinel.d,
             ('1.2.1.2', sentinel.e)),
        ]
        mock_exec.return_value = (
            """1.2.1.2 via 192.168.122.1 dev eth0  src 192.168.122.56
                cache """,
            ""
        )
        # Mock successful HTTP reachability test
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_requests_get.return_value = mock_response

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('192.168.122.56', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_once_with('ip', 'route', 'get', '1.2.1.2')
        mock_getaddrinfo.assert_called_once_with('fake_api.example.org', 0)

    def test_route_with_host_v6(self, mock_exec, mock_getaddrinfo,
                                mock_requests_get):
        mock_getaddrinfo.return_value = [
            (sentinel.a, sentinel.b, sentinel.c, sentinel.d,
             ('fc00:1111::1', sentinel.e)),
        ]
        mock_exec.return_value = (
            """fc00:101::1 dev br-ctlplane  src fc00:101::4  metric 0
                cache """,
            ""
        )
        # Mock successful HTTP reachability test
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_requests_get.return_value = mock_response

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('fc00:101::4', 9990),
                         self.agent.advertise_address)
        mock_exec.assert_called_once_with('ip', 'route', 'get', 'fc00:1111::1')
        mock_getaddrinfo.assert_called_once_with('fake_api.example.org', 0)

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_route_retry(self, mock_sleep, mock_exec, mock_getaddrinfo,
                         mock_requests_get):
        mock_getaddrinfo.return_value = [
            (sentinel.a, sentinel.b, sentinel.c, sentinel.d,
             ('1.2.1.2', sentinel.e)),
        ]
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
        mock_getaddrinfo.assert_called_once_with('fake_api.example.org', 0)
        mock_sleep.assert_called_with(10)
        self.assertEqual(3, mock_exec.call_count)
        self.assertEqual(2, mock_sleep.call_count)

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_route_several_urls_and_retries(self, mock_sleep, mock_exec,
                                            mock_getaddrinfo,
                                            mock_requests_get):
        mock_getaddrinfo.side_effect = lambda addr, port: [
            (sentinel.a, sentinel.b, sentinel.c, sentinel.d,
             (addr, sentinel.e)),
        ]
        self.agent.api_urls = ['http://[fc00:1111::1]:8081/v1',
                               'http://1.2.1.2:8081/v1']
        mock_exec.side_effect = [
            processutils.ProcessExecutionError('boom'),
            (
                "Error: some error text",
                ""
            ),
            processutils.ProcessExecutionError('boom'),
            (
                """1.2.1.2 via 192.168.122.1 dev eth0  src 192.168.122.56
                    cache """,
                ""
            )
        ]

        self.agent.set_agent_advertise_addr()

        self.assertEqual(('192.168.122.56', 9990),
                         self.agent.advertise_address)
        self.assertCountEqual(
            mock_exec.mock_calls,
            [
                mock.call('ip', 'route', 'get', 'fc00:1111::1'),
                mock.call('ip', 'route', 'get', '1.2.1.2'),
                mock.call('ip', 'route', 'get', 'fc00:1111::1'),
                mock.call('ip', 'route', 'get', '1.2.1.2'),
            ],
        )
        mock_getaddrinfo.assert_has_calls([
            mock.call('fc00:1111::1', 0),
            mock.call('1.2.1.2', 0),
        ])
        mock_sleep.assert_called_with(10)
        self.assertEqual(4, mock_exec.call_count)
        # Both URLs are handled in a single attempt, so only one sleep here
        self.assertEqual(1, mock_sleep.call_count)
        self.assertEqual(2, mock_getaddrinfo.call_count)

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_route_failed(self, mock_sleep, mock_exec, mock_getaddrinfo,
                          mock_requests_get):
        mock_getaddrinfo.return_value = [
            (sentinel.a, sentinel.b, sentinel.c, sentinel.d,
             ('1.2.1.2', sentinel.e)),
        ]
        mock_exec.side_effect = processutils.ProcessExecutionError('boom')

        self.assertRaises(errors.LookupAgentIPError,
                          self.agent.set_agent_advertise_addr)

        mock_exec.assert_called_with('ip', 'route', 'get', '1.2.1.2')
        mock_getaddrinfo.assert_called_once_with('fake_api.example.org', 0)
        self.assertEqual(5, mock_exec.call_count)
        self.assertEqual(5, mock_sleep.call_count)


@mock.patch.object(hardware, '_md_scan_and_assemble', lambda: None)
@mock.patch.object(hardware, '_check_for_iscsi', lambda: None)
@mock.patch.object(hardware.GenericHardwareManager, 'wait_for_disks',
                   lambda self: None)
class TestBaseAgentVMediaToken(ironic_agent_base.IronicAgentTest):

    def setUp(self):
        super(TestBaseAgentVMediaToken, self).setUp()
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
                                             False,
                                             '1' * 128)
        self.agent.ext_mgr = extension.ExtensionManager.\
            make_test_instance([extension.Extension('fake', None,
                                                    FakeExtension,
                                                    FakeExtension())])
        self.sample_nw_iface = hardware.NetworkInterface(
            "eth9", "AA:BB:CC:DD:EE:FF", "1.2.3.4", True)
        hardware.NODE = None

    @mock.patch(
        'ironic_python_agent.hardware_managers.cna._detect_cna_card',
        mock.Mock())
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    @mock.patch.object(agent.IronicPythonAgent,
                       '_wait_for_interface', autospec=True)
    @mock.patch.object(hardware, 'get_managers', autospec=True)
    def test_run_agent_token_vmedia(self, mock_get_managers,
                                    mock_wait, mock_dispatch):
        CONF.set_override('inspection_callback_url', '')

        def set_serve_api(*args, **kwargs):
            self.agent.serve_api = False

        self.agent.api.start = mock.Mock(side_effect=set_serve_api)
        self.agent.heartbeater = mock.Mock()
        self.agent.api_client.lookup_node = mock.Mock()
        self.agent.api_client.lookup_node.return_value = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300,
                'agent_token': '********',
            }
        }

        self.agent.run()
        self.assertFalse(self.agent.lockdown)

        self.agent.api.start.assert_called_once_with(mock.ANY, mock.ANY)
        mock_wait.assert_called_once_with(mock.ANY)
        self.assertEqual([mock.call('list_hardware_info'),
                          mock.call('wait_for_disks')],
                         mock_dispatch.call_args_list)
        self.agent.heartbeater.start.assert_called_once_with()
        self.assertEqual('1' * 128, self.agent.agent_token)
        self.assertEqual('1' * 128, self.agent.api_client.agent_token)


class TestFromConfig(ironic_agent_base.IronicAgentTest):

    def test_override_urls(self):
        urls = ['http://[fc00:1111::1]:8081/v1', 'http://1.2.1.2:8081/v1']
        CONF.set_override('api_url', ','.join(urls))
        ag = agent.IronicPythonAgent.from_config(CONF)
        self.assertEqual(urls, ag.api_urls)

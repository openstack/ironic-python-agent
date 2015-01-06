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

import glob
import json
import os
import time

import mock
from oslo_concurrency import processutils
from oslotest import base as test_base
import pkg_resources
import six
from stevedore import extension
from wsgiref import simple_server

from ironic_python_agent import agent
from ironic_python_agent.cmd import agent as agent_cmd
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import utils

EXPECTED_ERROR = RuntimeError('command execution failed')

if six.PY2:
    OPEN_FUNCTION_NAME = '__builtin__.open'
else:
    OPEN_FUNCTION_NAME = 'builtins.open'


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
        wsgi_server.serve_forever.assert_called_once()

        self.agent.heartbeater.start.assert_called_once_with()

    @mock.patch('os.read')
    @mock.patch('select.poll')
    @mock.patch('time.sleep', return_value=None)
    def test_ipv4_lookup(self, mock_time_sleep, mock_poll, mock_read):
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

        homeless_agent.hardware = mock.Mock()
        mock_list_net = homeless_agent.hardware.list_network_interfaces
        mock_get_ipv4 = homeless_agent.hardware.get_ipv4_addr

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
        wsgi_server.serve_forever.assert_called_once()

        self.assertFalse(self.agent.heartbeater.called)
        self.assertFalse(self.agent.api_client.lookup_node.called)


class TestAgentCmd(test_base.BaseTestCase):
    @mock.patch('ironic_python_agent.openstack.common.log.getLogger')
    @mock.patch(OPEN_FUNCTION_NAME)
    def test__read_params_from_file_fail(self, logger_mock, open_mock):
        open_mock.side_effect = Exception
        params = agent_cmd._read_params_from_file('file-path')
        self.assertEqual(params, {})

    @mock.patch(OPEN_FUNCTION_NAME)
    def test__read_params_from_file(self, open_mock):
        kernel_line = 'api-url=http://localhost:9999 baz foo=bar\n'
        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        read_mock = open_mock.return_value.read
        read_mock.return_value = kernel_line
        params = agent_cmd._read_params_from_file('file-path')
        open_mock.assert_called_once_with('file-path')
        read_mock.assert_called_once_with()
        self.assertEqual(params['api-url'], 'http://localhost:9999')
        self.assertEqual(params['foo'], 'bar')
        self.assertFalse('baz' in params)

    @mock.patch.object(agent_cmd, '_read_params_from_file')
    def test__get_agent_params_kernel_cmdline(self, read_params_mock):

        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        returned_params = agent_cmd._get_agent_params()
        read_params_mock.assert_called_once_with('/proc/cmdline')
        self.assertEqual(expected_params, returned_params)

    @mock.patch.object(agent_cmd, '_get_vmedia_params')
    @mock.patch.object(agent_cmd, '_read_params_from_file')
    def test__get_agent_params_vmedia(self, read_params_mock,
                                       get_vmedia_params_mock):

        kernel_params = {'boot_method': 'vmedia'}
        vmedia_params = {'a': 'b'}
        expected_params = dict(kernel_params.items() +
                               vmedia_params.items())
        read_params_mock.return_value = kernel_params
        get_vmedia_params_mock.return_value = vmedia_params

        returned_params = agent_cmd._get_agent_params()
        read_params_mock.assert_called_once_with('/proc/cmdline')
        self.assertEqual(expected_params, returned_params)

    @mock.patch(OPEN_FUNCTION_NAME)
    @mock.patch.object(glob, 'glob')
    def test__get_vmedia_device(self, glob_mock, open_mock):

        glob_mock.return_value = ['/sys/class/block/sda/device/model',
                                  '/sys/class/block/sdb/device/model',
                                  '/sys/class/block/sdc/device/model']
        fobj_mock = mock.MagicMock()
        mock_file_handle = mock.MagicMock(spec=file)
        mock_file_handle.__enter__.return_value = fobj_mock
        open_mock.return_value = mock_file_handle

        fobj_mock.read.side_effect = ['scsi disk', Exception, 'Virtual Media']
        vmedia_device_returned = agent_cmd._get_vmedia_device()
        self.assertEqual('sdc', vmedia_device_returned)

    @mock.patch.object(agent_cmd, '_get_vmedia_device')
    @mock.patch.object(agent_cmd, '_read_params_from_file')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params(self, execute_mock, mkdir_mock,
                                read_params_mock, get_device_mock):
        vmedia_mount_point = "/vmedia_mnt"

        null_output = ["", ""]
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        execute_mock.side_effect = [null_output, null_output]
        get_device_mock.return_value = "sda"

        returned_params = agent_cmd._get_vmedia_params()

        mkdir_mock.assert_called_once_with(vmedia_mount_point)
        execute_mock.assert_any_call('mount', "/dev/sda", vmedia_mount_point)
        read_params_mock.assert_called_once_with("/vmedia_mnt/parameters.txt")
        execute_mock.assert_any_call('umount', vmedia_mount_point)
        self.assertEqual(expected_params, returned_params)

    @mock.patch.object(agent_cmd, '_get_vmedia_device')
    def test__get_vmedia_params_cannot_find_dev(self, get_device_mock):
        get_device_mock.return_value = None
        self.assertRaises(errors.VirtualMediaBootError,
                          agent_cmd._get_vmedia_params)

    @mock.patch.object(agent_cmd, '_get_vmedia_device')
    @mock.patch.object(agent_cmd, '_read_params_from_file')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_mount_fails(self, execute_mock,
                                            mkdir_mock, read_params_mock,
                                            get_device_mock):
        vmedia_mount_point = "/vmedia_mnt"

        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        get_device_mock.return_value = "sda"

        execute_mock.side_effect = processutils.ProcessExecutionError()

        self.assertRaises(errors.VirtualMediaBootError,
                          agent_cmd._get_vmedia_params)

        mkdir_mock.assert_called_once_with(vmedia_mount_point)
        execute_mock.assert_any_call('mount', "/dev/sda", vmedia_mount_point)

    @mock.patch.object(agent_cmd, '_get_vmedia_device')
    @mock.patch.object(agent_cmd, '_read_params_from_file')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_umount_fails(self, execute_mock, mkdir_mock,
                                            read_params_mock, get_device_mock):
        vmedia_mount_point = "/vmedia_mnt"

        null_output = ["", ""]
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        get_device_mock.return_value = "sda"

        execute_mock.side_effect = [null_output,
                                    processutils.ProcessExecutionError()]

        returned_params = agent_cmd._get_vmedia_params()

        mkdir_mock.assert_called_once_with(vmedia_mount_point)
        execute_mock.assert_any_call('mount', "/dev/sda", vmedia_mount_point)
        read_params_mock.assert_called_once_with("/vmedia_mnt/parameters.txt")
        execute_mock.assert_any_call('umount', vmedia_mount_point)
        self.assertEqual(expected_params, returned_params)

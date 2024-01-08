#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from unittest import mock

from ironic_lib import utils
from oslo_concurrency import processutils
from tooz import coordination

from ironic_python_agent import burnin
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent.tests.unit import base


SMART_OUTPUT_JSON_COMPLETED = ("""
{
  "ata_smart_data": {
    "self_test": {
      "status": {
        "value": 0,
        "string": "completed without error",
        "passed": true
      },
      "polling_minutes": {
        "short": 1,
        "extended": 2,
        "conveyance": 2
      }
    }
  }
}
""")

SMART_OUTPUT_JSON_MISSING = ("""
{
  "ata_smart_data": {
    "self_test": {
      "status": {
        "value": 0,
        "passed": true
      }
    }
  }
}
""")


@mock.patch.object(utils, 'execute', autospec=True)
class TestBurnin(base.IronicAgentTest):

    def test_stress_ng_cpu_default(self, mock_execute):

        node = {'driver_info': {}}
        mock_execute.return_value = (['out', 'err'])

        burnin.stress_ng_cpu(node)

        mock_execute.assert_called_once_with(
            'stress-ng', '--cpu', 0, '--timeout', 86400, '--metrics-brief')

    def test_stress_ng_cpu_non_default(self, mock_execute):

        node = {'driver_info': {
            'agent_burnin_cpu_cpu': 3,
            'agent_burnin_cpu_timeout': 2911,
            'agent_burnin_cpu_outputfile': '/var/log/burnin.cpu'}}
        mock_execute.return_value = (['out', 'err'])

        burnin.stress_ng_cpu(node)

        mock_execute.assert_called_once_with(
            'stress-ng', '--cpu', 3, '--timeout', 2911, '--metrics-brief',
            '--log-file', '/var/log/burnin.cpu')

    def test_stress_ng_cpu_no_stress_ng(self, mock_execute):

        node = {'driver_info': {}}
        mock_execute.side_effect = (['out', 'err'],
                                    processutils.ProcessExecutionError())

        burnin.stress_ng_cpu(node)

        self.assertRaises(errors.CommandExecutionError,
                          burnin.stress_ng_cpu, node)

    def test_stress_ng_vm_default(self, mock_execute):

        node = {'driver_info': {}}
        mock_execute.return_value = (['out', 'err'])

        burnin.stress_ng_vm(node)

        mock_execute.assert_called_once_with(

            'stress-ng', '--vm', 0, '--vm-bytes', '98%',
            '--timeout', 86400, '--metrics-brief')

    def test_stress_ng_vm_non_default(self, mock_execute):

        node = {'driver_info': {
            'agent_burnin_vm_vm': 2,
            'agent_burnin_vm_vm-bytes': '25%',
            'agent_burnin_vm_timeout': 120,
            'agent_burnin_vm_outputfile': '/var/log/burnin.vm'}}
        mock_execute.return_value = (['out', 'err'])

        burnin.stress_ng_vm(node)

        mock_execute.assert_called_once_with(
            'stress-ng', '--vm', 2, '--vm-bytes', '25%',
            '--timeout', 120, '--metrics-brief',
            '--log-file', '/var/log/burnin.vm')

    def test_stress_ng_vm_no_stress_ng(self, mock_execute):

        node = {'driver_info': {}}
        mock_execute.side_effect = (['out', 'err'],
                                    processutils.ProcessExecutionError())

        burnin.stress_ng_vm(node)

        self.assertRaises(errors.CommandExecutionError,
                          burnin.stress_ng_vm, node)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_fio_disk_default(self, mock_list, mock_execute):

        node = {'driver_info': {}}

        mock_list.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_disk(node)

        mock_execute.assert_called_once_with(
            'fio', '--rw', 'readwrite', '--bs', '4k', '--direct', 1,
            '--ioengine', 'libaio', '--iodepth', '32', '--verify',
            'crc32c', '--verify_dump', 1, '--continue_on_error', 'verify',
            '--loops', 4, '--runtime', 0, '--time_based', '--name',
            '/dev/sdj', '--name', '/dev/hdaa')

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_fio_disk_no_default(self, mock_list, mock_execute):

        node = {'driver_info': {
            'agent_burnin_fio_disk_runtime': 600,
            'agent_burnin_fio_disk_loops': 5,
            'agent_burnin_fio_disk_outputfile': '/var/log/burnin.disk'}}

        mock_list.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_disk(node)

        mock_execute.assert_called_once_with(
            'fio', '--rw', 'readwrite', '--bs', '4k', '--direct', 1,
            '--ioengine', 'libaio', '--iodepth', '32', '--verify',
            'crc32c', '--verify_dump', 1, '--continue_on_error', 'verify',
            '--loops', 5, '--runtime', 600, '--time_based', '--output-format',
            'json', '--output', '/var/log/burnin.disk', '--name', '/dev/sdj',
            '--name', '/dev/hdaa', )

    def test__smart_test_status(self, mock_execute):
        device = hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True)
        mock_execute.return_value = ([SMART_OUTPUT_JSON_COMPLETED, 'err'])

        status = burnin._smart_test_status(device)

        mock_execute.assert_called_once_with('smartctl', '-ja', '/dev/sdj')
        self.assertEqual(status, "completed without error")

    def test__smart_test_status_missing(self, mock_execute):
        device = hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True)
        mock_execute.return_value = ([SMART_OUTPUT_JSON_MISSING, 'err'])

        status = burnin._smart_test_status(device)

        mock_execute.assert_called_once_with('smartctl', '-ja', '/dev/sdj')
        self.assertIsNone(status)

    @mock.patch.object(burnin, '_smart_test_status', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_fio_disk_smart_test(self, mock_list, mock_status, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_disk_smart_test': True}}

        mock_list.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]
        mock_status.return_value = "completed without error"
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_disk(node)

        expected_calls = [
            mock.call('fio', '--rw', 'readwrite', '--bs', '4k', '--direct', 1,
                      '--ioengine', 'libaio', '--iodepth', '32', '--verify',
                      'crc32c', '--verify_dump', 1, '--continue_on_error',
                      'verify', '--loops', 4, '--runtime', 0, '--time_based',
                      '--name', '/dev/sdj', '--name', '/dev/hdaa'),
            mock.call('smartctl', '-t', 'long', '/dev/sdj'),
            mock.call('smartctl', '-t', 'long', '/dev/hdaa')
        ]
        mock_execute.assert_has_calls(expected_calls)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_fio_disk_no_fio(self, mock_list, mock_execute):

        node = {'driver_info': {}}
        mock_execute.side_effect = (['out', 'err'],
                                    processutils.ProcessExecutionError())

        burnin.fio_disk(node)

        self.assertRaises(errors.CommandExecutionError,
                          burnin.fio_disk, node)

    def test_fio_network_reader(self, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_network_runtime': 600,
                                'agent_burnin_fio_network_config':
                                    {'partner': 'host-002',
                                     'role': 'reader'}}}
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_network(node)

        expected_calls = [
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name',
                      'reader', '--rw', 'read', '--hostname', 'host-002'),
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name', 'writer',
                      '--rw', 'write', '--runtime', 600, '--time_based',
                      '--listen')]
        mock_execute.assert_has_calls(expected_calls)

    def test_fio_network_reader_w_logfile(self, mock_execute):

        node = {'driver_info': {
            'agent_burnin_fio_network_runtime': 600,
            'agent_burnin_fio_network_config':
                {'partner': 'host-002',
                 'role': 'reader'},
            'agent_burnin_fio_network_outputfile': '/var/log/burnin.network'}}
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_network(node)

        expected_calls = [
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name',
                      'reader', '--rw', 'read', '--hostname', 'host-002',
                      '--output-format', 'json', '--output',
                      '/var/log/burnin.network.reader'),
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name', 'writer',
                      '--rw', 'write', '--runtime', 600, '--time_based',
                      '--listen', '--output-format', 'json', '--output',
                      '/var/log/burnin.network.writer')]
        mock_execute.assert_has_calls(expected_calls)

    def test_fio_network_writer(self, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_network_runtime': 600,
                                'agent_burnin_fio_network_config':
                                    {'partner': 'host-001',
                                     'role': 'writer'}}}
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_network(node)

        expected_calls = [
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name', 'writer',
                      '--rw', 'write', '--runtime', 600, '--time_based',
                      '--listen'),
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name',
                      'reader', '--rw', 'read', '--hostname', 'host-001')]
        mock_execute.assert_has_calls(expected_calls)

    def test_fio_network_writer_w_logfile(self, mock_execute):

        node = {'driver_info': {
            'agent_burnin_fio_network_runtime': 600,
            'agent_burnin_fio_network_config':
                {'partner': 'host-001',
                 'role': 'writer'},
            'agent_burnin_fio_network_outputfile': '/var/log/burnin.network'}}
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_network(node)

        expected_calls = [
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name', 'writer',
                      '--rw', 'write', '--runtime', 600, '--time_based',
                      '--listen', '--output-format', 'json', '--output',
                      '/var/log/burnin.network.writer'),
            mock.call('fio', '--ioengine', 'net', '--port', '9000',
                      '--fill_device', 1, '--group_reporting',
                      '--gtod_reduce', 1, '--numjobs', 16, '--name',
                      'reader', '--rw', 'read', '--hostname', 'host-001',
                      '--output-format', 'json', '--output',
                      '/var/log/burnin.network.reader')]
        mock_execute.assert_has_calls(expected_calls)

    def test_fio_network_no_fio(self, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_network_config':
                                {'partner': 'host-003', 'role': 'reader'}}}
        mock_execute.side_effect = processutils.ProcessExecutionError('boom')

        self.assertRaises(errors.CommandExecutionError,
                          burnin.fio_network, node)

    def test_fio_network_unknown_role(self, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_network_config':
                                {'partner': 'host-003', 'role': 'read'}}}

        self.assertRaises(errors.CleaningError, burnin.fio_network, node)

    def test_fio_network_no_role(self, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_network_config':
                                {'partner': 'host-003'}}}

        self.assertRaises(errors.CleaningError, burnin.fio_network, node)

    def test_fio_network_no_partner(self, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_network_config':
                                {'role': 'reader'}}}

        self.assertRaises(errors.CleaningError, burnin.fio_network, node)

    @mock.patch('time.sleep', autospec=True)
    def test_fio_network_reader_loop(self, mock_time, mock_execute):

        node = {'driver_info': {'agent_burnin_fio_network_config':
                                {'partner': 'host-004', 'role': 'reader'}}}
        # mock the infinite loop
        mock_execute.side_effect = (processutils.ProcessExecutionError(
                                    'Connection timeout', exit_code=16),
                                    processutils.ProcessExecutionError(
                                    'Connection timeout', exit_code=16),
                                    processutils.ProcessExecutionError(
                                    'Connection refused', exit_code=16),
                                    ['out', 'err'],  # connected!
                                    ['out', 'err'])  # reversed roles

        burnin.fio_network(node)

        # we loop 3 times, then do the 2 fio calls
        self.assertEqual(5, mock_execute.call_count)
        self.assertEqual(3, mock_time.call_count)

    def test_fio_network_dynamic_pairing_raise_missing_config(self,
                                                              mock_execute):
        node = {'driver_info': {}}
        self.assertRaises(errors.CleaningError, burnin.fio_network, node)

    def test_fio_network_dynamic_pairing_raise_wrong_config(self,
                                                            mock_execute):
        node = {'driver_info': {
            'backend_url': 'zookeeper://zookeeper-host-01:2181',
            'group_name': 'ironic.dynamic-network-burnin',
            'timeout': 600}}
        self.assertRaises(errors.CleaningError, burnin.fio_network, node)

    @mock.patch.object(burnin, '_find_network_burnin_partner_and_role',
                       autospec=True)
    def test_fio_network_dynamic_pairing_defaults(self, mock_find,
                                                  mock_execute):
        node = {'driver_info': {
            'agent_burnin_fio_network_pairing_backend_url':
                'zookeeper://zookeeper-host-01:2181'}}
        mock_find.return_value = ['partner-host', 'reader']
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_network(node)

        mock_find.assert_called_once_with(
            backend_url='zookeeper://zookeeper-host-01:2181',
            group_name='ironic.network-burnin',
            timeout=900)

    @mock.patch.object(burnin, '_find_network_burnin_partner_and_role',
                       autospec=True)
    def test_fio_network_dynamic_pairing_no_defaults(self, mock_find,
                                                     mock_execute):
        node = {'driver_info': {
            'agent_burnin_fio_network_pairing_backend_url':
                'zookeeper://zookeeper-host-01:2181',
            'agent_burnin_fio_network_pairing_group_name':
                'ironic.special-group',
            'agent_burnin_fio_network_pairing_timeout': 600}}
        mock_find.return_value = ['partner-host', 'reader']
        mock_execute.return_value = (['out', 'err'])

        burnin.fio_network(node)

        mock_find.assert_called_once_with(
            backend_url='zookeeper://zookeeper-host-01:2181',
            group_name='ironic.special-group',
            timeout=600)

    @mock.patch.object(coordination, 'get_coordinator', autospec=True)
    def test_fio_network_dynamic_find_timeout(self, mock_get_coordinator,
                                              mock_execute):
        mock_coordinator = mock.MagicMock()
        mock_get_coordinator.return_value = mock_coordinator

        # timeout since no other node is joining
        self.assertRaises(errors.CleaningError,
                          burnin._find_network_burnin_partner_and_role,
                          "zk://xyz", 'group', 2)

        # group did not exist, so we created it
        mock_coordinator.create_group.assert_called_once_with('group')
        mock_coordinator.join_group.assert_called_once()
        # get_members is called initially, then every second
        # up to the timeout
        self.assertEqual(3, mock_coordinator.get_members.call_count)

    @mock.patch.object(coordination, 'get_coordinator', autospec=True)
    def test_fio_network_dynamic_find_pair_1st(self, mock_get_coordinator,
                                               mock_execute):
        mock_coordinator = mock.MagicMock()
        mock_get_coordinator.return_value = mock_coordinator

        class Members:
            def __init__(self, members=[]):
                self.members = members

            def get(self):
                return self.members

        # we are the first node to enter, so no other host
        # initially until the second one appears after some
        # iterations
        mock_coordinator.get_members.side_effect = \
            [Members(), Members([b'host1']), Members([b'host1']),
             Members([b'host1']), Members([b'host1', b'host2'])]

        (partner, role) = \
            burnin._find_network_burnin_partner_and_role("zk://xyz",
                                                         "group", 10)

        # ... so we will leave first and be the writer
        self.assertEqual((partner, role), ("host2", "writer"))

        # group did not exist, so we created it
        mock_coordinator.create_group.assert_called_once_with('group')
        mock_coordinator.join_group.assert_called_once()
        # get_members is called initially, then every second
        # up to the timeout
        self.assertEqual(5, mock_coordinator.get_members.call_count)

    @mock.patch.object(coordination, 'get_coordinator', autospec=True)
    def test_fio_network_dynamic_find_pair_2nd(self, mock_get_coordinator,
                                               mock_execute):
        mock_coordinator = mock.MagicMock()
        mock_get_coordinator.return_value = mock_coordinator

        class Members:
            def __init__(self, members=[]):
                self.members = members

            def get(self):
                return self.members

        # we are the second node to enter, host1 is there before us ...
        mock_coordinator.get_members.side_effect = \
            [Members([b'host1']),
             Members([b'host1', b'host2']),
             Members([b'host2'])]

        (partner, role) = \
            burnin._find_network_burnin_partner_and_role("zk://xyz",
                                                         "group", 10)

        # ... so we will leave second and be the reader
        self.assertEqual((partner, role), ("host1", "reader"))

        # group did not exist, so we created it
        mock_coordinator.create_group.assert_called_once_with('group')
        mock_coordinator.join_group.assert_called_once()
        # get_members is called initially, then every second until the
        # other node appears
        self.assertEqual(3, mock_coordinator.get_members.call_count)

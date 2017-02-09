# Copyright 2017 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import mock
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent import numa_inspector as numa_insp
from ironic_python_agent import utils


class TestCollectNumaTopologyInfo(test_base.BaseTestCase):
    def setUp(self):
        super(TestCollectNumaTopologyInfo, self).setUp()
        self.data = {}
        self.failures = utils.AccumulatedFailures()

    @mock.patch.object(numa_insp, 'get_nodes_nics_info', autospec=True)
    @mock.patch.object(numa_insp, 'get_nodes_cores_info', autospec=True)
    @mock.patch.object(numa_insp, 'get_nodes_memory_info', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    def test_collect_success(self, mock_listdir, mock_isdir, mock_memory_info,
                             mock_cores_info, mock_nics_info):
        numa_node_dirs = ['node0', 'node1']
        mock_listdir.return_value = numa_node_dirs
        mock_isdir.return_value = True
        mock_memory_info.return_value = [{'numa_node': 0, 'size_kb': 1560000},
                                         {'numa_node': 1, 'size_kb': 1200000}]
        mock_cores_info.return_value = [{'cpu': 0, 'numa_node': 0,
                                         'thread_siblings': [0, 1, 2, 3]},
                                        {'cpu': 1, 'numa_node': 0,
                                         'thread_siblings': [4, 5, 6]},
                                        {'cpu': 0, 'numa_node': 1,
                                         'thread_siblings': [16, 17]},
                                        {'cpu': 1, 'numa_node': 1,
                                         'thread_siblings': [18, 19]}]
        mock_nics_info.return_value = [{'name': 'enp0s01', 'numa_node': 0},
                                       {'name': 'enp0s02', 'numa_node': 1}]
        expected_numa_info = {"ram": [{'numa_node': 0, 'size_kb': 1560000},
                                      {'numa_node': 1, 'size_kb': 1200000}],
                              "cpus": [{'cpu': 0, 'numa_node': 0,
                                        'thread_siblings': [0, 1, 2, 3]},
                                       {'cpu': 1, 'numa_node': 0,
                                        'thread_siblings': [4, 5, 6]},
                                       {'cpu': 0, 'numa_node': 1,
                                        'thread_siblings': [16, 17]},
                                       {'cpu': 1, 'numa_node': 1,
                                        'thread_siblings': [18, 19]}],
                              "nics": [{'name': 'enp0s01', 'numa_node': 0},
                                       {'name': 'enp0s02', 'numa_node': 1}]}
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            numa_insp.collect_numa_topology_info(self.data, self.failures)
        self.assertEqual(expected_numa_info, self.data["numa_topology"])

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_collect_no_numa_dirs(self, mock_isdir):
        mock_isdir.return_value = False
        numa_insp.collect_numa_topology_info(self.data, self.failures)
        self.assertNotIn("numa_topology", self.data)

    @mock.patch.object(numa_insp, 'get_nodes_nics_info', autospec=True)
    @mock.patch.object(numa_insp, 'get_nodes_cores_info', autospec=True)
    @mock.patch.object(numa_insp, 'get_nodes_memory_info', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    def test_collect_no_nics_dirs(self, mock_listdir, mock_isdir,
                                  mock_memory_info, mock_cores_info,
                                  mock_nics_info):
        numa_node_dirs = ['node0', 'node1']
        mock_listdir.return_value = numa_node_dirs
        mock_isdir.return_value = True
        mock_memory_info.return_value = [{'numa_node': 0, 'size_kb': 1560000},
                                         {'numa_node': 1, 'size_kb': 1200000}]
        mock_cores_info.return_value = [{'cpu': 0, 'numa_node': 0,
                                         'thread_siblings': [0, 1, 2, 3]},
                                        {'cpu': 1, 'numa_node': 1,
                                         'thread_siblings': [4, 5, 6]}]
        mock_nics_info.side_effect = errors.IncompatibleNumaFormatError("")
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            numa_insp.collect_numa_topology_info(self.data, self.failures)
        self.assertNotIn("numa_topology", self.data)

    @mock.patch.object(numa_insp, 'get_nodes_nics_info', autospec=True)
    @mock.patch.object(numa_insp, 'get_nodes_cores_info', autospec=True)
    @mock.patch.object(numa_insp, 'get_nodes_memory_info', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    def test_collect_failure(self, mock_listdir, mock_isdir, mock_memory_info,
                             mock_cores_info, mock_nics_info):
        numa_node_dirs = ['node0', 'node1']
        mock_listdir.return_value = numa_node_dirs
        mock_isdir.return_value = True
        mock_memory_info.side_effect = errors.IncompatibleNumaFormatError("")
        mock_cores_info.side_effect = errors.IncompatibleNumaFormatError("")
        mock_nics_info.side_effect = errors.IncompatibleNumaFormatError("")
        numa_insp.collect_numa_topology_info(self.data, self.failures)
        self.assertNotIn("numa_topology", self.data)
        self.assertFalse(self.failures)


class TestGetNumaTopologyInfo(test_base.BaseTestCase):
    def setUp(self):
        super(TestGetNumaTopologyInfo, self).setUp()
        self.data = {}
        self.failures = utils.AccumulatedFailures()

    def test_get_numa_node_id_valid_format(self):
        numa_node_dir = '/sys/devices/system/node/node0'
        expected_numa_node_id = 0
        numa_node_id = numa_insp.get_numa_node_id(numa_node_dir)
        self.assertEqual(expected_numa_node_id, numa_node_id)

    def test_get_numa_node_id_invalid_format(self):
        self.assertRaises(errors.IncompatibleNumaFormatError,
                          numa_insp.get_numa_node_id,
                          '/sys/devices/system/node/node-*0')
        self.assertRaises(errors.IncompatibleNumaFormatError,
                          numa_insp.get_numa_node_id,
                          '/sys/devices/system/node/nod')
        self.assertRaises(errors.IncompatibleNumaFormatError,
                          numa_insp.get_numa_node_id,
                          '')

    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_get_nodes_memory_info(self, mock_node_id):
        numa_node_dirs = ['/sys/devices/system/node/node0',
                          '/sys/devices/system/node/node1']
        mock_node_id.side_effect = [0, 1]
        reads = [['Node 0 Ignored Line',
                  'Node 0 MemTotal: 1560000 kB'],
                 ['Node 1 MemTotal: 1200000 kB',
                  'Node 1 Ignored Line']]
        expected_meminfo = [{'numa_node': 0, 'size_kb': 1560000},
                            {'numa_node': 1, 'size_kb': 1200000}]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_meminfo_file = mock.MagicMock()
            mock_meminfo_file.__enter__.side_effect = reads
            mock_open.return_value = mock_meminfo_file
            ram = numa_insp.get_nodes_memory_info(numa_node_dirs)
        self.assertListEqual(expected_meminfo, ram)

    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_bad_nodes_memory_info(self, mock_node_id):
        numa_node_dirs = ['/sys/devices/system/node/node0',
                          '/sys/devices/system/node/node1']
        mock_node_id.side_effect = [0, 1]
        reads = [['Node 0 MemTotal: 1560000 kB'], IOError]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_meminfo_file = mock.MagicMock()
            mock_meminfo_file.__enter__.side_effect = reads
            mock_open.return_value = mock_meminfo_file
            self.assertRaises(errors.IncompatibleNumaFormatError,
                              numa_insp.get_nodes_memory_info,
                              numa_node_dirs)

    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_nodes_invalid_numa_format_memory_info(self, mock_node_id):
        numa_node_dirs = ['/sys/devices/system/node/node0',
                          '/sys/devices/system/node/node1']
        mock_node_id.side_effect = [0, 1]
        reads = [['Node 0: MemTotal: 1560000 kB'],
                 ['Node 1 MemTotal: 1200000 kB']]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_meminfo_file = mock.MagicMock()
            mock_meminfo_file.__enter__.side_effect = reads
            mock_open.return_value = mock_meminfo_file
            self.assertRaises(errors.IncompatibleNumaFormatError,
                              numa_insp.get_nodes_memory_info,
                              numa_node_dirs)

    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_nodes_invalid_memory_unit(self, mock_node_id):
        numa_node_dirs = ['/sys/devices/system/node/node0',
                          '/sys/devices/system/node/node1']
        mock_node_id.side_effect = [0, 1]
        reads = [['Node 0 MemTotal: 1560000 TB'],
                 ['Node 1 MemTotal: 1200000 kB']]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_meminfo_file = mock.MagicMock()
            mock_meminfo_file.__enter__.side_effect = reads
            mock_open.return_value = mock_meminfo_file
            self.assertRaises(errors.IncompatibleNumaFormatError,
                              numa_insp.get_nodes_memory_info,
                              numa_node_dirs)

    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_get_numa_node_id_invalid_format_memory_info(self,
                                                         mock_node_id):
        numa_node_dirs = ['/sys/devices/system/node/node-*0',
                          '/sys/devices/system/node/node1']
        mock_node_id.side_effect = errors.IncompatibleNumaFormatError
        self.assertRaises(errors.IncompatibleNumaFormatError,
                          numa_insp.get_nodes_memory_info,
                          numa_node_dirs)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_get_nodes_cores_info(self, mock_node_id,
                                  mock_listdir, mock_isdir):
        numa_node_dirs = ['/sys/devices/system/node/node0',
                          '/sys/devices/system/node/node1']
        mock_node_id.side_effect = [0, 1]
        mock_listdir.side_effect = [['cpu0', 'cpu1', 'cpu2',
                                     'cpu3', 'cpu4'],
                                    ['cpu5', 'cpu6', 'cpu7']]
        mock_isdir.return_value = True
        reads = ['0', '0', '1', '1', '1', '0', '0', '0']
        expected_cores_info = [{'cpu': 0, 'numa_node': 0,
                                'thread_siblings': [0, 1]},
                               {'cpu': 1, 'numa_node': 0,
                                'thread_siblings': [2, 3, 4]},
                               {'cpu': 0, 'numa_node': 1,
                                'thread_siblings': [5, 6, 7]}]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_core_id_file = mock_open.return_value.read
            mock_core_id_file.side_effect = reads
            cpus = numa_insp.get_nodes_cores_info(numa_node_dirs)
        self.assertEqual(len(cpus), len(expected_cores_info))
        for cpu in cpus:
            self.assertIn(cpu, expected_cores_info)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_bad_nodes_cores_info(self, mock_node_id,
                                  mock_listdir, mock_isdir):
        numa_node_dirs = ['/sys/devices/system/node/node0']
        mock_node_id.return_value = 0
        thread_dirs = ['cpu0', 'cpu1', 'cpu2', 'cpu3', 'cpu4', 'cpu5']
        mock_listdir.return_value = thread_dirs
        mock_isdir.return_value = True
        reads = ['0', '0', '1', '1', '1', IOError]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_core_id_file = mock_open.return_value.read
            mock_core_id_file.side_effect = reads
            self.assertRaises(errors.IncompatibleNumaFormatError,
                              numa_insp.get_nodes_cores_info,
                              numa_node_dirs)

    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_get_numa_node_id_invalid_format_cores_info(self,
                                                        mock_node_id):
        numa_node_dirs = ['/sys/devices/system/node/nodeid0']
        mock_node_id.side_effect = errors.IncompatibleNumaFormatError
        self.assertRaises(errors.IncompatibleNumaFormatError,
                          numa_insp.get_nodes_cores_info,
                          numa_node_dirs)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_nodes_invalid_threaddir_format_cores_info(self, mock_node_id,
                                                       mock_listdir,
                                                       mock_isdir):
        numa_node_dirs = ['/sys/devices/system/node/node0']
        mock_node_id.return_value = 0
        thread_dirs = ['cpuid0', 'cpu1', 'cpu2', 'cpu3', 'cpu4', 'cpu5']
        mock_listdir.return_value = thread_dirs
        mock_isdir.return_value = True
        reads = ['0', '0', '1', '1', '1', '2']
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_core_id_file = mock_open.return_value.read
            mock_core_id_file.side_effect = reads
            self.assertRaises(errors.IncompatibleNumaFormatError,
                              numa_insp.get_nodes_cores_info,
                              numa_node_dirs)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(numa_insp, 'get_numa_node_id', autospec=True)
    def test_bad_nodes_thread_dirs(self, mock_node_id,
                                   mock_listdir, mock_isdir):
        numa_node_dirs = ['/sys/devices/system/node/node0']
        mock_node_id.return_value = 0
        mock_listdir.side_effect = errors.IncompatibleNumaFormatError("")
        mock_isdir.return_value = True
        self.assertRaises(errors.IncompatibleNumaFormatError,
                          numa_insp.get_nodes_cores_info,
                          numa_node_dirs)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    def test_get_nodes_nics_info(self, mock_listdir, mock_isdir):
        nic_dirs = ['enp0s01', 'enp0s02']
        mock_listdir.return_value = nic_dirs
        mock_isdir.return_value = True
        reads = ['0', '1']
        expected_nicsinfo = [{'name': 'enp0s01', 'numa_node': 0},
                             {'name': 'enp0s02', 'numa_node': 1}]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_nicsinfo_file = mock_open.return_value.read
            mock_nicsinfo_file.side_effect = reads
            nics = numa_insp.get_nodes_nics_info('/sys/class/net/')
        self.assertListEqual(expected_nicsinfo, nics)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    def test_bad_nodes_nics_info(self, mock_listdir, mock_isdir):
        nic_dirs = ['enp0s01', 'enp0s02']
        mock_listdir.return_value = nic_dirs
        mock_isdir.return_value = True
        reads = ['0', IOError]
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_nicsinfo_file = mock_open.return_value.read
            mock_nicsinfo_file.side_effect = reads
            self.assertRaises(errors.IncompatibleNumaFormatError,
                              numa_insp.get_nodes_nics_info,
                              '/sys/class/net/')

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_no_nics_dir(self, mock_isdir, mock_listdir):
        mock_isdir.return_value = False
        nic_dirs = ['enp0s01', 'enp0s02']
        mock_listdir.return_value = nic_dirs
        reads = ['0', '1']
        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_nicsinfo_file = mock_open.return_value.read
            mock_nicsinfo_file.side_effect = reads
            self.assertRaises(errors.IncompatibleNumaFormatError,
                              numa_insp.get_nodes_nics_info,
                              '/sys/class/net/')

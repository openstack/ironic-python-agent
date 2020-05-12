# Copyright (C) 2017 Intel Corporation
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

from unittest import mock

from oslo_concurrency import processutils

from ironic_python_agent import dmi_inspector
from ironic_python_agent.tests.unit import base
from ironic_python_agent.tests.unit import dmi_inspector_data as dmi_data
from ironic_python_agent import utils


class TestCollectDmidecodeInfo(base.IronicAgentTest):
    def setUp(self):
        super(TestCollectDmidecodeInfo, self).setUp()
        self.data = {}
        self.failures = utils.AccumulatedFailures()

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_dmidecode_info_ok(self, mock_execute):
        mock_execute.return_value = dmi_data.DMI_DATA

        dmi_inspector.collect_dmidecode_info(self.data, None)

        for key in ('bios', 'memory', 'cpu'):
            self.assertTrue(self.data['dmi'][key])

        self.assertEqual(dmi_data.DMI_OUTPUT, self.data)

        mock_execute.assert_called_once_with('dmidecode', '-t', 'bios',
                                             '-t', 'processor', '-t', 'memory')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_dmidecode_info_bad_data(self, mock_execute):
        mock_execute.return_value = ("""Handle 0x0000\nFoo\nBar: Baz\n""", "")
        expected = {'dmi': {'bios': {}, 'cpu': [], 'memory': {'devices': []}}}

        dmi_inspector.collect_dmidecode_info(self.data, None)

        self.assertEqual(expected, self.data)

        mock_execute.assert_called_once_with('dmidecode', '-t', 'bios',
                                             '-t', 'processor', '-t', 'memory')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_dmidecode_info_failure(self, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError()

        dmi_inspector.collect_dmidecode_info(self.data, self.failures)

        self.assertTrue(self.failures)
        self.assertNotIn('dmi', self.data)
        mock_execute.assert_called_once_with('dmidecode', '-t', 'bios',
                                             '-t', 'processor', '-t', 'memory')

    def test_parse_dmi_bios(self):
        inputdata = dmi_data.BIOS_DATA[0]
        expected = dmi_data.BIOS_OUTPUT

        ret = dmi_inspector.parse_dmi(inputdata)
        self.assertEqual(expected, ret)

    def test_parse_dmi_cpu(self):
        inputdata = dmi_data.CPU_DATA[0]
        expected = dmi_data.CPU_OUTPUT

        ret = dmi_inspector.parse_dmi(inputdata)
        self.assertEqual(expected, ret)

    def test_parse_dmi_memory(self):
        inputdata = dmi_data.MEMORY_DATA[0]
        expected = dmi_data.MEMORY_OUTPUT

        ret = dmi_inspector.parse_dmi(inputdata)
        self.assertEqual(expected, ret)

    def test_save_data(self):
        dmi_info = {}
        dmi_info['bios'] = {}
        dmi_info['cpu'] = []
        dmi_info['memory'] = {}
        dmi_info['memory']['devices'] = {}
        mem = [{'Handle': 'handle', 'Number Of Devices': '2'},
               {'Handle': 'handle', 'Number Of Devices': '2'}]
        devices = [{'bar': 'foo'}, {'bar': 'foo'}]
        expected = {'bios': {},
                    'cpu': [],
                    'memory': {'Number Of Devices': 4,
                               'devices': [{'bar': 'foo'}, {'bar': 'foo'}]}}

        ret = dmi_inspector._save_data(dmi_info, mem, devices)
        self.assertEqual(expected, ret)

    def test_save_data_error_number_of_devices(self):
        dmi_info = {}
        dmi_info['bios'] = {}
        dmi_info['cpu'] = []
        dmi_info['memory'] = {}
        dmi_info['memory']['devices'] = {}

        self.assertRaises(KeyError,
                          dmi_inspector._save_data,
                          dmi_info,
                          [{'foo': 'bar', 'Handle': '0x10'}],
                          [{'bar': 'foo'}, {'bar': 'foo'}])

    def test_save_data_error_handle(self):
        dmi_info = {}
        dmi_info['bios'] = {}
        dmi_info['cpu'] = []
        dmi_info['memory'] = {}
        dmi_info['memory']['devices'] = {}

        self.assertRaises(KeyError,
                          dmi_inspector._save_data,
                          dmi_info,
                          [{'foo': 'bar', 'Number Of Devices': '2'}],
                          [{'bar': 'foo'}, {'bar': 'foo'}])

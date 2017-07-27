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

import mock
from oslo_concurrency import processutils

from ironic_python_agent import dmi_inspector
from ironic_python_agent.tests.unit import base
from ironic_python_agent import utils

BIOS_DATA = ("""
# dmidecode 3.0
Getting SMBIOS data from sysfs.
SMBIOS 2.7 present.

Handle 0x0000, DMI type 0, 24 bytes
Address: 0xF0000
ROM Size: 16384 kB
Characteristics:
     PCI is supported

Handle 0x000B, DMI type 13, 22 bytes
BIOS Language Information
     Installable Languages: 1
         enUS
""", "")

BIOS_OUTPUT = {'bios': {
               'Address': '0xF0000',
               'Characteristics': ['PCI is supported'],
               'Handle': 'Handle 0x0000, DMI type 0, 24 bytes',
               'ROM Size': '16384 kB'},
               'cpu': [],
               'memory': {'devices': []}}

MEMORY_DATA = ("""
# dmidecode 3.0
Getting SMBIOS data from sysfs.
SMBIOS 2.7 present.

Handle 0x0038, DMI type 16, 23 bytes
Physical Memory Array
    Maximum Capacity: 192 GB
    Number Of Devices: 6

Handle 0x003A, DMI type 17, 40 bytes
Memory Device
    Array Handle: 0x0038
    Size: 16384 MB
    Form Factor: DIMM
    Speed: 2133 MHz

Handle 0x0044, DMI type 16, 23 bytes
Physical Memory Array
    Maximum Capacity: 192 GB
    Number Of Devices: 6

Handle 0x0046, DMI type 17, 40 bytes
Memory Device
    Array Handle: 0x0044
    Size: 16384 MB
    Form Factor: DIMM
    Speed: 2133 MHz
""", "")

MEMORY_OUTPUT = {
    'bios': {},
    'cpu': [],
    'memory': {
        'Maximum Capacity': '192 GB',
        'Number Of Devices': 12,
        'devices': [{'Array Handle': '0x0038',
                     'Form Factor': 'DIMM',
                     'Handle': 'Handle 0x003A, DMI type 17, 40 bytes',
                     'Size': '16384 MB',
                     'Speed': '2133 MHz'},
                    {'Array Handle': '0x0044',
                     'Form Factor': 'DIMM',
                     'Handle': 'Handle 0x0046, DMI type 17, 40 bytes',
                     'Size': '16384 MB',
                     'Speed': '2133 MHz'}]}}

CPU_DATA = ("""
# dmidecode 3.0
Getting SMBIOS data from sysfs.
SMBIOS 2.7 present.

Handle 0x0038, DMI type 4, 23 bytes
Family: Xeon
""", "")

CPU_OUTPUT = {'bios': {},
              'cpu': [
             {'Family': 'Xeon',
              'Handle': 'Handle 0x0038, DMI type 4, 23 bytes'}],
              'memory': {'devices': []}}

DMI_DATA = ("""
# dmidecode 2.12
SMBIOS 2.5 present.

Handle 0x0000, DMI type 4, 35 bytes
Processor Information
        Socket Designation: J1PR
        Type: Central Processor
        Family: Core i7
        Manufacturer: Intel(R) Corporation
        ID: C2 06 02 00 FF FB EB BF
        Signature: Type 0, Family 6, Model 44, Stepping 2
        Flags:
                FPU (Floating-point unit on-chip)
                VME (Virtual mode extension)
                DE (Debugging extension)
                PSE (Page size extension)
                TSC (Time stamp counter)
                MSR (Model specific registers)
                PAE (Physical address extension)
                MCE (Machine check exception)
                CX8 (CMPXCHG8 instruction supported)
                APIC (On-chip APIC hardware supported)
                SEP (Fast system call)
                MTRR (Memory type range registers)
                PGE (Page global enable)
                MCA (Machine check architecture)
                CMOV (Conditional move instruction supported)
                PAT (Page attribute table)
                PSE-36 (36-bit page size extension)
                CLFSH (CLFLUSH instruction supported)
                DS (Debug store)
                ACPI (ACPI supported)
                MMX (MMX technology supported)
                FXSR (FXSAVE and FXSTOR instructions supported)
                SSE (Streaming SIMD extensions)
                SSE2 (Streaming SIMD extensions 2)
                SS (Self-snoop)
                HTT (Multi-threading)
                TM (Thermal monitor supported)
                PBE (Pending break enabled)
        Version: Intel(R) Core(TM) i7 CPU       X 980  @ 3.33GHz
        Voltage: 1.2 V
        External Clock: 135 MHz
        Max Speed: 4000 MHz
        Current Speed: 3381 MHz
        Status: Populated, Enabled
        Upgrade: Socket LGA1366
        L1 Cache Handle: 0x0002
        L2 Cache Handle: 0x0003
        L3 Cache Handle: 0x0004
        Serial Number: Not Specified
        Asset Tag: Not Specified
        Part Number: Not Specified

Handle 0x0005, DMI type 0, 24 bytes
BIOS Information
        Vendor: Intel Corp.
        Version: SOX5810J.86A.5561.2011.0516.2023
        Release Date: 05/16/2011
        Address: 0xF0000
        Runtime Size: 64 kB
        ROM Size: 2048 kB
        Characteristics:
                PCI is supported
                BIOS is upgradeable
                BIOS shadowing is allowed
                Boot from CD is supported
                Selectable boot is supported
                EDD is supported
                8042 keyboard services are supported (int 9h)
                Serial services are supported (int 14h)
                Printer services are supported (int 17h)
                CGA/mono video services are supported (int 10h)
                ACPI is supported
                USB legacy is supported
                ATAPI Zip drive boot is supported
                BIOS boot specification is supported
                Function key-initiated network boot is supported
                Targeted content distribution is supported
        BIOS Revision: 0.0
        Firmware Revision: 0.0

Handle 0x0012, DMI type 13, 22 bytes
BIOS Language Information
        Language Description Format: Abbreviated
        Installable Languages: 1
                enUS
        Currently Installed Language: enUS

Handle 0x0014, DMI type 16, 15 bytes
Physical Memory Array
        Location: System Board Or Motherboard
        Use: System Memory
        Error Correction Type: None
        Maximum Capacity: 16 GB
        Error Information Handle: Not Provided
        Number Of Devices: 4

Handle 0x0016, DMI type 17, 27 bytes
Memory Device
        Array Handle: 0x0014
        Error Information Handle: Not Provided
        Total Width: 64 bits
        Data Width: 64 bits
        Size: 2048 MB
        Form Factor: DIMM
        Set: None
        Locator: J1MY
        Bank Locator: CHAN A DIMM 0
        Type: DDR3
        Type Detail: Synchronous
        Speed: 1333 MHz
        Manufacturer: 0x0198
        Serial Number: 0x700ECE90
        Asset Tag: Unknown
        Part Number: 0x393930353437312D3030312E4130304C4620

Handle 0x0017, DMI type 17, 27 bytes
Memory Device
        Array Handle: 0x0014
        Error Information Handle: Not Provided
        Total Width: Unknown
        Data Width: Unknown
        Size: No Module Installed
        Form Factor: DIMM
        Set: None
        Locator: J2MY
        Bank Locator: CHAN A DIMM 1
        Type: DDR3
        Type Detail: Synchronous
        Speed: 1333 MHz
        Manufacturer: NO DIMM
        Serial Number: NO DIMM
        Asset Tag: NO DIMM
        Part Number: NO DIMM

Handle 0x0018, DMI type 17, 27 bytes
Memory Device
        Array Handle: 0x0014
        Error Information Handle: Not Provided
        Total Width: 64 bits
        Data Width: 64 bits
        Size: 2048 MB
        Form Factor: DIMM
        Set: None
        Locator: J3MY
        Bank Locator: CHAN B DIMM 0
        Type: DDR3
        Type Detail: Synchronous
        Speed: 1333 MHz
        Manufacturer: 0x0198
        Serial Number: 0x700ED090
        Asset Tag: Unknown
        Part Number: 0x393930353437312D3030312E4130304C4620

Handle 0x0019, DMI type 17, 27 bytes
Memory Device
        Array Handle: 0x0014
        Error Information Handle: Not Provided
        Total Width: 64 bits
        Data Width: 64 bits
        Size: 2048 MB
        Form Factor: DIMM
        Set: None
        Locator: J4MY
        Bank Locator: CHAN C DIMM 0
        Type: DDR3
        Type Detail: Synchronous
        Speed: 1333 MHz
        Manufacturer: 0x0198
        Serial Number: 0x6F0ED090
        Asset Tag: Unknown
        Part Number: 0x393930353437312D3030312E4130304C4620
""", "")

DMI_OUTPUT = {
    'dmi': {
        'bios': {
            'Address': '0xF0000',
            'BIOS Revision': '0.0',
            'Characteristics': [
                'PCI is supported',
                'BIOS is upgradeable',
                'BIOS shadowing is allowed',
                'Boot from CD is supported',
                'Selectable boot is supported',
                'EDD is supported',
                '8042 keyboard services are supported (int 9h)',
                'Serial services are supported (int 14h)',
                'Printer services are supported (int 17h)',
                'CGA/mono video services are supported (int 10h)',
                'ACPI is supported',
                'USB legacy is supported',
                'ATAPI Zip drive boot is supported',
                'BIOS boot specification is supported',
                'Function key-initiated network boot is supported',
                'Targeted content distribution is supported'],
            'Firmware Revision': '0.0',
            'Handle': 'Handle 0x0005, DMI type 0, 24 bytes',
            'ROM Size': '2048 kB',
            'Release Date': '05/16/2011',
            'Runtime Size': '64 kB',
            'Vendor': 'Intel Corp.',
            'Version': 'SOX5810J.86A.5561.2011.0516.2023'},
        'cpu': [{
            'Asset Tag': 'Not Specified',
            'Current Speed': '3381 MHz',
            'External Clock': '135 MHz',
            'Family': 'Core i7',
            'Flags': [
                'FPU (Floating-point unit on-chip)',
                'VME (Virtual mode extension)',
                'DE (Debugging extension)',
                'PSE (Page size extension)',
                'TSC (Time stamp counter)',
                'MSR (Model specific registers)',
                'PAE (Physical address extension)',
                'MCE (Machine check exception)',
                'CX8 (CMPXCHG8 instruction supported)',
                'APIC (On-chip APIC hardware supported)',
                'SEP (Fast system call)',
                'MTRR (Memory type range registers)',
                'PGE (Page global enable)',
                'MCA (Machine check architecture)',
                'CMOV (Conditional move instruction supported)',
                'PAT (Page attribute table)',
                'PSE-36 (36-bit page size extension)',
                'CLFSH (CLFLUSH instruction supported)',
                'DS (Debug store)',
                'ACPI (ACPI supported)',
                'MMX (MMX technology supported)',
                'FXSR (FXSAVE and FXSTOR instructions supported)',
                'SSE (Streaming SIMD extensions)',
                'SSE2 (Streaming SIMD extensions 2)',
                'SS (Self-snoop)',
                'HTT (Multi-threading)',
                'TM (Thermal monitor supported)',
                'PBE (Pending break enabled)'],
            'Handle': 'Handle 0x0000, DMI type 4, 35 bytes',
                      'ID': 'C2 06 02 00 FF FB EB BF',
                      'L1 Cache Handle': '0x0002',
                      'L2 Cache Handle': '0x0003',
                      'L3 Cache Handle': '0x0004',
                      'Manufacturer': 'Intel(R) Corporation',
                      'Max Speed': '4000 MHz',
                      'Part Number': 'Not Specified',
                      'Serial Number': 'Not Specified',
                      'Signature': 'Type 0, Family 6, Model 44, Stepping 2',
                      'Socket Designation': 'J1PR',
                      'Status': 'Populated, Enabled',
                      'Type': 'Central Processor',
                      'Upgrade': 'Socket LGA1366',
                      'Version': 'Intel(R) Core(TM) i7 CPU       X 980  @ 3.33GHz',  # noqa
            'Voltage': '1.2 V'}],
        'memory': {
            'Error Correction Type': 'None',
            'Error Information Handle': 'Not Provided',
            'Location': 'System Board Or Motherboard',
            'Maximum Capacity': '16 GB',
            'Number Of Devices': 4,
            'Use': 'System Memory',
            'devices': [
                {'Array Handle': '0x0014',
                 'Asset Tag': 'Unknown',
                 'Bank Locator': 'CHAN A DIMM 0',
                 'Data Width': '64 bits',
                 'Error Information Handle': 'Not Provided',
                 'Form Factor': 'DIMM',
                 'Handle': 'Handle 0x0016, DMI type 17, 27 bytes',
                 'Locator': 'J1MY',
                 'Manufacturer': '0x0198',
                 'Part Number': '0x393930353437312D3030312E4130304C4620',
                 'Serial Number': '0x700ECE90',
                 'Set': 'None',
                 'Size': '2048 MB',
                 'Speed': '1333 MHz',
                 'Total Width': '64 bits',
                 'Type': 'DDR3',
                 'Type Detail': 'Synchronous'},
                {'Array Handle': '0x0014',
                 'Asset Tag': 'NO DIMM',
                 'Bank Locator': 'CHAN A DIMM 1',
                 'Data Width': 'Unknown',
                 'Error Information Handle': 'Not Provided',
                 'Form Factor': 'DIMM',
                 'Handle': 'Handle 0x0017, DMI type 17, 27 bytes',
                 'Locator': 'J2MY',
                 'Manufacturer': 'NO DIMM',
                 'Part Number': 'NO DIMM',
                 'Serial Number': 'NO DIMM',
                 'Set': 'None',
                 'Size': 'No Module Installed',
                 'Speed': '1333 MHz',
                 'Total Width': 'Unknown',
                 'Type': 'DDR3',
                 'Type Detail': 'Synchronous'},
                {'Array Handle': '0x0014',
                 'Asset Tag': 'Unknown',
                 'Bank Locator': 'CHAN B DIMM 0',
                 'Data Width': '64 bits',
                 'Error Information Handle': 'Not Provided',
                 'Form Factor': 'DIMM',
                 'Handle': 'Handle 0x0018, DMI type 17, 27 bytes',
                 'Locator': 'J3MY',
                 'Manufacturer': '0x0198',
                 'Part Number': '0x393930353437312D3030312E4130304C4620',
                 'Serial Number': '0x700ED090',
                 'Set': 'None',
                 'Size': '2048 MB',
                 'Speed': '1333 MHz',
                 'Total Width': '64 bits',
                 'Type': 'DDR3',
                 'Type Detail': 'Synchronous'},
                {'Array Handle': '0x0014',
                 'Asset Tag': 'Unknown',
                 'Bank Locator': 'CHAN C DIMM 0',
                 'Data Width': '64 bits',
                 'Error Information Handle': 'Not Provided',
                 'Form Factor': 'DIMM',
                 'Handle': 'Handle 0x0019, DMI type 17, 27 bytes',
                 'Locator': 'J4MY',
                 'Manufacturer': '0x0198',
                 'Part Number': '0x393930353437312D3030312E4130304C4620',
                 'Serial Number': '0x6F0ED090',
                 'Set': 'None',
                 'Size': '2048 MB',
                 'Speed': '1333 MHz',
                 'Total Width': '64 bits',
                 'Type': 'DDR3',
                 'Type Detail': 'Synchronous'}]}}}

DMM_OUTPUT = {'dmi': {'bios': {'Address': '0xF0000',
                      'BIOS Revision': '0.0',
                      'Characteristics': ['PCI is supported',
                                          'BIOS is upgradeable',
                                          'BIOS shadowing is allowed',
                                          'Boot from CD is supported',
                                          'Selectable boot is supported',
                                          'EDD is supported',
                                          '8042 keyboard services are supported (int 9h)',  # noqa
                                          'Serial services are supported (int 14h)',  # noqa
                                          'Printer services are supported (int 17h)',  # noqa
                                          'CGA/mono video services are supported (int 10h)',  # noqa
                                          'ACPI is supported',
                                          'USB legacy is supported',
                                          'ATAPI Zip drive boot is supported',
                                          'BIOS boot specification is supported',  # noqa
                                          'Function key-initiated network boot is supported',  # noqa
                                          'Targeted content distribution is supported'],  # noqa
                      'Firmware Revision': '0.0',
                      'Handle': 'Handle 0x0005, DMI type 0, 24 bytes',
                      'ROM Size': '2048 kB',
                      'Release Date': '05/16/2011',
                      'Runtime Size': '64 kB',
                      'Vendor': 'Intel Corp.',
                      'Version': 'SOX5810J.86A.5561.2011.0516.2023'},
             'cpu': [{'Asset Tag': 'Not Specified',
                      'Current Speed': '3381 MHz',
                      'External Clock': '135 MHz',
                      'Family': 'Core i7',
                      'Flags': ['FPU (Floating-point unit on-chip)',
                                'VME (Virtual mode extension)',
                                'DE (Debugging extension)',
                                'PSE (Page size extension)',
                                'TSC (Time stamp counter)',
                                'MSR (Model specific registers)',
                                'PAE (Physical address extension)',
                                'MCE (Machine check exception)',
                                'CX8 (CMPXCHG8 instruction supported)',
                                'APIC (On-chip APIC hardware supported)',
                                'SEP (Fast system call)',
                                'MTRR (Memory type range registers)',
                                'PGE (Page global enable)',
                                'MCA (Machine check architecture)',
                                'CMOV (Conditional move instruction supported)',  # noqa
                                'PAT (Page attribute table)',
                                'PSE-36 (36-bit page size extension)',
                                'CLFSH (CLFLUSH instruction supported)',
                                'DS (Debug store)',
                                'ACPI (ACPI supported)',
                                'MMX (MMX technology supported)',
                                'FXSR (FXSAVE and FXSTOR instructions supported)',  # noqa
                                'SSE (Streaming SIMD extensions)',
                                'SSE2 (Streaming SIMD extensions 2)',
                                'SS (Self-snoop)',
                                'HTT (Multi-threading)',
                                'TM (Thermal monitor supported)',
                                'PBE (Pending break enabled)'],
                      'Handle': 'Handle 0x0000, DMI type 4, 35 bytes',
                      'ID': 'C2 06 02 00 FF FB EB BF',
                      'L1 Cache Handle': '0x0002',
                      'L2 Cache Handle': '0x0003',
                      'L3 Cache Handle': '0x0004',
                      'Manufacturer': 'Intel(R) Corporation',
                      'Max Speed': '4000 MHz',
                      'Part Number': 'Not Specified',
                      'Serial Number': 'Not Specified',
                      'Signature': 'Type 0, Family 6, Model 44, Stepping 2',
                      'Socket Designation': 'J1PR',
                      'Status': 'Populated, Enabled',
                      'Type': 'Central Processor',
                      'Upgrade': 'Socket LGA1366',
                      'Version': 'Intel(R) Core(TM) i7 CPU       X 980  @ 3.33GHz',  # noqa
                      'Voltage': '1.2 V'}],
             'memory': {'Error Correction Type': 'None',
                        'Error Information Handle': 'Not Provided',
                        'Location': 'System Board Or Motherboard',
                        'Maximum Capacity': '16 GB',
                        'Number Of Devices': 4,
                        'Use': 'System Memory',
                        'devices': [{'Array Handle': '0x0014',
                                     'Asset Tag': 'Unknown',
                                     'Bank Locator': 'CHAN A DIMM 0',
                                     'Data Width': '64 bits',
                                     'Error Information Handle': 'Not Provided',  # noqa
                                     'Form Factor': 'DIMM',
                                     'Handle': 'Handle 0x0016, DMI type 17, 27 bytes',  # noqa
                                     'Locator': 'J1MY',
                                     'Manufacturer': '0x0198',
                                     'Part Number': '0x393930353437312D3030312E4130304C4620',  # noqa
                                     'Serial Number': '0x700ECE90',
                                     'Set': 'None',
                                     'Size': '2048 MB',
                                     'Speed': '1333 MHz',
                                     'Total Width': '64 bits',
                                     'Type': 'DDR3',
                                     'Type Detail': 'Synchronous'},
                                    {'Array Handle': '0x0014',
                                     'Asset Tag': 'NO DIMM',
                                     'Bank Locator': 'CHAN A DIMM 1',
                                     'Data Width': 'Unknown',
                                     'Error Information Handle': 'Not Provided',  # noqa
                                     'Form Factor': 'DIMM',
                                     'Handle': 'Handle 0x0017, DMI type 17, 27 bytes',  # noqa
                                     'Locator': 'J2MY',
                                     'Manufacturer': 'NO DIMM',
                                     'Part Number': 'NO DIMM',
                                     'Serial Number': 'NO DIMM',
                                     'Set': 'None',
                                     'Size': 'No Module Installed',
                                     'Speed': '1333 MHz',
                                     'Total Width': 'Unknown',
                                     'Type': 'DDR3',
                                     'Type Detail': 'Synchronous'},
                                    {'Array Handle': '0x0014',
                                     'Asset Tag': 'Unknown',
                                     'Bank Locator': 'CHAN B DIMM 0',
                                     'Data Width': '64 bits',
                                     'Error Information Handle': 'Not Provided',  # noqa
                                     'Form Factor': 'DIMM',
                                     'Handle': 'Handle 0x0018, DMI type 17, 27 bytes',  # noqa
                                     'Locator': 'J3MY',
                                     'Manufacturer': '0x0198',
                                     'Part Number': '0x393930353437312D3030312E4130304C4620',  # noqa
                                     'Serial Number': '0x700ED090',
                                     'Set': 'None',
                                     'Size': '2048 MB',
                                     'Speed': '1333 MHz',
                                     'Total Width': '64 bits',
                                     'Type': 'DDR3',
                                     'Type Detail': 'Synchronous'},
                                    {'Array Handle': '0x0014',
                                     'Asset Tag': 'Unknown',
                                     'Bank Locator': 'CHAN C DIMM 0',
                                     'Data Width': '64 bits',
                                     'Error Information Handle': 'Not Provided',  # noqa
                                     'Form Factor': 'DIMM',
                                     'Handle': 'Handle 0x0019, DMI type 17, 27 bytes',  # noqa
                                     'Locator': 'J4MY',
                                     'Manufacturer': '0x0198',
                                     'Part Number': '0x393930353437312D3030312E4130304C4620',  # noqa
                                     'Serial Number': '0x6F0ED090',
                                     'Set': 'None',
                                     'Size': '2048 MB',
                                     'Speed': '1333 MHz',
                                     'Total Width': '64 bits',
                                     'Type': 'DDR3',
                                     'Type Detail': 'Synchronous'}]}}}


class TestCollectDmidecodeInfo(base.IronicAgentTest):
    def setUp(self):
        super(TestCollectDmidecodeInfo, self).setUp()
        self.data = {}
        self.failures = utils.AccumulatedFailures()

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_dmidecode_info_ok(self, mock_execute):
        mock_execute.return_value = DMI_DATA

        dmi_inspector.collect_dmidecode_info(self.data, None)

        for key in ('bios', 'memory', 'cpu'):
            self.assertTrue(self.data['dmi'][key])

        self.assertEqual(DMI_OUTPUT, self.data)

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
        inputdata = BIOS_DATA[0]
        expected = BIOS_OUTPUT

        ret = dmi_inspector.parse_dmi(inputdata)
        self.assertEqual(expected, ret)

    def test_parse_dmi_cpu(self):
        inputdata = CPU_DATA[0]
        expected = CPU_OUTPUT

        ret = dmi_inspector.parse_dmi(inputdata)
        self.assertEqual(expected, ret)

    def test_parse_dmi_memory(self):
        inputdata = MEMORY_DATA[0]
        expected = MEMORY_OUTPUT

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

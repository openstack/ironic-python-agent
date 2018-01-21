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

import binascii
import os
import time

from ironic_lib import disk_utils
import mock
import netifaces
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import units
import pyudev
from stevedore import extension

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import netutils
from ironic_python_agent.tests.unit import base
from ironic_python_agent import utils

CONF = cfg.CONF

CONF.import_opt('disk_wait_attempts', 'ironic_python_agent.config')
CONF.import_opt('disk_wait_delay', 'ironic_python_agent.config')

HDPARM_INFO_TEMPLATE = (
    '/dev/sda:\n'
    '\n'
    'ATA device, with non-removable media\n'
    '\tModel Number:       7 PIN  SATA FDM\n'
    '\tSerial Number:      20131210000000000023\n'
    '\tFirmware Revision:  SVN406\n'
    '\tTransport:          Serial, ATA8-AST, SATA 1.0a, SATA II Extensions, '
        'SATA Rev 2.5, SATA Rev 2.6, SATA Rev 3.0\n'
    'Standards: \n'
    '\tSupported: 9 8 7 6 5\n'
    '\tLikely used: 9\n'
    'Configuration: \n'
    '\tLogical\t\tmax\tcurrent\n'
    '\tcylinders\t16383\t16383\n'
    '\theads\t\t16\t16\n'
    '\tsectors/track\t63\t63\n'
    '\t--\n'
    '\tCHS current addressable sectors:   16514064\n'
    '\tLBA    user addressable sectors:   60579792\n'
    '\tLBA48  user addressable sectors:   60579792\n'
    '\tLogical  Sector size:                   512 bytes\n'
    '\tPhysical Sector size:                   512 bytes\n'
    '\tLogical Sector-0 offset:                  0 bytes\n'
    '\tdevice size with M = 1024*1024:       29579 MBytes\n'
    '\tdevice size with M = 1000*1000:       31016 MBytes (31 GB)\n'
    '\tcache/buffer size  = unknown\n'
    '\tForm Factor: 2.5 inch\n'
    '\tNominal Media Rotation Rate: Solid State Device\n'
    'Capabilities: \n'
    '\tLBA, IORDY(can be disabled)\n'
    '\tQueue depth: 32\n'
    '\tStandby timer values: spec\'d by Standard, no device specific '
        'minimum\n'
    '\tR/W multiple sector transfer: Max = 1\tCurrent = 1\n'
    '\tDMA: mdma0 mdma1 mdma2 udma0 udma1 udma2 udma3 udma4 *udma5\n'
    '\t     Cycle time: min=120ns recommended=120ns\n'
    '\tPIO: pio0 pio1 pio2 pio3 pio4\n'
    '\t     Cycle time: no flow control=120ns  IORDY flow '
        'control=120ns\n'
    'Commands/features: \n'
    '\tEnabled\tSupported:\n'
    '\t   *\tSMART feature set\n'
    '\t    \tSecurity Mode feature set\n'
    '\t   *\tPower Management feature set\n'
    '\t   *\tWrite cache\n'
    '\t   *\tLook-ahead\n'
    '\t   *\tHost Protected Area feature set\n'
    '\t   *\tWRITE_BUFFER command\n'
    '\t   *\tREAD_BUFFER command\n'
    '\t   *\tNOP cmd\n'
    '\t    \tSET_MAX security extension\n'
    '\t   *\t48-bit Address feature set\n'
    '\t   *\tDevice Configuration Overlay feature set\n'
    '\t   *\tMandatory FLUSH_CACHE\n'
    '\t   *\tFLUSH_CACHE_EXT\n'
    '\t   *\tWRITE_{DMA|MULTIPLE}_FUA_EXT\n'
    '\t   *\tWRITE_UNCORRECTABLE_EXT command\n'
    '\t   *\tGen1 signaling speed (1.5Gb/s)\n'
    '\t   *\tGen2 signaling speed (3.0Gb/s)\n'
    '\t   *\tGen3 signaling speed (6.0Gb/s)\n'
    '\t   *\tNative Command Queueing (NCQ)\n'
    '\t   *\tHost-initiated interface power management\n'
    '\t   *\tPhy event counters\n'
    '\t   *\tDMA Setup Auto-Activate optimization\n'
    '\t    \tDevice-initiated interface power management\n'
    '\t   *\tSoftware settings preservation\n'
    '\t    \tunknown 78[8]\n'
    '\t   *\tSMART Command Transport (SCT) feature set\n'
    '\t   *\tSCT Error Recovery Control (AC3)\n'
    '\t   *\tSCT Features Control (AC4)\n'
    '\t   *\tSCT Data Tables (AC5)\n'
    '\t   *\tData Set Management TRIM supported (limit 2 blocks)\n'
    'Security: \n'
    '\tMaster password revision code = 65534\n'
    '\t%(supported)s\n'
    '\t%(enabled)s\n'
    '\t%(locked)s\n'
    '\t%(frozen)s\n'
    '\tnot\texpired: security count\n'
    '\t%(enhanced_erase)s\n'
    '\t24min for SECURITY ERASE UNIT. 24min for ENHANCED SECURITY '
        'ERASE UNIT.\n'
    'Checksum: correct\n'
)  # noqa
# NOTE(jroll) noqa here is to dodge E131 (indent rules). Since this is a
# massive multi-line string (with specific whitespace formatting), it's easier
# for a human to parse it with indentations on line continuations. The other
# option would be to ignore the 79-character limit here. Ew.

BLK_DEVICE_TEMPLATE = (
    'KNAME="sda" MODEL="TinyUSB Drive" SIZE="3116853504" '
    'ROTA="0" TYPE="disk" SERIAL="123"\n'
    'KNAME="sdb" MODEL="Fastable SD131 7" SIZE="10737418240" '
    'ROTA="0" TYPE="disk"\n'
    'KNAME="sdc" MODEL="NWD-BLP4-1600   " SIZE="1765517033472" '
    ' ROTA="0" TYPE="disk"\n'
    'KNAME="sdd" MODEL="NWD-BLP4-1600   " SIZE="1765517033472" '
    ' ROTA="0" TYPE="disk"\n'
    'KNAME="loop0" MODEL="" SIZE="109109248" ROTA="1" TYPE="loop"'
)

# NOTE(pas-ha) largest device is 1 byte smaller than 4GiB
BLK_DEVICE_TEMPLATE_SMALL = (
    'KNAME="sda" MODEL="TinyUSB Drive" SIZE="3116853504" '
    'ROTA="0" TYPE="disk"\n'
    'KNAME="sdb" MODEL="AlmostBigEnough Drive" SIZE="4294967295" '
    'ROTA="0" TYPE="disk"'
)
BLK_DEVICE_TEMPLATE_SMALL_DEVICES = [
    hardware.BlockDevice(name='/dev/sda', model='TinyUSB Drive',
                         size=3116853504, rotational=False,
                         vendor="FooTastic"),
    hardware.BlockDevice(name='/dev/sdb', model='AlmostBigEnough Drive',
                         size=4294967295, rotational=False,
                         vendor="FooTastic"),
]

SHRED_OUTPUT_0_ITERATIONS_ZERO_FALSE = ()

SHRED_OUTPUT_1_ITERATION_ZERO_TRUE = (
    'shred: /dev/sda: pass 1/2 (random)...\n'
    'shred: /dev/sda: pass 1/2 (random)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 1/2 (random)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 1/2 (random)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 1/2 (random)...29GiB/29GiB 100%\n'
    'shred: /dev/sda: pass 2/2 (000000)...\n'
    'shred: /dev/sda: pass 2/2 (000000)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 2/2 (000000)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 2/2 (000000)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 2/2 (000000)...29GiB/29GiB 100%\n'
)

SHRED_OUTPUT_2_ITERATIONS_ZERO_FALSE = (
    'shred: /dev/sda: pass 1/2 (random)...\n'
    'shred: /dev/sda: pass 1/2 (random)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 1/2 (random)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 1/2 (random)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 1/2 (random)...29GiB/29GiB 100%\n'
    'shred: /dev/sda: pass 2/2 (random)...\n'
    'shred: /dev/sda: pass 2/2 (random)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 2/2 (random)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 2/2 (random)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 2/2 (random)...29GiB/29GiB 100%\n'
)


LSCPU_OUTPUT = """
Architecture:          x86_64
CPU op-mode(s):        32-bit, 64-bit
Byte Order:            Little Endian
CPU(s):                4
On-line CPU(s) list:   0-3
Thread(s) per core:    1
Core(s) per socket:    4
Socket(s):             1
NUMA node(s):          1
Vendor ID:             GenuineIntel
CPU family:            6
Model:                 45
Model name:            Intel(R) Xeon(R) CPU E5-2609 0 @ 2.40GHz
Stepping:              7
CPU MHz:               1290.000
CPU max MHz:           2400.0000
CPU min MHz:           1200.0000
BogoMIPS:              4800.06
Virtualization:        VT-x
L1d cache:             32K
L1i cache:             32K
L2 cache:              256K
L3 cache:              10240K
NUMA node0 CPU(s):     0-3
"""

LSCPU_OUTPUT_NO_MAX_MHZ = """
Architecture:          x86_64
CPU op-mode(s):        32-bit, 64-bit
Byte Order:            Little Endian
CPU(s):                12
On-line CPU(s) list:   0-11
Thread(s) per core:    2
Core(s) per socket:    6
Socket(s):             1
NUMA node(s):          1
Vendor ID:             GenuineIntel
CPU family:            6
Model:                 63
Model name:            Intel(R) Xeon(R) CPU E5-1650 v3 @ 3.50GHz
Stepping:              2
CPU MHz:               1794.433
BogoMIPS:              6983.57
Virtualization:        VT-x
L1d cache:             32K
L1i cache:             32K
L2 cache:              256K
L3 cache:              15360K
NUMA node0 CPU(s):     0-11
"""

# NOTE(dtanstur): flags list stripped down for sanity reasons
CPUINFO_FLAGS_OUTPUT = """
flags           : fpu vme de pse
"""

LSHW_JSON_OUTPUT = ("""
{
  "id": "fuzzypickles",
  "product": "ABC123 (GENERIC_SERVER)",
  "vendor": "GENERIC",
  "serial": "1234567",
  "width": 64,
  "capabilities": {
    "smbios-2.7": "SMBIOS version 2.7",
    "dmi-2.7": "DMI version 2.7",
    "vsyscall32": "32-bit processes"
  },
  "children": [
    {
      "id": "core",
      "description": "Motherboard",
      "product": "ABC123",
      "vendor": "GENERIC",
      "serial": "ABCDEFGHIJK",
      "children": [
        {
          "id": "memory",
          "class": "memory",
          "description": "System Memory",
          "units": "bytes",
          "size": 4294967296,
          "children": [
            {
              "id": "bank:0",
              "class": "memory",
              "physid": "0",
              "units": "bytes",
              "size": 2147483648,
              "width": 64,
              "clock": 1600000000
            },
            {
              "id": "bank:1",
              "class": "memory",
              "physid": "1"
            },
            {
              "id": "bank:2",
              "class": "memory",
              "physid": "2",
              "units": "bytes",
              "size": 1073741824,
              "width": 64,
              "clock": 1600000000
            },
            {
              "id": "bank:3",
              "class": "memory",
              "physid": "3",
              "units": "bytes",
              "size": 1073741824,
              "width": 64,
              "clock": 1600000000
            }
          ]
        },
        {
          "id": "cpu:0",
          "class": "processor",
          "claimed": true,
          "product": "Intel Xeon E312xx (Sandy Bridge)",
          "vendor": "Intel Corp.",
          "physid": "1",
          "businfo": "cpu@0",
          "width": 64,
          "capabilities": {
            "fpu": "mathematical co-processor",
            "fpu_exception": "FPU exceptions reporting",
            "wp": true,
            "mmx": "multimedia extensions (MMX)"
          }
        }
      ]
    },
    {
      "id": "network:0",
      "class": "network",
      "claimed": true,
      "description": "Ethernet interface",
      "physid": "1",
      "logicalname": "ovs-tap",
      "serial": "1c:90:c0:f9:4e:a1",
      "units": "bit/s",
      "size": 10000000000,
      "configuration": {
        "autonegotiation": "off",
        "broadcast": "yes",
        "driver": "veth",
        "driverversion": "1.0",
        "duplex": "full",
        "link": "yes",
        "multicast": "yes",
        "port": "twisted pair",
        "speed": "10Gbit/s"
      },
      "capabilities": {
        "ethernet": true,
        "physical": "Physical interface"
      }
    }
  ]
}
""", "")

SMARTCTL_NORMAL_OUTPUT = ("""
smartctl 6.2 2017-02-27 r4394 [x86_64-linux-3.10.0-693.21.1.el7.x86_64] (local build)
Copyright (C) 2002-13, Bruce Allen, Christian Franke, www.smartmontools.org

ATA Security is:  Disabled, NOT FROZEN [SEC1]
""")  # noqa

SMARTCTL_UNAVAILABLE_OUTPUT = ("""
smartctl 6.2 2017-02-27 r4394 [x86_64-linux-3.10.0-693.21.1.el7.x86_64] (local build)
Copyright (C) 2002-13, Bruce Allen, Christian Franke, www.smartmontools.org

ATA Security is:  Unavailable
""")  # noqa


class FakeHardwareManager(hardware.GenericHardwareManager):
    def __init__(self, hardware_support):
        self._hardware_support = hardware_support

    def evaluate_hardware_support(self):
        return self._hardware_support


class TestHardwareManagerLoading(base.IronicAgentTest):
    def setUp(self):
        super(TestHardwareManagerLoading, self).setUp()
        # In order to use ExtensionManager.make_test_instance() without
        # creating a new only-for-test codepath, we instantiate the test
        # instance outside of the test case in setUp, where we can access
        # make_test_instance() before it gets mocked. Inside of the test case
        # we set this as the return value of the mocked constructor, so we can
        # verify that the constructor is called correctly while still using a
        # more realistic ExtensionManager
        fake_ep = mock.Mock()
        fake_ep.module_name = 'fake'
        fake_ep.attrs = ['fake attrs']
        ext1 = extension.Extension(
            'fake_generic0', fake_ep, None,
            FakeHardwareManager(hardware.HardwareSupport.GENERIC))
        ext2 = extension.Extension(
            'fake_mainline0', fake_ep, None,
            FakeHardwareManager(hardware.HardwareSupport.MAINLINE))
        ext3 = extension.Extension(
            'fake_generic1', fake_ep, None,
            FakeHardwareManager(hardware.HardwareSupport.GENERIC))
        self.correct_hw_manager = ext2.obj
        self.fake_ext_mgr = extension.ExtensionManager.make_test_instance([
            ext1, ext2, ext3
        ])


@mock.patch.object(hardware, '_udev_settle', lambda *_: None)
class TestGenericHardwareManager(base.IronicAgentTest):
    def setUp(self):
        super(TestGenericHardwareManager, self).setUp()
        self.hardware = hardware.GenericHardwareManager()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244',
                     'driver_internal_info': {}}
        CONF.clear_override('disk_wait_attempts')
        CONF.clear_override('disk_wait_delay')

    def test_get_clean_steps(self):
        expected_clean_steps = [
            {
                'step': 'erase_devices',
                'priority': 10,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_devices_metadata',
                'priority': 99,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            }
        ]
        clean_steps = self.hardware.get_clean_steps(self.node, [])
        self.assertEqual(expected_clean_steps, clean_steps)

    @mock.patch('binascii.hexlify', autospec=True)
    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    def test_collect_lldp_data(self, mock_lldp_info, mock_hexlify):
        if_names = ['eth0', 'lo']
        mock_lldp_info.return_value = {if_names[0]: [
            (0, b''),
            (1, b'foo\x01'),
            (2, b'\x02bar')],
        }
        mock_hexlify.side_effect = [
            b'',
            b'666f6f01',
            b'02626172'
        ]
        expected_lldp_data = {
            'eth0': [
                (0, ''),
                (1, '666f6f01'),
                (2, '02626172')],
        }
        result = self.hardware.collect_lldp_data(if_names)
        self.assertEqual(True, if_names[0] in result)
        self.assertEqual(expected_lldp_data, result)

    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    def test_collect_lldp_data_netutils_exception(self, mock_lldp_info):
        if_names = ['eth0', 'lo']
        mock_lldp_info.side_effect = Exception('fake error')
        result = self.hardware.collect_lldp_data(if_names)
        expected_lldp_data = {}
        self.assertEqual(expected_lldp_data, result)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    @mock.patch('binascii.hexlify', autospec=True)
    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    def test_collect_lldp_data_decode_exception(self, mock_lldp_info,
                                                mock_hexlify, mock_log):
        if_names = ['eth0', 'lo']
        mock_lldp_info.return_value = {if_names[0]: [
            (0, b''),
            (1, b'foo\x01'),
            (2, b'\x02bar')],
        }
        mock_hexlify.side_effect = [
            b'',
            b'666f6f01',
            binascii.Error('fake_error')
        ]
        expected_lldp_data = {
            'eth0': [
                (0, ''),
                (1, '666f6f01')],
        }
        result = self.hardware.collect_lldp_data(if_names)
        mock_log.warning.assert_called_once()
        self.assertEqual(True, if_names[0] in result)
        self.assertEqual(expected_lldp_data, result)

    @mock.patch('ironic_python_agent.hardware._get_managers', autospec=True)
    @mock.patch('netifaces.ifaddresses', autospec=True)
    @mock.patch('os.listdir', autospec=True)
    @mock.patch('os.path.exists', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(netutils, 'interface_has_carrier', autospec=True)
    def test_list_network_interfaces(self,
                                     mock_has_carrier,
                                     mock_get_mac,
                                     mocked_execute,
                                     mocked_open,
                                     mocked_exists,
                                     mocked_listdir,
                                     mocked_ifaddresses,
                                     mocked_get_managers):
        mocked_get_managers.return_value = [hardware.GenericHardwareManager()]
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_ifaddresses.return_value = {
            netifaces.AF_INET: [{'addr': '192.168.1.2'}],
            netifaces.AF_INET6: [{'addr': 'fd00::101'}]
        }
        mocked_execute.return_value = ('em0\n', '')
        mock_get_mac.mock_has_carrier = True
        mock_get_mac.return_value = '00:0c:29:8c:11:b1'
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)

    @mock.patch('ironic_python_agent.hardware._get_managers', autospec=True)
    @mock.patch('netifaces.ifaddresses', autospec=True)
    @mock.patch('os.listdir', autospec=True)
    @mock.patch('os.path.exists', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(netutils, 'interface_has_carrier', autospec=True)
    def test_list_network_interfaces_with_biosdevname(self,
                                                      mock_has_carrier,
                                                      mock_get_mac,
                                                      mocked_execute,
                                                      mocked_open,
                                                      mocked_exists,
                                                      mocked_listdir,
                                                      mocked_ifaddresses,
                                                      mocked_get_managers):
        mocked_get_managers.return_value = [hardware.GenericHardwareManager()]
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_ifaddresses.return_value = {
            netifaces.AF_INET: [{'addr': '192.168.1.2'}],
            netifaces.AF_INET6: [{'addr': 'fd00::101'}]
        }
        mocked_execute.return_value = ('em0\n', '')
        mock_get_mac.return_value = '00:0c:29:8c:11:b1'
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bios_given_nic_name_ok(self, mock_execute):
        interface_name = 'eth0'
        mock_execute.return_value = ('em0\n', '')
        result = self.hardware.get_bios_given_nic_name(interface_name)
        self.assertEqual('em0', result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bios_given_nic_name_oserror(self, mock_execute):
        interface_name = 'eth0'
        mock_execute.side_effect = OSError()
        result = self.hardware.get_bios_given_nic_name(interface_name)
        self.assertIsNone(result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(hardware, 'LOG', autospec=True)
    def test_get_bios_given_nic_name_process_exec_err4(self, mock_log,
                                                       mock_execute):
        interface_name = 'eth0'
        mock_execute.side_effect = [
            processutils.ProcessExecutionError(exit_code=4)]

        result = self.hardware.get_bios_given_nic_name(interface_name)

        mock_log.info.assert_called_once_with(
            'The system is a virtual machine, so biosdevname utility does '
            'not provide names for virtual NICs.')
        self.assertIsNone(result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(hardware, 'LOG', autospec=True)
    def test_get_bios_given_nic_name_process_exec_err3(self, mock_log,
                                                       mock_execute):
        interface_name = 'eth0'
        mock_execute.side_effect = [
            processutils.ProcessExecutionError(exit_code=3)]

        result = self.hardware.get_bios_given_nic_name(interface_name)

        mock_log.warning.assert_called_once_with(
            'Biosdevname returned exit code %s', 3)
        self.assertIsNone(result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch('ironic_python_agent.hardware._get_managers', autospec=True)
    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    @mock.patch('netifaces.ifaddresses', autospec=True)
    @mock.patch('os.listdir', autospec=True)
    @mock.patch('os.path.exists', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(netutils, 'interface_has_carrier', autospec=True)
    def test_list_network_interfaces_with_lldp(self,
                                               mock_has_carrier,
                                               mock_get_mac,
                                               mocked_execute,
                                               mocked_open,
                                               mocked_exists,
                                               mocked_listdir,
                                               mocked_ifaddresses,
                                               mocked_lldp_info,
                                               mocked_get_managers):
        mocked_get_managers.return_value = [hardware.GenericHardwareManager()]
        CONF.set_override('collect_lldp', True)
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_ifaddresses.return_value = {
            netifaces.AF_INET: [{'addr': '192.168.1.2'}],
            netifaces.AF_INET6: [{'addr': 'fd00::101'}]
        }
        mocked_lldp_info.return_value = {'eth0': [
            (0, b''),
            (1, b'\x04\x88Z\x92\xecTY'),
            (2, b'\x05Ethernet1/18'),
            (3, b'\x00x')]
        }
        mock_has_carrier.return_value = True
        mock_get_mac.return_value = '00:0c:29:8c:11:b1'
        mocked_execute.return_value = ('em0\n', '')
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        expected_lldp_info = [
            (0, ''),
            (1, '04885a92ec5459'),
            (2, '0545746865726e6574312f3138'),
            (3, '0078'),
        ]
        self.assertEqual(expected_lldp_info, interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)

    @mock.patch.object(netutils, 'interface_has_carrier', autospec=True)
    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch('ironic_python_agent.hardware._get_managers', autospec=True)
    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    @mock.patch('netifaces.ifaddresses', autospec=True)
    @mock.patch('os.listdir', autospec=True)
    @mock.patch('os.path.exists', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_network_interfaces_with_lldp_error(
            self, mocked_execute, mocked_open, mocked_exists, mocked_listdir,
            mocked_ifaddresses, mocked_lldp_info, mocked_get_managers,
            mock_get_mac, mock_has_carrier):
        mocked_get_managers.return_value = [hardware.GenericHardwareManager()]
        CONF.set_override('collect_lldp', True)
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_ifaddresses.return_value = {
            netifaces.AF_INET: [{'addr': '192.168.1.2'}],
            netifaces.AF_INET6: [{'addr': 'fd00::101'}]
        }
        mocked_lldp_info.side_effect = Exception('Boom!')
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        mock_get_mac.return_value = '00:0c:29:8c:11:b1'
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)

    @mock.patch('ironic_python_agent.hardware._get_managers', autospec=True)
    @mock.patch('netifaces.ifaddresses', autospec=True)
    @mock.patch('os.listdir', autospec=True)
    @mock.patch('os.path.exists', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(netutils, 'interface_has_carrier', autospec=True)
    def test_list_network_interfaces_no_carrier(self,
                                                mock_has_carrier,
                                                mock_get_mac,
                                                mocked_execute,
                                                mocked_open,
                                                mocked_exists,
                                                mocked_listdir,
                                                mocked_ifaddresses,
                                                mocked_get_managers):

        mocked_get_managers.return_value = [hardware.GenericHardwareManager()]
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = [OSError('boom')]
        mocked_ifaddresses.return_value = {
            netifaces.AF_INET: [{'addr': '192.168.1.2'}],
            netifaces.AF_INET6: [{'addr': 'fd00::101'}]
        }
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = False
        mock_get_mac.return_value = '00:0c:29:8c:11:b1'
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertFalse(interfaces[0].has_carrier)
        self.assertIsNone(interfaces[0].vendor)
        self.assertEqual('em0', interfaces[0].biosdevname)

    @mock.patch('ironic_python_agent.hardware._get_managers', autospec=True)
    @mock.patch('netifaces.ifaddresses', autospec=True)
    @mock.patch('os.listdir', autospec=True)
    @mock.patch('os.path.exists', autospec=True)
    @mock.patch('six.moves.builtins.open', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(netutils, 'interface_has_carrier', autospec=True)
    def test_list_network_interfaces_with_vendor_info(self,
                                                      mock_has_carrier,
                                                      mock_get_mac,
                                                      mocked_execute,
                                                      mocked_open,
                                                      mocked_exists,
                                                      mocked_listdir,
                                                      mocked_ifaddresses,
                                                      mocked_get_managers):
        mocked_get_managers.return_value = [hardware.GenericHardwareManager()]
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        mac = '00:0c:29:8c:11:b1'
        read_mock.side_effect = ['0x15b3\n', '0x1014\n']
        mocked_ifaddresses.return_value = {
            netifaces.AF_INET: [{'addr': '192.168.1.2'}],
            netifaces.AF_INET6: [{'addr': 'fd00::101'}]
        }
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        mock_get_mac.return_value = mac
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual(mac, interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('0x15b3', interfaces[0].vendor)
        self.assertEqual('0x1014', interfaces[0].product)
        self.assertEqual('em0', interfaces[0].biosdevname)

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device(self, mocked_execute, mock_cached_node,
                                   mocked_listdir, mocked_readlink):
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mock_cached_node.return_value = None
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        self.assertEqual('/dev/sdb', self.hardware.get_os_install_device())
        mocked_execute.assert_called_once_with(
            'lsblk', '-Pbdi', '-oKNAME,MODEL,SIZE,ROTA,TYPE',
            check_exit_code=[0])
        mock_cached_node.assert_called_once_with()

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device_fails(self, mocked_execute,
                                         mock_cached_node,
                                         mocked_listdir, mocked_readlink):
        """Fail to find device >=4GB w/o root device hints"""
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mock_cached_node.return_value = None
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE_SMALL, '')
        ex = self.assertRaises(errors.DeviceNotFound,
                               self.hardware.get_os_install_device)
        mocked_execute.assert_called_once_with(
            'lsblk', '-Pbdi', '-oKNAME,MODEL,SIZE,ROTA,TYPE',
            check_exit_code=[0])
        self.assertIn(str(4 * units.Gi), ex.details)
        mock_cached_node.assert_called_once_with()

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def _get_os_install_device_root_device_hints(self, hints, expected_device,
                                                 mock_cached_node, mock_dev):
        mock_cached_node.return_value = {'properties': {'root_device': hints},
                                         'uuid': 'node1'}
        model = 'fastable sd131 7'
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 wwn_with_extension='wwn0ven0',
                                 wwn_vendor_extension='ven0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model=model,
                                 size=10737418240,
                                 rotational=True,
                                 vendor='fake-vendor',
                                 wwn='fake-wwn',
                                 wwn_with_extension='fake-wwnven0',
                                 wwn_vendor_extension='ven0',
                                 serial='fake-serial',
                                 by_path='/dev/disk/by-path/1:0:0:0'),
        ]

        self.assertEqual(expected_device,
                         self.hardware.get_os_install_device())
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with()

    def test_get_os_install_device_root_device_hints_model(self):
        self._get_os_install_device_root_device_hints(
            {'model': 'fastable sd131 7'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_wwn(self):
        self._get_os_install_device_root_device_hints(
            {'wwn': 'wwn0'}, '/dev/sda')

    def test_get_os_install_device_root_device_hints_serial(self):
        self._get_os_install_device_root_device_hints(
            {'serial': 'serial0'}, '/dev/sda')

    def test_get_os_install_device_root_device_hints_size(self):
        self._get_os_install_device_root_device_hints(
            {'size': 10}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_size_str(self):
        self._get_os_install_device_root_device_hints(
            {'size': '10'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_size_not_int(self):
        self.assertRaises(errors.DeviceNotFound,
                          self._get_os_install_device_root_device_hints,
                          {'size': 'not-int'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_vendor(self):
        self._get_os_install_device_root_device_hints(
            {'vendor': 'fake-vendor'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_name(self):
        self._get_os_install_device_root_device_hints(
            {'name': '/dev/sdb'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_rotational(self):
        for value in (True, 'true', 'on', 'y', 'yes'):
            self._get_os_install_device_root_device_hints(
                {'rotational': value}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_by_path(self):
        self._get_os_install_device_root_device_hints(
            {'by_path': '/dev/disk/by-path/1:0:0:0'}, '/dev/sdb')

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_root_device_hints_no_device_found(
            self, mock_cached_node, mock_dev):
        model = 'fastable sd131 7'
        mock_cached_node.return_value = {
            'properties': {
                'root_device': {
                    'model': model,
                    'wwn': 'fake-wwn',
                    'serial': 'fake-serial',
                    'vendor': 'fake-vendor',
                    'size': 10}}}
        # Model is different here
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Another Model',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='fake-vendor',
                                 wwn='fake-wwn',
                                 serial='fake-serial'),
        ]
        self.assertRaises(errors.DeviceNotFound,
                          self.hardware.get_os_install_device)
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with()

    def test__get_device_info(self):
        fileobj = mock.mock_open(read_data='fake-vendor')
        with mock.patch(
                'six.moves.builtins.open', fileobj, create=True) as mock_open:
            vendor = hardware._get_device_info(
                '/dev/sdfake', 'block', 'vendor')
            mock_open.assert_called_once_with(
                '/sys/class/block/sdfake/device/vendor', 'r')
            self.assertEqual('fake-vendor', vendor)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus(self, mocked_execute):
        mocked_execute.side_effect = [
            (LSCPU_OUTPUT, ''),
            (CPUINFO_FLAGS_OUTPUT, '')
        ]

        cpus = self.hardware.get_cpus()
        self.assertEqual('Intel(R) Xeon(R) CPU E5-2609 0 @ 2.40GHz',
                         cpus.model_name)
        self.assertEqual('2400.0000', cpus.frequency)
        self.assertEqual(4, cpus.count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual(['fpu', 'vme', 'de', 'pse'], cpus.flags)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus2(self, mocked_execute):
        mocked_execute.side_effect = [
            (LSCPU_OUTPUT_NO_MAX_MHZ, ''),
            (CPUINFO_FLAGS_OUTPUT, '')
        ]

        cpus = self.hardware.get_cpus()
        self.assertEqual('Intel(R) Xeon(R) CPU E5-1650 v3 @ 3.50GHz',
                         cpus.model_name)
        self.assertEqual('1794.433', cpus.frequency)
        self.assertEqual(12, cpus.count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual(['fpu', 'vme', 'de', 'pse'], cpus.flags)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus_no_flags(self, mocked_execute):
        mocked_execute.side_effect = [
            (LSCPU_OUTPUT, ''),
            processutils.ProcessExecutionError()
        ]

        cpus = self.hardware.get_cpus()
        self.assertEqual('Intel(R) Xeon(R) CPU E5-2609 0 @ 2.40GHz',
                         cpus.model_name)
        self.assertEqual('2400.0000', cpus.frequency)
        self.assertEqual(4, cpus.count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual([], cpus.flags)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus_illegal_flags(self, mocked_execute):
        mocked_execute.side_effect = [
            (LSCPU_OUTPUT, ''),
            ('I am not a flag', '')
        ]

        cpus = self.hardware.get_cpus()
        self.assertEqual('Intel(R) Xeon(R) CPU E5-2609 0 @ 2.40GHz',
                         cpus.model_name)
        self.assertEqual('2400.0000', cpus.frequency)
        self.assertEqual(4, cpus.count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual([], cpus.flags)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_psutil(self, mocked_execute, mocked_psutil):
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mocked_execute.return_value = LSHW_JSON_OUTPUT
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertEqual(4096, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_psutil_exception(self, mocked_execute, mocked_psutil):
        mocked_execute.return_value = LSHW_JSON_OUTPUT
        mocked_psutil.side_effect = AttributeError()
        mem = self.hardware.get_memory()

        self.assertIsNone(mem.total)
        self.assertEqual(4096, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_lshw_exception(self, mocked_execute, mocked_psutil):
        mocked_execute.side_effect = OSError()
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertIsNone(mem.physical_mb)

    def test_list_hardware_info(self):
        self.hardware.list_network_interfaces = mock.Mock()
        self.hardware.list_network_interfaces.return_value = [
            hardware.NetworkInterface('eth0', '00:0c:29:8c:11:b1'),
            hardware.NetworkInterface('eth1', '00:0c:29:8c:11:b2'),
        ]

        self.hardware.get_cpus = mock.Mock()
        self.hardware.get_cpus.return_value = hardware.CPU(
            'Awesome CPU x14 9001',
            9001,
            14,
            'x86_64')

        self.hardware.get_memory = mock.Mock()
        self.hardware.get_memory.return_value = hardware.Memory(1017012)

        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        self.hardware.get_boot_info = mock.Mock()
        self.hardware.get_boot_info.return_value = hardware.BootInfo(
            current_boot_mode='bios', pxe_interface='boot:if')

        self.hardware.get_bmc_address = mock.Mock()
        self.hardware.get_system_vendor_info = mock.Mock()

        hardware_info = self.hardware.list_hardware_info()
        self.assertEqual(self.hardware.get_memory(), hardware_info['memory'])
        self.assertEqual(self.hardware.get_cpus(), hardware_info['cpu'])
        self.assertEqual(self.hardware.list_block_devices(),
                         hardware_info['disks'])
        self.assertEqual(self.hardware.list_network_interfaces(),
                         hardware_info['interfaces'])
        self.assertEqual(self.hardware.get_boot_info(),
                         hardware_info['boot'])

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_list_block_devices(self, list_mock):
        device = hardware.BlockDevice('/dev/hdaa', 'small', 65535, False)
        list_mock.return_value = [device]
        devices = self.hardware.list_block_devices()

        self.assertEqual([device], devices)

        list_mock.assert_called_once_with()

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Device, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device(self, mocked_execute, mocked_udev,
                                   mocked_dev_vendor, mock_listdir,
                                   mock_readlink):
        by_path_map = {
            '/dev/disk/by-path/1:0:0:0': '../../dev/sda',
            '/dev/disk/by-path/1:0:0:1': '../../dev/sdb',
            '/dev/disk/by-path/1:0:0:2': '../../dev/sdc',
            # pretend that the by-path link to ../../dev/sdd is missing
        }
        mock_readlink.side_effect = lambda x, m=by_path_map: m[x]
        mock_listdir.return_value = [os.path.basename(x)
                                     for x in sorted(by_path_map)]
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        mocked_udev.side_effect = pyudev.DeviceNotFoundError()
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:1'),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:2'),
            hardware.BlockDevice(name='/dev/sdd',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0'),
        ]

        self.assertEqual(4, len(devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'vendor', 'serial', 'hctl']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))
        expected_calls = [mock.call('/sys/block/%s/device/scsi_device' % dev)
                          for dev in ('sda', 'sdb', 'sdc', 'sdd')]
        mock_listdir.assert_has_calls(expected_calls)

        expected_calls = [mock.call('/dev/disk/by-path/1:0:0:%d' % dev)
                          for dev in range(3)]
        mock_readlink.assert_has_calls(expected_calls)

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Device, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device_udev_17(self, mocked_execute, mocked_udev,
                                           mocked_dev_vendor, mocked_listdir,
                                           mocked_readlink):
        # test compatibility with pyudev < 0.18
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        mocked_udev.side_effect = OSError()
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        self.assertEqual(4, len(devices))

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Device, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device_hctl_fail(self, mocked_execute, mocked_udev,
                                             mocked_dev_vendor,
                                             mocked_listdir):
        mocked_listdir.side_effect = (OSError, OSError, IndexError)
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE_SMALL, '')
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        self.assertEqual(2, len(devices))
        expected_calls = [
            mock.call('/dev/disk/by-path'),
            mock.call('/sys/block/sda/device/scsi_device'),
            mock.call('/sys/block/sdb/device/scsi_device')
        ]
        self.assertEqual(expected_calls, mocked_listdir.call_args_list)

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Device, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device_with_udev(self, mocked_execute, mocked_udev,
                                             mocked_dev_vendor, mocked_listdir,
                                             mocked_readlink):
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        mocked_udev.side_effect = iter([
            {'ID_WWN': 'wwn%d' % i, 'ID_SERIAL_SHORT': 'serial%d' % i,
             'ID_WWN_WITH_EXTENSION': 'wwn-ext%d' % i,
             'ID_WWN_VENDOR_EXTENSION': 'wwn-vendor-ext%d' % i}
            for i in range(4)
        ])
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 wwn_with_extension='wwn-ext0',
                                 wwn_vendor_extension='wwn-vendor-ext0',
                                 serial='serial0',
                                 hctl='1:0:0:0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn1',
                                 wwn_with_extension='wwn-ext1',
                                 wwn_vendor_extension='wwn-vendor-ext1',
                                 serial='serial1',
                                 hctl='1:0:0:0'),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn2',
                                 wwn_with_extension='wwn-ext2',
                                 wwn_vendor_extension='wwn-vendor-ext2',
                                 serial='serial2',
                                 hctl='1:0:0:0'),
            hardware.BlockDevice(name='/dev/sdd',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn3',
                                 wwn_with_extension='wwn-ext3',
                                 wwn_vendor_extension='wwn-vendor-ext3',
                                 serial='serial3',
                                 hctl='1:0:0:0')
        ]

        self.assertEqual(4, len(expected_devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'vendor', 'serial', 'wwn_with_extension',
                         'wwn_vendor_extension', 'hctl']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))
        expected_calls = [mock.call('/sys/block/%s/device/scsi_device' % dev)
                          for dev in ('sda', 'sdb', 'sdc', 'sdd')]
        mocked_listdir.assert_has_calls(expected_calls)

    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test_erase_devices(self, mocked_dispatch):
        mocked_dispatch.return_value = 'erased device'

        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        expected = {'/dev/hdaa': 'erased device', '/dev/sdj': 'erased device'}

        result = self.hardware.erase_devices({}, [])

        self.assertEqual(expected, result)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_success(self, mocked_execute):
        mocked_execute.side_effect = [
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            ('', ''),
            ('', ''),
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('hdparm', '--user-master', 'u', '--security-set-pass',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '--user-master', 'u', '--security-erase',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '-I', '/dev/sda'),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_success_no_smartctl(self, mocked_execute):
        mocked_execute.side_effect = [
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
            OSError('boom'),
            ('', ''),
            ('', ''),
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('hdparm', '--user-master', 'u', '--security-set-pass',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '--user-master', 'u', '--security-erase',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '-I', '/dev/sda'),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_nosecurity_shred(self, mocked_execute):
        hdparm_output = HDPARM_INFO_TEMPLATE.split('\nSecurity:')[0]

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_notsupported_shred(self, mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=False, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_smartctl_unsupported_shred(self,
                                                           mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_smartctl_fails_security_fallback_to_shred(
            self, mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            processutils.ProcessExecutionError(),
            (SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_uses_internal_info(self, mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=False, enabled=False, frozen=False, enhanced_erase=False)

        info = self.node['driver_internal_info']
        info['agent_erase_devices_iterations'] = 2
        info['agent_erase_devices_zeroize'] = False

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            (SHRED_OUTPUT_2_ITERATIONS_ZERO_FALSE, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--verbose',
                      '--iterations', '2', '/dev/sda')
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_0_pass_no_zeroize(self, mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=False, enabled=False, frozen=False, enhanced_erase=False)

        info = self.node['driver_internal_info']
        info['agent_erase_devices_iterations'] = 0
        info['agent_erase_devices_zeroize'] = False

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (SHRED_OUTPUT_0_ITERATIONS_ZERO_FALSE, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--verbose',
                      '--iterations', '0', '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    def test_erase_block_device_virtual_media(self, vm_mock):
        vm_mock.return_value = True
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        vm_mock.assert_called_once_with(self.hardware, block_device)

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__is_virtual_media_device_exists(self, mocked_exists,
                                             mocked_link):
        mocked_exists.return_value = True
        mocked_link.return_value = '../../sda'
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._is_virtual_media_device(block_device)
        self.assertTrue(res)
        mocked_exists.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')
        mocked_link.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__is_virtual_media_device_exists_no_match(self, mocked_exists,
                                                      mocked_link):
        mocked_exists.return_value = True
        mocked_link.return_value = '../../sdb'
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._is_virtual_media_device(block_device)
        self.assertFalse(res)
        mocked_exists.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')
        mocked_link.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__is_virtual_media_device_path_doesnt_exist(self, mocked_exists,
                                                        mocked_link):
        mocked_exists.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._is_virtual_media_device(block_device)
        self.assertFalse(res)
        mocked_exists.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')
        self.assertFalse(mocked_link.called)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_fail_oserror(self, mocked_execute):
        mocked_execute.side_effect = OSError
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._shred_block_device(self.node, block_device)
        self.assertFalse(res)
        mocked_execute.assert_called_once_with(
            'shred', '--force', '--zero', '--verbose', '--iterations', '1',
            '/dev/sda')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_fail_processerror(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._shred_block_device(self.node, block_device)
        self.assertFalse(res)
        mocked_execute.assert_called_once_with(
            'shred', '--force', '--zero', '--verbose', '--iterations', '1',
            '/dev/sda')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_security_unlock_fallback_pass(
            self, mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True
        )
        hdparm_output_unlocked = create_hdparm_info(
            supported=True, enabled=True, frozen=False, enhanced_erase=False)
        hdparm_output_not_enabled = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)
        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            processutils.ProcessExecutionError(),  # NULL fails to unlock
            (hdparm_output, ''),  # recheck security lines
            None,  # security unlock with ""
            (hdparm_output_unlocked, ''),
            '',
            (hdparm_output_not_enabled, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)

        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', '', '/dev/sda')

    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_security_enabled(
            self, mocked_execute, mock_shred):
        # Tests that an exception is thrown if all of the recovery passwords
        # fail to unlock the device without throwing exception
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            None,
            (hdparm_output, ''),
            None,
            (hdparm_output, ''),
            None,
            (hdparm_output, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.erase_block_device,
            self.node,
            block_device)
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', '', '/dev/sda')
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', 'NULL', '/dev/sda')
        self.assertFalse(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_security_enabled_unlock_attempt(
            self, mocked_execute, mock_shred):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True)
        hdparm_output_not_enabled = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            '',
            (hdparm_output_not_enabled, ''),
            '',
            '',
            (hdparm_output_not_enabled, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)
        self.assertFalse(mock_shred.called)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__ata_erase_security_enabled_unlock_exception(
            self, mocked_execute):
        # test that an exception is thrown when security unlock fails with
        # ProcessExecutionError
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True)
        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            processutils.ProcessExecutionError(),
            (hdparm_output, ''),
            processutils.ProcessExecutionError(),
            (hdparm_output, ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._ata_erase,
                          block_device)
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', '', '/dev/sda')
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', 'NULL', '/dev/sda')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__ata_erase_security_enabled_set_password_exception(
            self, mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            processutils.ProcessExecutionError()
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._ata_erase,
                          block_device)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__ata_erase_security_erase_exec_exception(
            self, mocked_execute):
        # Exception on security erase
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)
        hdparm_unlocked_output = create_hdparm_info(
            supported=True, locked=True, frozen=False, enhanced_erase=False)
        mocked_execute.side_effect = [
            (hdparm_output, '', '-1'),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            '',  # security-set-pass
            processutils.ProcessExecutionError(),  # security-erase
            (hdparm_unlocked_output, '', '-1'),
            '',  # attempt security unlock
            (hdparm_output, '', '-1')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._ata_erase,
                          block_device)

    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_frozen(self, mocked_execute, mock_shred):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=True, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SMARTCTL_NORMAL_OUTPUT, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.erase_block_device,
            self.node,
            block_device)
        self.assertFalse(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_failed(self, mocked_execute, mock_shred):
        hdparm_output_before = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        # If security mode remains enabled after the erase, it is indicative
        # of a failed erase.
        hdparm_output_after = create_hdparm_info(
            supported=True, enabled=True, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output_before, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            ('', ''),
            ('', ''),
            (hdparm_output_after, ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.erase_block_device,
            self.node,
            block_device)
        self.assertFalse(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_failed_continued(
            self, mocked_execute, mock_shred):

        info = self.node['driver_internal_info']
        info['agent_continue_if_ata_erase_failed'] = True

        hdparm_output_before = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        # If security mode remains enabled after the erase, it is indicative
        # of a failed erase.
        hdparm_output_after = create_hdparm_info(
            supported=True, enabled=True, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output_before, ''),
            (SMARTCTL_NORMAL_OUTPUT, ''),
            ('', ''),
            ('', ''),
            (hdparm_output_after, ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)
        self.assertTrue(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_erase_disabled(
            self, mocked_execute, mock_shred):

        info = self.node['driver_internal_info']
        info['agent_enable_ata_secure_erase'] = False

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)
        self.assertTrue(mock_shred.called)
        self.assertFalse(mocked_execute.called)

    def test_normal_vs_enhanced_security_erase(self):
        @mock.patch.object(utils, 'execute', autospec=True)
        def test_security_erase_option(test_case,
                                       enhanced_erase,
                                       expected_option,
                                       mocked_execute):
            mocked_execute.side_effect = [
                (create_hdparm_info(
                    supported=True, enabled=False, frozen=False,
                    enhanced_erase=enhanced_erase), ''),
                (SMARTCTL_NORMAL_OUTPUT, ''),
                ('', ''),
                ('', ''),
                (create_hdparm_info(
                    supported=True, enabled=False, frozen=False,
                    enhanced_erase=enhanced_erase), ''),
            ]

            block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                                True)
            test_case.hardware.erase_block_device(self.node, block_device)
            mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                           expected_option,
                                           'NULL', '/dev/sda')

        test_security_erase_option(
            self, True, '--security-erase-enhanced')
        test_security_erase_option(
            self, False, '--security-erase')

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
    def test_erase_devices_metadata(
            self, mock_metadata, mock_list_devs, mock__is_vmedia):
        block_devices = [
            hardware.BlockDevice('/dev/sr0', 'vmedia', 12345, True),
            hardware.BlockDevice('/dev/sda', 'small', 65535, False),
        ]
        mock_list_devs.return_value = block_devices
        mock__is_vmedia.side_effect = (True, False)

        self.hardware.erase_devices_metadata(self.node, [])
        mock_metadata.assert_called_once_with(
            '/dev/sda', self.node['uuid'])
        mock_list_devs.assert_called_once_with(mock.ANY)
        mock__is_vmedia.assert_has_calls([
            mock.call(mock.ANY, block_devices[0]),
            mock.call(mock.ANY, block_devices[1])
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
    def test_erase_devices_metadata_error(
            self, mock_metadata, mock_list_devs, mock__is_vmedia):
        block_devices = [
            hardware.BlockDevice('/dev/sda', 'small', 65535, False),
            hardware.BlockDevice('/dev/sdb', 'big', 10737418240, True),
        ]
        mock__is_vmedia.return_value = False
        mock_list_devs.return_value = block_devices
        # Simulate /dev/sda failing and /dev/sdb succeeding
        error_output = 'Booo00000ooommmmm'
        mock_metadata.side_effect = (
            processutils.ProcessExecutionError(error_output),
            None,
        )

        self.assertRaisesRegex(errors.BlockDeviceEraseError, error_output,
                               self.hardware.erase_devices_metadata,
                               self.node, [])
        # Assert all devices are erased independent if one of them
        # failed previously
        mock_metadata.assert_has_calls([
            mock.call('/dev/sda', self.node['uuid']),
            mock.call('/dev/sdb', self.node['uuid']),
        ])
        mock_list_devs.assert_called_once_with(mock.ANY)
        mock__is_vmedia.assert_has_calls([
            mock.call(mock.ANY, block_devices[0]),
            mock.call(mock.ANY, block_devices[1])
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address(self, mocked_execute):
        mocked_execute.return_value = '192.1.2.3\n', ''
        self.assertEqual('192.1.2.3', self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_virt(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        self.assertIsNone(self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_zeroed(self, mocked_execute):
        mocked_execute.return_value = '0.0.0.0\n', ''
        self.assertEqual('0.0.0.0', self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_invalid(self, mocked_execute):
        # In case of invalid lan channel, stdout is empty and the error
        # on stderr is "Invalid channel"
        mocked_execute.return_value = '\n', 'Invalid channel: 55'
        self.assertEqual('0.0.0.0', self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_random_error(self, mocked_execute):
        mocked_execute.return_value = '192.1.2.3\n', 'Random error message'
        self.assertEqual('192.1.2.3', self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_iterate_channels(self, mocked_execute):
        # For channel 1 we simulate unconfigured IP
        # and for any other we return a correct IP address
        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print 1"):
                return '', 'Invalid channel 1\n'
            elif args[0].startswith("ipmitool lan print 2"):
                return '0.0.0.0\n', ''
            elif args[0].startswith("ipmitool lan print 3"):
                return 'meow', ''
            else:
                return '192.1.2.3\n', ''
        mocked_execute.side_effect = side_effect
        self.assertEqual('192.1.2.3', self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_not_available(self, mocked_execute):
        mocked_execute.return_value = '', ''
        self.assertEqual('0.0.0.0', self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_system_vendor_info(self, mocked_execute):
        mocked_execute.return_value = LSHW_JSON_OUTPUT
        vendor_info = self.hardware.get_system_vendor_info()
        self.assertEqual('ABC123 (GENERIC_SERVER)', vendor_info.product_name)
        self.assertEqual('1234567', vendor_info.serial_number)
        self.assertEqual('GENERIC', vendor_info.manufacturer)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_system_vendor_info_failure(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        vendor_info = self.hardware.get_system_vendor_info()
        self.assertEqual('', vendor_info.product_name)
        self.assertEqual('', vendor_info.serial_number)
        self.assertEqual('', vendor_info.manufacturer)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_os_install_device', autospec=True)
    @mock.patch.object(hardware, '_check_for_iscsi', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_evaluate_hw_waits_for_disks(
            self, mocked_sleep, mocked_check_for_iscsi, mocked_get_inst_dev):
        mocked_get_inst_dev.side_effect = [
            errors.DeviceNotFound('boom'),
            None
        ]

        result = self.hardware.evaluate_hardware_support()

        self.assertTrue(mocked_check_for_iscsi.called)
        self.assertEqual(hardware.HardwareSupport.GENERIC, result)
        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(2, mocked_get_inst_dev.call_count)
        mocked_sleep.assert_called_once_with(CONF.disk_wait_delay)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_os_install_device', autospec=True)
    @mock.patch.object(hardware, '_check_for_iscsi', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_evaluate_hw_no_wait_for_disks(
            self, mocked_sleep, mocked_check_for_iscsi, mocked_get_inst_dev,
            mocked_log):
        CONF.set_override('disk_wait_attempts', '0')

        result = self.hardware.evaluate_hardware_support()

        self.assertTrue(mocked_check_for_iscsi.called)
        self.assertEqual(hardware.HardwareSupport.GENERIC, result)
        self.assertFalse(mocked_get_inst_dev.called)
        self.assertFalse(mocked_sleep.called)
        self.assertFalse(mocked_log.called)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    @mock.patch.object(hardware, '_check_for_iscsi', mock.Mock())
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_os_install_device', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_evaluate_hw_waits_for_disks_nonconfigured(
            self, mocked_sleep, mocked_get_inst_dev, mocked_log):
        mocked_get_inst_dev.side_effect = [
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            None
        ]

        self.hardware.evaluate_hardware_support()

        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(10, mocked_get_inst_dev.call_count)
        expected_calls = [mock.call(CONF.disk_wait_delay)] * 9
        mocked_sleep.assert_has_calls(expected_calls)
        mocked_log.warning.assert_called_once_with(
            'The root device was not detected in %d seconds',
            CONF.disk_wait_delay * 9)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    @mock.patch.object(hardware, '_check_for_iscsi', mock.Mock())
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_os_install_device', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_evaluate_hw_waits_for_disks_configured(self, mocked_sleep,
                                                    mocked_get_inst_dev,
                                                    mocked_log):
        CONF.set_override('disk_wait_attempts', '1')

        mocked_get_inst_dev.side_effect = [
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            None
        ]

        self.hardware.evaluate_hardware_support()

        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(1, mocked_get_inst_dev.call_count)
        self.assertFalse(mocked_sleep.called)
        mocked_log.warning.assert_called_once_with(
            'The root device was not detected')

    @mock.patch.object(hardware, '_check_for_iscsi', mock.Mock())
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_os_install_device', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_evaluate_hw_disks_timeout_unconfigured(self, mocked_sleep,
                                                    mocked_get_inst_dev):
        mocked_get_inst_dev.side_effect = errors.DeviceNotFound('boom')
        self.hardware.evaluate_hardware_support()
        mocked_sleep.assert_called_with(3)

    @mock.patch.object(hardware, '_check_for_iscsi', mock.Mock())
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_os_install_device', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_evaluate_hw_disks_timeout_configured(self, mocked_sleep,
                                                  mocked_root_dev):
        CONF.set_override('disk_wait_delay', '5')
        mocked_root_dev.side_effect = errors.DeviceNotFound('boom')

        self.hardware.evaluate_hardware_support()
        mocked_sleep.assert_called_with(5)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_os_install_device', autospec=True)
    @mock.patch.object(hardware, '_check_for_iscsi', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_evaluate_hw_disks_timeout(
            self, mocked_sleep, mocked_check_for_iscsi, mocked_get_inst_dev):
        mocked_get_inst_dev.side_effect = errors.DeviceNotFound('boom')
        result = self.hardware.evaluate_hardware_support()
        self.assertEqual(hardware.HardwareSupport.GENERIC, result)
        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(CONF.disk_wait_attempts,
                         mocked_get_inst_dev.call_count)
        mocked_sleep.assert_called_with(CONF.disk_wait_delay)

    @mock.patch.object(utils, 'get_agent_params',
                       lambda: {'BOOTIF': 'boot:if'})
    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_get_boot_info_pxe_interface(self, mocked_isdir):
        mocked_isdir.return_value = False
        result = self.hardware.get_boot_info()
        self.assertEqual(hardware.BootInfo(current_boot_mode='bios',
                                           pxe_interface='boot:if'),
                         result)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_get_boot_info_bios(self, mocked_isdir):
        mocked_isdir.return_value = False
        result = self.hardware.get_boot_info()
        self.assertEqual(hardware.BootInfo(current_boot_mode='bios'), result)
        mocked_isdir.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_get_boot_info_uefi(self, mocked_isdir):
        mocked_isdir.return_value = True
        result = self.hardware.get_boot_info()
        self.assertEqual(hardware.BootInfo(current_boot_mode='uefi'), result)
        mocked_isdir.assert_called_once_with('/sys/firmware/efi')


@mock.patch.object(os, 'listdir', lambda *_: [])
@mock.patch.object(utils, 'execute', autospec=True)
class TestModuleFunctions(base.IronicAgentTest):

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(hardware, '_get_device_info',
                       lambda x, y, z: 'FooTastic')
    @mock.patch.object(hardware, '_udev_settle', autospec=True)
    @mock.patch.object(hardware.pyudev.Device, "from_device_file",
                       autospec=False)
    def test_list_all_block_devices_success(self, mocked_fromdevfile,
                                            mocked_udev, mocked_readlink,
                                            mocked_execute):
        mocked_readlink.return_value = '../../sda'
        mocked_fromdevfile.return_value = {}
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE_SMALL, '')
        result = hardware.list_all_block_devices()
        mocked_execute.assert_called_once_with(
            'lsblk', '-Pbdi', '-oKNAME,MODEL,SIZE,ROTA,TYPE',
            check_exit_code=[0])
        self.assertEqual(BLK_DEVICE_TEMPLATE_SMALL_DEVICES, result)
        mocked_udev.assert_called_once_with()

    @mock.patch.object(hardware, '_get_device_info',
                       lambda x, y: "FooTastic")
    @mock.patch.object(hardware, '_udev_settle', autospec=True)
    def test_list_all_block_devices_wrong_block_type(self, mocked_udev,
                                                     mocked_execute):
        mocked_execute.return_value = ('TYPE="foo" MODEL="model"', '')
        result = hardware.list_all_block_devices()
        mocked_execute.assert_called_once_with(
            'lsblk', '-Pbdi', '-oKNAME,MODEL,SIZE,ROTA,TYPE',
            check_exit_code=[0])
        self.assertEqual([], result)
        mocked_udev.assert_called_once_with()

    @mock.patch.object(hardware, '_udev_settle', autospec=True)
    def test_list_all_block_devices_missing(self, mocked_udev,
                                            mocked_execute):
        """Test for missing values returned from lsblk"""
        mocked_execute.return_value = ('TYPE="disk" MODEL="model"', '')
        self.assertRaisesRegex(
            errors.BlockDeviceError,
            r'^Block device caused unknown error: KNAME, ROTA, SIZE must be '
            r'returned by lsblk.$',
            hardware.list_all_block_devices)
        mocked_udev.assert_called_once_with()

    def test__udev_settle(self, mocked_execute):
        hardware._udev_settle()
        mocked_execute.assert_called_once_with('udevadm', 'settle')

    def test__check_for_iscsi(self, mocked_execute):
        hardware._check_for_iscsi()
        mocked_execute.assert_has_calls([
            mock.call('iscsistart', '-f'),
            mock.call('iscsistart', '-b')])

    def test__check_for_iscsi_no_iscsi(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        hardware._check_for_iscsi()
        mocked_execute.assert_has_calls([
            mock.call('iscsistart', '-f')])


def create_hdparm_info(supported=False, enabled=False, locked=False,
                       frozen=False, enhanced_erase=False):

    def update_values(values, state, key):
        if not state:
            values[key] = 'not' + values[key]

    values = {
        'supported': '\tsupported',
        'enabled': '\tenabled',
        'locked': '\tlocked',
        'frozen': '\tfrozen',
        'enhanced_erase': '\tsupported: enhanced erase',
    }

    update_values(values, supported, 'supported')
    update_values(values, enabled, 'enabled')
    update_values(values, locked, 'locked')
    update_values(values, frozen, 'frozen')
    update_values(values, enhanced_erase, 'enhanced_erase')

    return HDPARM_INFO_TEMPLATE % values

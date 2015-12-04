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

import mock
import netifaces
import os
from oslo_concurrency import processutils
from oslo_utils import units
from oslotest import base as test_base
import pyudev
import six
from stevedore import extension

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import utils

if six.PY2:
    OPEN_FUNCTION_NAME = '__builtin__.open'
else:
    OPEN_FUNCTION_NAME = 'builtins.open'

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
    '\tnot\tlocked\n'
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

SHRED_OUTPUT = (
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


class FakeHardwareManager(hardware.GenericHardwareManager):
    def __init__(self, hardware_support):
        self._hardware_support = hardware_support

    def evaluate_hardware_support(self):
        return self._hardware_support


class TestHardwareManagerLoading(test_base.BaseTestCase):
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
        ext1 = extension.Extension('fake_generic0', fake_ep, None,
            FakeHardwareManager(hardware.HardwareSupport.GENERIC))
        ext2 = extension.Extension('fake_mainline0', fake_ep, None,
            FakeHardwareManager(hardware.HardwareSupport.MAINLINE))
        ext3 = extension.Extension('fake_generic1', fake_ep, None,
            FakeHardwareManager(hardware.HardwareSupport.GENERIC))
        self.correct_hw_manager = ext2.obj
        self.fake_ext_mgr = extension.ExtensionManager.make_test_instance([
            ext1, ext2, ext3
        ])


class TestGenericHardwareManager(test_base.BaseTestCase):
    def setUp(self):
        super(TestGenericHardwareManager, self).setUp()
        self.hardware = hardware.GenericHardwareManager()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244',
                     'driver_internal_info': {}}

    @mock.patch('netifaces.ifaddresses')
    @mock.patch('os.listdir')
    @mock.patch('os.path.exists')
    @mock.patch(OPEN_FUNCTION_NAME)
    def test_list_network_interfaces(self,
                                     mocked_open,
                                     mocked_exists,
                                     mocked_listdir,
                                     mocked_ifaddresses):
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.return_value = '00:0c:29:8c:11:b1\n'
        mocked_ifaddresses.return_value = {
            netifaces.AF_INET: [{'addr': '192.168.1.2'}]
        }
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(len(interfaces), 1)
        self.assertEqual(interfaces[0].name, 'eth0')
        self.assertEqual(interfaces[0].mac_address, '00:0c:29:8c:11:b1')
        self.assertEqual(interfaces[0].ipv4_address, '192.168.1.2')

    @mock.patch.object(utils, 'execute')
    def test_get_os_install_device(self, mocked_execute):
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        self.assertEqual(self.hardware.get_os_install_device(), '/dev/sdb')
        mocked_execute.assert_called_once_with(
            'lsblk', '-PbdioKNAME,MODEL,SIZE,ROTA,TYPE',
            check_exit_code=[0])

    @mock.patch.object(utils, 'execute')
    def test_get_os_install_device_fails(self, mocked_execute):
        """Fail to find device >=4GB w/o root device hints"""
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE_SMALL, '')
        ex = self.assertRaises(errors.DeviceNotFound,
                               self.hardware.get_os_install_device)
        mocked_execute.assert_called_once_with(
            'lsblk', '-PbdioKNAME,MODEL,SIZE,ROTA,TYPE', check_exit_code=[0])
        self.assertIn(str(4 * units.Gi), ex.details)

    @mock.patch.object(hardware, 'list_all_block_devices')
    @mock.patch.object(utils, 'parse_root_device_hints')
    def test_get_os_install_device_root_device_hints(self, mock_root_device,
                                                     mock_dev):
        model = 'fastable sd131 7'
        mock_root_device.return_value = {'model': model,
                                         'wwn': 'fake-wwn',
                                         'serial': 'fake-serial',
                                         'vendor': 'fake-vendor',
                                         'size': 10}
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model=model,
                                 size=10737418240,
                                 rotational=False,
                                 vendor='fake-vendor',
                                 wwn='fake-wwn',
                                 serial='fake-serial'),
        ]

        self.assertEqual('/dev/sdb', self.hardware.get_os_install_device())
        mock_root_device.assert_called_once_with()
        mock_dev.assert_called_once_with()

    @mock.patch.object(hardware, 'list_all_block_devices')
    @mock.patch.object(utils, 'parse_root_device_hints')
    def test_get_os_install_device_root_device_hints_no_device_found(
            self, mock_root_device, mock_dev):
        model = 'fastable sd131 7'
        mock_root_device.return_value = {'model': model,
                                         'wwn': 'fake-wwn',
                                         'serial': 'fake-serial',
                                         'vendor': 'fake-vendor',
                                         'size': 10}
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
        mock_root_device.assert_called_once_with()
        mock_dev.assert_called_once_with()

    def test__get_device_vendor(self):
        fileobj = mock.mock_open(read_data='fake-vendor')
        with mock.patch(OPEN_FUNCTION_NAME, fileobj, create=True) as mock_open:
            vendor = hardware._get_device_vendor('/dev/sdfake')
            mock_open.assert_called_once_with(
                '/sys/class/block/sdfake/device/vendor', 'r')
            self.assertEqual('fake-vendor', vendor)

    @mock.patch.object(utils, 'execute')
    def test_get_cpus(self, mocked_execute):
        mocked_execute.return_value = LSCPU_OUTPUT, ''

        cpus = self.hardware.get_cpus()
        self.assertEqual(cpus.model_name,
                         'Intel(R) Xeon(R) CPU E5-2609 0 @ 2.40GHz')
        self.assertEqual(cpus.frequency, '2400.0000')
        self.assertEqual(cpus.count, 4)
        self.assertEqual(cpus.architecture, 'x86_64')

    @mock.patch.object(utils, 'execute')
    def test_get_cpus2(self, mocked_execute):
        mocked_execute.return_value = LSCPU_OUTPUT_NO_MAX_MHZ, ''

        cpus = self.hardware.get_cpus()
        self.assertEqual(cpus.model_name,
                         'Intel(R) Xeon(R) CPU E5-1650 v3 @ 3.50GHz')
        self.assertEqual(cpus.frequency, '1794.433')
        self.assertEqual(cpus.count, 12)
        self.assertEqual(cpus.architecture, 'x86_64')

    @mock.patch('psutil.version_info', (2, 0))
    @mock.patch('psutil.phymem_usage', autospec=True)
    @mock.patch.object(utils, 'execute')
    def test_get_memory(self, mocked_execute, mocked_usage):
        mocked_usage.return_value = mock.Mock(total=3952 * 1024 * 1024)
        mocked_execute.return_value = (
            "Foo\nSize: 2048 MB\nSize: 2 GB\n",
            ""
        )

        mem = self.hardware.get_memory()

        self.assertEqual(mem.total, 3952 * 1024 * 1024)
        self.assertEqual(mem.physical_mb, 4096)

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

        hardware_info = self.hardware.list_hardware_info()
        self.assertEqual(hardware_info['memory'], self.hardware.get_memory())
        self.assertEqual(hardware_info['cpu'], self.hardware.get_cpus())
        self.assertEqual(hardware_info['disks'],
                         self.hardware.list_block_devices())
        self.assertEqual(hardware_info['interfaces'],
                         self.hardware.list_network_interfaces())

    @mock.patch.object(hardware, 'list_all_block_devices')
    def test_list_block_devices(self, list_mock):
        device = hardware.BlockDevice('/dev/hdaa', 'small', 65535, False)
        list_mock.return_value = [device]
        devices = self.hardware.list_block_devices()

        self.assertEqual([device], devices)

        list_mock.assert_called_once_with()

    @mock.patch.object(hardware, '_get_device_vendor')
    @mock.patch.object(pyudev.Device, 'from_device_file')
    @mock.patch.object(utils, 'execute')
    def test_list_all_block_device(self, mocked_execute, mocked_udev,
                                   mocked_dev_vendor):
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        mocked_udev.side_effect = pyudev.DeviceNotFoundError()
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='Super Vendor'),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor'),
            hardware.BlockDevice(name='/dev/sdd',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor')
        ]

        self.assertEqual(4, len(devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'vendor', 'serial']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))

    @mock.patch.object(hardware, '_get_device_vendor')
    @mock.patch.object(pyudev.Device, 'from_device_file')
    @mock.patch.object(utils, 'execute')
    def test_list_all_block_device_udev_17(self, mocked_execute, mocked_udev,
                                           mocked_dev_vendor):
        # test compatibility with pyudev < 0.18
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        mocked_udev.side_effect = OSError()
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        self.assertEqual(4, len(devices))

    @mock.patch.object(hardware, '_get_device_vendor')
    @mock.patch.object(pyudev.Device, 'from_device_file')
    @mock.patch.object(utils, 'execute')
    def test_list_all_block_device_with_udev(self, mocked_execute, mocked_udev,
                                             mocked_dev_vendor):
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        mocked_udev.side_effect = iter([
            {'ID_WWN': 'wwn%d' % i, 'ID_SERIAL_SHORT': 'serial%d' % i}
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
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn1',
                                 serial='serial1'),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn2',
                                 serial='serial2'),
            hardware.BlockDevice(name='/dev/sdd',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn3',
                                 serial='serial3')
        ]

        self.assertEqual(4, len(expected_devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'vendor', 'serial']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))

    @mock.patch.object(hardware, 'dispatch_to_managers')
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

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_ata_success(self, mocked_execute):
        hdparm_info_fields = {
            'supported': '\tsupported',
            'enabled': 'not\tenabled',
            'frozen': 'not\tfrozen',
            'enhanced_erase': 'not\tsupported: enhanced erase',
        }
        mocked_execute.side_effect = [
            (HDPARM_INFO_TEMPLATE % hdparm_info_fields, ''),
            ('', ''),
            ('', ''),
            (HDPARM_INFO_TEMPLATE % hdparm_info_fields, ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('hdparm', '--user-master', 'u', '--security-set-pass',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '--user-master', 'u', '--security-erase',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '-I', '/dev/sda'),
        ])

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_nosecurity_shred(self, mocked_execute):
        hdparm_output = HDPARM_INFO_TEMPLATE.split('\nSecurity:')[0]
        info = self.node.get('driver_internal_info')
        info['agent_erase_devices_iterations'] = 2

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SHRED_OUTPUT, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '2', '/dev/sda')
        ])

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_notsupported_shred(self, mocked_execute):
        hdparm_output = HDPARM_INFO_TEMPLATE % {
                'supported': 'not\tsupported',
                'enabled': 'not\tenabled',
                'frozen': 'not\tfrozen',
                'enhanced_erase': 'not\tsupported: enhanced erase',
        }

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SHRED_OUTPUT, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
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

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_shred_fail_oserror(self, mocked_execute):
        mocked_execute.side_effect = OSError
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._shred_block_device(self.node, block_device)
        self.assertFalse(res)
        mocked_execute.assert_called_once_with('shred', '--force', '--zero',
            '--verbose', '--iterations', '1', '/dev/sda')

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_shred_fail_processerror(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._shred_block_device(self.node, block_device)
        self.assertFalse(res)
        mocked_execute.assert_called_once_with('shred', '--force', '--zero',
            '--verbose', '--iterations', '1', '/dev/sda')

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_ata_security_enabled(self, mocked_execute):
        hdparm_output = HDPARM_INFO_TEMPLATE % {
            'supported': '\tsupported',
            'enabled': '\tenabled',
            'frozen': 'not\tfrozen',
            'enhanced_erase': 'not\tsupported: enhanced erase',
        }

        mocked_execute.side_effect = [
            (hdparm_output, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware.erase_block_device,
                          self.node, block_device)

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_ata_frozen(self, mocked_execute):
        hdparm_output = HDPARM_INFO_TEMPLATE % {
            'supported': '\tsupported',
            'enabled': 'not\tenabled',
            'frozen': '\tfrozen',
            'enhanced_erase': 'not\tsupported: enhanced erase',
        }

        mocked_execute.side_effect = [
            (hdparm_output, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware.erase_block_device,
                          self.node, block_device)

    @mock.patch.object(utils, 'execute')
    def test_erase_block_device_ata_failed(self, mocked_execute):
        hdparm_output_before = HDPARM_INFO_TEMPLATE % {
            'supported': '\tsupported',
            'enabled': 'not\tenabled',
            'frozen': 'not\tfrozen',
            'enhanced_erase': 'not\tsupported: enhanced erase',
        }

        # If security mode remains enabled after the erase, it is indiciative
        # of a failed erase.
        hdparm_output_after = HDPARM_INFO_TEMPLATE % {
            'supported': '\tsupported',
            'enabled': '\tenabled',
            'frozen': 'not\tfrozen',
            'enhanced_erase': 'not\tsupported: enhanced erase',
        }

        mocked_execute.side_effect = [
            (hdparm_output_before, ''),
            ('', ''),
            ('', ''),
            (hdparm_output_after, ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware.erase_block_device,
                          self.node, block_device)

    def test_normal_vs_enhanced_security_erase(self):
        @mock.patch.object(utils, 'execute')
        def test_security_erase_option(test_case,
                                       enhanced_erase_string,
                                       expected_option,
                                       mocked_execute):
            hdparm_parameters = {
                'supported': '\tsupported',
                'enabled': 'not\tenabled',
                'frozen': 'not\tfrozen',
                'enhanced_erase': enhanced_erase_string,
            }
            mocked_execute.side_effect = [
                (HDPARM_INFO_TEMPLATE % hdparm_parameters, ''),
                ('', ''),
                ('', ''),
                (HDPARM_INFO_TEMPLATE % hdparm_parameters, ''),
            ]

            block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                                True)
            test_case.hardware.erase_block_device(self.node, block_device)
            mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                           expected_option,
                                           'NULL', '/dev/sda')

        test_security_erase_option(self,
                '\tsupported: enhanced erase', '--security-erase-enhanced')
        test_security_erase_option(self,
                '\tnot\tsupported: enhanced erase', '--security-erase')

    @mock.patch.object(utils, 'execute')
    def test_get_bmc_address(self, mocked_execute):
        mocked_execute.return_value = '192.1.2.3\n', ''
        self.assertEqual('192.1.2.3', self.hardware.get_bmc_address())

    @mock.patch.object(utils, 'execute')
    def test_get_bmc_address_virt(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        self.assertIsNone(self.hardware.get_bmc_address())

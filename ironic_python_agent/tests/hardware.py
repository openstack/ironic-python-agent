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
import os
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
)

BLK_DEVICE_TEMPLATE = (
    'KNAME="sda" MODEL="TinyUSB Drive" SIZE="3116853504" '
    'ROTA="0" TYPE="disk"\n'
    'KNAME="sdb" MODEL="Fastable SD131 7" SIZE="10737418240" '
    'ROTA="0" TYPE="disk"\n'
    'KNAME="sdc" MODEL="NWD-BLP4-1600   " SIZE="1765517033472" '
    ' ROTA="0" TYPE="disk"\n'
    'KNAME="sdd" MODEL="NWD-BLP4-1600   " SIZE="1765517033472" '
    ' ROTA="0" TYPE="disk"\n'
    'KNAME="loop0" MODEL="" SIZE="109109248" ROTA="1" TYPE="loop"'
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

    @mock.patch('os.listdir')
    @mock.patch('os.path.exists')
    @mock.patch(OPEN_FUNCTION_NAME)
    def test_list_network_interfaces(self,
                                     mocked_open,
                                     mocked_exists,
                                     mocked_listdir):
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.return_value = '00:0c:29:8c:11:b1\n'
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(len(interfaces), 1)
        self.assertEqual(interfaces[0].name, 'eth0')
        self.assertEqual(interfaces[0].mac_address, '00:0c:29:8c:11:b1')

    @mock.patch.object(utils, 'execute')
    def test_get_os_install_device(self, mocked_execute):
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        self.assertEqual(self.hardware.get_os_install_device(), '/dev/sdb')
        mocked_execute.assert_called_once_with(
            'lsblk', '-PbdioKNAME,MODEL,SIZE,ROTA,TYPE', check_exit_code=[0])

    @mock.patch.object(hardware.GenericHardwareManager, '_get_device_vendor')
    @mock.patch.object(pyudev.Device, 'from_device_file')
    @mock.patch.object(utils, 'parse_root_device_hints')
    @mock.patch.object(utils, 'execute')
    def test_get_os_install_device_root_device_hints(self, mocked_execute,
                                                     mock_root_device,
                                                     mock_pyudev,
                                                     mock_dev_vendor):
        model = 'fastable sd131 7'
        mock_root_device.return_value = {'model': model,
                                         'wwn': 'fake-wwn',
                                         'serial': 'fake-serial',
                                         'vendor': 'fake-vendor',
                                         'size': 10}
        mock_dev_vendor.return_value = 'fake-vendor'
        mock_pyudev.side_effect = ({}, {'ID_MODEL': model,
                                        'ID_WWN': 'fake-wwn',
                                        'ID_SERIAL_SHORT': 'fake-serial'})
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')

        self.assertEqual('/dev/sdb', self.hardware.get_os_install_device())
        mocked_execute.assert_called_once_with(
            'lsblk', '-PbdioKNAME,MODEL,SIZE,ROTA,TYPE', check_exit_code=[0])
        mock_root_device.assert_called_once_with()
        expected = [mock.call(mock.ANY, '/dev/sda'),
                    mock.call(mock.ANY, '/dev/sdb')]
        mock_pyudev.assert_has_calls(expected)

    @mock.patch.object(pyudev.Device, 'from_device_file')
    @mock.patch.object(utils, 'parse_root_device_hints')
    @mock.patch.object(utils, 'execute')
    def test_get_os_install_device_root_device_hints_no_device_found(self,
            mocked_execute, mock_root_device, mock_pyudev):
        mock_root_device.return_value = {'model': 'endo-sym armor'}
        mock_pyudev.return_value = {'ID_MODEL': 'Saturn V Armor'}
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        self.assertRaises(errors.DeviceNotFound,
                          self.hardware.get_os_install_device)
        mocked_execute.assert_called_once_with(
            'lsblk', '-PbdioKNAME,MODEL,SIZE,ROTA,TYPE', check_exit_code=[0])
        mock_root_device.assert_called_once_with()
        expected = [mock.call(mock.ANY, '/dev/sda'),
                    mock.call(mock.ANY, '/dev/sdb'),
                    mock.call(mock.ANY, '/dev/sdc'),
                    mock.call(mock.ANY, '/dev/sdd')]
        mock_pyudev.assert_has_calls(expected)

    def test__get_device_vendor(self):
        fileobj = mock.mock_open(read_data='fake-vendor')
        with mock.patch(OPEN_FUNCTION_NAME, fileobj, create=True) as mock_open:
            vendor = self.hardware._get_device_vendor('/dev/sdfake')
            mock_open.assert_called_once_with(
                '/sys/class/block/sdfake/device/vendor', 'r')
            self.assertEqual('fake-vendor', vendor)

    @mock.patch('ironic_python_agent.hardware.GenericHardwareManager.'
                '_get_cpu_count')
    @mock.patch(OPEN_FUNCTION_NAME)
    def test_get_cpus(self, mocked_open, mocked_cpucount):
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.return_value = (
            'processor       : 0\n'
            'vendor_id       : GenuineIntel\n'
            'cpu family      : 6\n'
            'model           : 58\n'
            'model name      : Intel(R) Core(TM) i7-3720QM CPU @ 2.60GHz\n'
            'stepping        : 9\n'
            'microcode       : 0x15\n'
            'cpu MHz         : 2594.685\n'
            'cache size      : 6144 KB\n'
            'fpu             : yes\n'
            'fpu_exception   : yes\n'
            'cpuid level     : 13\n'
            'wp              : yes\n'
            'flags           : fpu vme de pse tsc msr pae mce cx8 apic sep '
            'mtrr pge mca cmov pat pse36 clflush dts mmx fxsr sse sse2 ss '
            'syscall nx rdtscp lm constant_tsc arch_perfmon pebs bts nopl '
            'xtopology tsc_reliable nonstop_tsc aperfmperf eagerfpu pni '
            'pclmulqdq ssse3 cx16 pcid sse4_1 sse4_2 x2apic popcnt aes xsave '
            'avx f16c rdrand hypervisor lahf_lm ida arat epb xsaveopt pln pts '
            'dtherm fsgsbase smep\n'
            'bogomips        : 5189.37\n'
            'clflush size    : 64\n'
            'cache_alignment : 64\n'
            'address sizes   : 40 bits physical, 48 bits virtual\n'
            'power management:\n'
            '\n'
            'processor       : 1\n'
            'vendor_id       : GenuineIntel\n'
            'cpu family      : 6\n'
            'model           : 58\n'
            'model name      : Intel(R) Core(TM) i7-3720QM CPU @ 2.60GHz\n'
            'stepping        : 9\n'
            'microcode       : 0x15\n'
            'cpu MHz         : 2594.685\n'
            'cache size      : 6144 KB\n'
            'fpu             : yes\n'
            'fpu_exception   : yes\n'
            'cpuid level     : 13\n'
            'wp              : yes\n'
            'flags           : fpu vme de pse tsc msr pae mce cx8 apic sep '
            'mtrr pge mca cmov pat pse36 clflush dts mmx fxsr sse sse2 ss '
            'syscall nx rdtscp lm constant_tsc arch_perfmon pebs bts nopl '
            'xtopology tsc_reliable nonstop_tsc aperfmperf eagerfpu pni '
            'pclmulqdq ssse3 cx16 pcid sse4_1 sse4_2 x2apic popcnt aes xsave '
            'avx f16c rdrand hypervisor lahf_lm ida arat epb xsaveopt pln pts '
            'dtherm fsgsbase smep\n'
            'bogomips        : 5189.37\n'
            'clflush size    : 64\n'
            'cache_alignment : 64\n'
            'address sizes   : 40 bits physical, 48 bits virtual\n'
            'power management:\n'
        )

        mocked_cpucount.return_value = 2

        cpus = self.hardware.get_cpus()
        self.assertEqual(cpus.model_name,
                         'Intel(R) Core(TM) i7-3720QM CPU @ 2.60GHz')
        self.assertEqual(cpus.frequency, '2594.685')
        self.assertEqual(cpus.count, 2)

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
            14)

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

    @mock.patch.object(utils, 'execute')
    def test_list_block_device(self, mocked_execute):
        mocked_execute.return_value = (BLK_DEVICE_TEMPLATE, '')
        devices = self.hardware.list_block_devices()
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False),
            hardware.BlockDevice(name='/dev/sdd',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False)
        ]

        self.assertEqual(4, len(expected_devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))

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
        self.hardware.erase_block_device(block_device)
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

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (SHRED_OUTPUT, '')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
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
        self.hardware.erase_block_device(block_device)
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
        self.hardware.erase_block_device(block_device)
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
                          block_device)

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
                          block_device)

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
                          block_device)

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
            test_case.hardware.erase_block_device(block_device)
            mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                           expected_option,
                                           'NULL', '/dev/sda')

        test_security_erase_option(self,
                '\tsupported: enhanced erase', '--security-erase-enhanced')
        test_security_erase_option(self,
                '\tnot\tsupported: enhanced erase', '--security-erase')

"""
Copyright 2013 Rackspace, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import mock
from oslotest import base as test_base
import six

from ironic_python_agent import hardware
from ironic_python_agent import utils

if six.PY2:
    OPEN_FUNCTION_NAME = '__builtin__.open'
else:
    OPEN_FUNCTION_NAME = 'builtins.open'


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
        mocked_execute.return_value = (
            'RO    RA   SSZ   BSZ   StartSec            Size   Device\n'
            'rw   256   512  4096          0    249578283616   /dev/sda\n'
            'rw   256   512  4096       2048      8587837440   /dev/sda1\n'
            'rw   256   512  4096  124967424        15728640   /dev/sda2\n'
            'rw   256   512  4096          0     31016853504   /dev/sdb\n'
            'rw   256   512  4096          0    249578283616   /dev/sdc\n', '')

        self.assertEqual(self.hardware.get_os_install_device(), '/dev/sdb')
        mocked_execute.assert_called_once_with('blockdev',
                                               '--report',
                                               check_exit_code=[0])

    @mock.patch('psutil.cpu_count')
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
            hardware.BlockDevice('/dev/sdj', 1073741824),
            hardware.BlockDevice('/dev/hdaa', 65535),
        ]

        hardware_info = self.hardware.list_hardware_info()
        self.assertEqual(hardware_info['memory'], self.hardware.get_memory())
        self.assertEqual(hardware_info['cpu'], self.hardware.get_cpus())
        self.assertEqual(hardware_info['disks'],
                         self.hardware.list_block_devices())
        self.assertEqual(hardware_info['interfaces'],
                         self.hardware.list_network_interfaces())

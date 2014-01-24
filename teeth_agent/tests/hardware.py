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
import unittest

from teeth_agent import hardware


class TestGenericHardwareManager(unittest.TestCase):
    def setUp(self):
        self.hardware = hardware.GenericHardwareManager()

    @mock.patch('__builtin__.open')
    def test_get_primary_mac_address(self, mocked_open):
        f = mocked_open.return_value
        f.read.return_value = '00:0c:29:8c:11:b1\n'

        mac_addr = self.hardware.get_primary_mac_address()
        self.assertEqual(mac_addr, '00:0c:29:8c:11:b1')

        mocked_open.assert_called_once_with('/sys/class/net/eth0/address', 'r')
        f.read.assert_called_once_with()

    def test_get_os_install_device(self):
        self.hardware._cmd = mock.Mock()
        self.hardware._cmd.return_value = blockdev = mock.Mock()
        blockdev.return_value = (
            'RO    RA   SSZ   BSZ   StartSec            Size   Device\n'
            'rw   256   512  4096          0     31016853504   /dev/sdb\n'
            'rw   256   512  4096          0    249578283616   /dev/sda\n'
            'rw   256   512  4096       2048      8587837440   /dev/sda1\n'
            'rw   256   512  4096  124967424        15728640   /dev/sda2\n'
            'rw   256   512  4096          0    249578283616   /dev/sdc\n')

        self.assertEqual(self.hardware.get_os_install_device(), '/dev/sdb')
        self.hardware._cmd.assert_called_once_with('blockdev')
        blockdev.assert_called_once_with('--report')

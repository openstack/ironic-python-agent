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


class TestBaseTeethAgent(unittest.TestCase):
    def setUp(self):
        self.hardware = hardware.HardwareInspector()

    @mock.patch('__builtin__.open')
    def test_decom_mode(self, mocked_open):
        f = mocked_open.return_value
        f.read.return_value = '00:0c:29:8c:11:b1\n'

        mac_addr = self.hardware.get_primary_mac_address()
        self.assertEqual(mac_addr, '00:0c:29:8c:11:b1')

        mocked_open.assert_called_once_with('/sys/class/net/eth0/address', 'r')
        f.read.assert_called_once_with()

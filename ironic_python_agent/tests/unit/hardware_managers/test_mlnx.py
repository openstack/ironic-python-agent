# Copyright 2016 Mellanox Technologies, Ltd
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

import os

import mock
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent.hardware_managers import mlnx

IB_ADDRESS = 'a0:00:00:27:fe:80:00:00:00:00:00:00:7c:fe:90:03:00:29:26:52'
CLIENT_ID = 'ff:00:00:00:00:00:02:00:00:02:c9:00:7c:fe:90:03:00:29:26:52'


class MlnxHardwareManager(test_base.BaseTestCase):
    def setUp(self):
        super(MlnxHardwareManager, self).setUp()
        self.hardware = mlnx.MellanoxDeviceHardwareManager()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244',
                     'driver_internal_info': {}}

    def test_infiniband_address_to_mac(self):
        self.assertEqual(
            '7c:fe:90:29:26:52',
            mlnx._infiniband_address_to_mac(IB_ADDRESS))

    def test_generate_client_id(self):
        self.assertEqual(
            CLIENT_ID,
            mlnx._generate_client_id(IB_ADDRESS))

    @mock.patch.object(os, 'listdir')
    @mock.patch('six.moves.builtins.open')
    def test_detect_hardware(self, mocked_open, mock_listdir):
        mock_listdir.return_value = ['eth0', 'ib0']
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['0x8086\n', '0x15b3\n']
        self.assertTrue(mlnx._detect_hardware())

    @mock.patch.object(os, 'listdir')
    @mock.patch('six.moves.builtins.open')
    def test_detect_hardware_no_mlnx(self, mocked_open, mock_listdir):
        mock_listdir.return_value = ['eth0', 'eth1']
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['0x8086\n', '0x8086\n']
        self.assertFalse(mlnx._detect_hardware())

    @mock.patch.object(os, 'listdir')
    @mock.patch('six.moves.builtins.open')
    def test_detect_hardware_error(self, mocked_open, mock_listdir):
        mock_listdir.return_value = ['eth0', 'ib0']
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['0x8086\n', OSError('boom')]
        self.assertFalse(mlnx._detect_hardware())

    @mock.patch.object(os, 'listdir')
    @mock.patch('six.moves.builtins.open')
    def test_evaluate_hardware_support(self, mocked_open, mock_listdir):
        mock_listdir.return_value = ['eth0', 'ib0']
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['0x8086\n', '0x15b3\n']
        self.assertEqual(
            hardware.HardwareSupport.MAINLINE,
            self.hardware.evaluate_hardware_support())

    @mock.patch.object(os, 'listdir')
    @mock.patch('six.moves.builtins.open')
    def test_evaluate_hardware_support_no_mlnx(
            self, mocked_open, mock_listdir):
        mock_listdir.return_value = ['eth0', 'eth1']
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['0x8086\n', '0x8086\n']
        self.assertEqual(
            hardware.HardwareSupport.NONE,
            self.hardware.evaluate_hardware_support())

    @mock.patch('six.moves.builtins.open')
    def test_get_interface_info(self, mocked_open):
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = [IB_ADDRESS, '0x15b3\n']
        network_interface = self.hardware.get_interface_info('ib0')
        self.assertEqual('ib0', network_interface.name)
        self.assertEqual('7c:fe:90:29:26:52', network_interface.mac_address)
        self.assertEqual('0x15b3', network_interface.vendor)
        self.assertEqual(CLIENT_ID, network_interface.client_id)

    @mock.patch('six.moves.builtins.open')
    def test_get_interface_info_no_ib_interface(self, mocked_open):
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['7c:fe:90:29:26:52', '0x15b3\n']
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.get_interface_info, 'eth0')

    @mock.patch('six.moves.builtins.open')
    def test_get_interface_info_no_mlnx_interface(self, mocked_open):
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = [IB_ADDRESS, '0x8086\n']
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.get_interface_info, 'ib0')

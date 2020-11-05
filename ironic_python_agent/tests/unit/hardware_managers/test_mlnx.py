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
from unittest import mock

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent.hardware_managers import mlnx
from ironic_python_agent import netutils
from ironic_python_agent.tests.unit import base

IB_ADDRESS = 'a0:00:00:27:fe:80:00:00:00:00:00:00:7c:fe:90:03:00:29:26:52'
CLIENT_ID = 'ff:00:00:00:00:00:02:00:00:02:c9:00:7c:fe:90:03:00:29:26:52'


class MlnxHardwareManager(base.IronicAgentTest):
    def setUp(self):
        """
        Sets the hardware.

        Args:
            self: (todo): write your description
        """
        super(MlnxHardwareManager, self).setUp()
        self.hardware = mlnx.MellanoxDeviceHardwareManager()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244',
                     'driver_internal_info': {}}

    def test_infiniband_address_to_mac(self):
        """
        Assigns the address of the macro.

        Args:
            self: (todo): write your description
        """
        self.assertEqual(
            '7c:fe:90:29:26:52',
            mlnx._infiniband_address_to_mac(IB_ADDRESS))

    def test_generate_client_id(self):
        """
        Generate client id.

        Args:
            self: (todo): write your description
        """
        self.assertEqual(
            CLIENT_ID,
            mlnx._generate_client_id(IB_ADDRESS))

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_detect_hardware(self, mocked_get_device_info, mock_listdir):
        """
        Perform hardware hardware hardware.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_listdir: (list): write your description
        """
        mock_listdir.return_value = ['eth0', 'ib0']
        mocked_get_device_info.side_effect = ['0x8086', '0x15b3']
        self.assertTrue(mlnx._detect_hardware())

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_detect_hardware_no_mlnx(
            self, mocked_get_device_info, mock_listdir):
        """
        Test for hardware hardware hardware hardware.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_listdir: (todo): write your description
        """
        mock_listdir.return_value = ['eth0', 'eth1']
        mocked_get_device_info.side_effect = ['0x8086', '0x8086']
        self.assertFalse(mlnx._detect_hardware())

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_detect_hardware_error(
            self, mocked_get_device_info, mock_listdir):
        """
        Test if the error message for a device.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_listdir: (list): write your description
        """
        mock_listdir.return_value = ['eth0', 'ib0']
        mocked_get_device_info.side_effect = ['0x8086', None]
        self.assertFalse(mlnx._detect_hardware())

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_evaluate_hardware_support(
            self, mocked_get_device_info, mock_listdir):
        """
        Evaluate support.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_listdir: (list): write your description
        """
        mock_listdir.return_value = ['eth0', 'ib0']
        mocked_get_device_info.side_effect = ['0x8086', '0x15b3']
        self.assertEqual(
            hardware.HardwareSupport.MAINLINE,
            self.hardware.evaluate_hardware_support())

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_evaluate_hardware_support_no_mlnx(
            self, mocked_get_device_info, mock_listdir):
        """
        Perform the mock device.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_listdir: (list): write your description
        """
        mock_listdir.return_value = ['eth0', 'eth1']
        mocked_get_device_info.side_effect = ['0x8086', '0x8086']
        self.assertEqual(
            hardware.HardwareSupport.NONE,
            self.hardware.evaluate_hardware_support())

    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_get_interface_info(self, mocked_get_device_info, mock_get_mac):
        """
        Return interface information.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_get_mac: (todo): write your description
        """
        mocked_get_device_info.side_effect = ['0x15b3', '0x0014']
        mock_get_mac.return_value = IB_ADDRESS
        network_interface = self.hardware.get_interface_info('ib0')
        self.assertEqual('ib0', network_interface.name)
        self.assertEqual('7c:fe:90:29:26:52', network_interface.mac_address)
        self.assertEqual('0x15b3', network_interface.vendor)
        self.assertEqual('0x0014', network_interface.product)
        self.assertEqual(CLIENT_ID, network_interface.client_id)

    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_get_interface_info_no_ib_interface(
            self, mocked_get_device_info, mock_get_mac):
        """
        Get interface interface interface interface interface interface.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_get_mac: (str): write your description
        """
        mocked_get_device_info.side_effect = ['0x15b3']
        mock_get_mac.return_value = '7c:fe:90:29:26:52'
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.get_interface_info, 'eth0')

    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_get_interface_info_no_mlnx_interface(
            self, mocked_get_device_info, mock_get_mac):
        """
        Get the interface interface interface interface interface.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_get_mac: (todo): write your description
        """
        mocked_get_device_info.side_effect = ['0x8086']
        mock_get_mac.return_value = IB_ADDRESS
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.get_interface_info, 'ib0')

    @mock.patch.object(netutils, 'get_mac_addr', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    def test_get_interface_info_no_mac_address(
            self, mocked_get_device_info, mock_get_mac):
        """
        Gets the interface instance of the interface.

        Args:
            self: (todo): write your description
            mocked_get_device_info: (todo): write your description
            mock_get_mac: (todo): write your description
        """
        mock_get_mac.return_value = None
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.get_interface_info, 'ib0')
        self.assertFalse(mocked_get_device_info.called)

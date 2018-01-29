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

from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import netutils

LOG = log.getLogger()
# Mellanox NIC Vendor ID
MLNX_VENDOR_ID = '0x15b3'
# Mellanox Prefix to generate InfiniBand CLient-ID
MLNX_INFINIBAND_CLIENT_ID_PREFIX = 'ff:00:00:00:00:00:02:00:00:02:c9:00:'


def _infiniband_address_to_mac(address):
    """Convert InfiniBand address to MAC

    Convert InfiniBand address to MAC by Mellanox specific
    translation. The InfiniBand address is 59 characters
    composed from GID:GUID. The last 24 characters are the
    GUID. The InfiniBand MAC is upper 10 characters and lower
    9 characters from the GUID
    Example:
    address - a0:00:00:27:fe:80:00:00:00:00:00:00:7c:fe:90:03:00:29:26:52
    GUID - 7c:fe:90:03:00:29:26:52
    InfiniBand MAC - 7c:fe:90:29:26:52

    :param address: InfiniBand Address.
    :returns: InfiniBand MAC.
    """
    return address[36:-14] + address[51:]


def _generate_client_id(address):
    """Generate client id from  InfiniBand address

    :param address: InfiniBand address.
    :returns: client id.
    """
    return MLNX_INFINIBAND_CLIENT_ID_PREFIX + address[36:]


def _detect_hardware():
    """method for detection of Mellanox NICs

    :returns: Boolean value. True if the machine contain one
              or more Mellanox NIC(s), False otherwise.
    """
    iface_names = os.listdir('/sys/class/net')
    for ifname in iface_names:
        if (hardware._get_device_info(ifname, 'net', 'vendor') ==
            MLNX_VENDOR_ID):
            return True
    return False


class MellanoxDeviceHardwareManager(hardware.HardwareManager):
    """Mellanox hardware manager to support a single device"""

    HARDWARE_MANAGER_NAME = 'MellanoxDeviceHardwareManager'
    HARDWARE_MANAGER_VERSION = '1'

    def evaluate_hardware_support(self):
        """Declare level of hardware support provided."""

        if _detect_hardware():
            LOG.debug('Found Mellanox device')
            return hardware.HardwareSupport.MAINLINE
        else:
            LOG.debug('No Mellanox devices found')
            return hardware.HardwareSupport.NONE

    def get_interface_info(self, interface_name):
        """Return the interface information when its Mellanox and InfiniBand

        In case of Mellanox and InfiniBand interface we do the following:
            1. Calculate the "InfiniBand  MAC" according to InfiniBand GUID
            2. Calculate the client-id according to InfiniBand GUID
        """

        addr_path = '/sys/class/net/{0}/address'.format(interface_name)
        with open(addr_path) as addr_file:
            address = addr_file.read().strip()
        vendor = hardware._get_device_info(interface_name, 'net', 'vendor')
        if (len(address) != netutils.INFINIBAND_ADDR_LEN or
            vendor != MLNX_VENDOR_ID):
            raise errors.IncompatibleHardwareMethodError()

        mac_addr = _infiniband_address_to_mac(address)
        client_id = _generate_client_id(address)

        return hardware.NetworkInterface(
            interface_name, mac_addr,
            ipv4_address=netutils.get_ipv4_addr(interface_name),
            has_carrier=netutils.interface_has_carrier(interface_name),
            lldp=None,
            vendor=vendor,
            product=hardware._get_device_info(interface_name, 'net', 'device'),
            client_id=client_id)

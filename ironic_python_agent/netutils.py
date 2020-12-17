# Copyright 2014 Rackspace, Inc.
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

import ctypes
import fcntl
import select
import socket
import struct
import sys

import netifaces
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import netutils

from ironic_python_agent import utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

LLDP_ETHERTYPE = 0x88cc
IFF_PROMISC = 0x100
SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914
INFINIBAND_ADDR_LEN = 59

# LLDP definitions needed to extract vlan information
LLDP_TLV_ORG_SPECIFIC = 127
# 802.1Q defines from http://www.ieee802.org/1/pages/802.1Q-2014.html, Annex D
LLDP_802dot1_OUI = "0080c2"
# subtypes
dot1_VLAN_NAME = "03"
VLAN_ID_LEN = len(LLDP_802dot1_OUI + dot1_VLAN_NAME)


class ifreq(ctypes.Structure):
    """Class for setting flags on a socket."""
    _fields_ = [("ifr_ifrn", ctypes.c_char * 16),
                ("ifr_flags", ctypes.c_short)]


class RawPromiscuousSockets(object):
    def __init__(self, interface_names, protocol):
        """Initialize context manager.

        :param interface_names: a list of interface names to bind to
        :param protocol: the protocol to listen for
        :returns: A list of tuple of (interface_name, bound_socket), or [] if
                  there is an exception binding or putting the sockets in
                  promiscuous mode
        """
        if not interface_names:
            raise ValueError('interface_names must be a non-empty list of '
                             'network interface names to bind to.')
        self.protocol = protocol
        # A 3-tuple of (interface_name, socket, ifreq object)
        self.interfaces = [(name, self._get_socket(), ifreq())
                           for name in interface_names]

    def __enter__(self):
        for interface_name, sock, ifr in self.interfaces:
            LOG.info('Interface %s entering promiscuous mode to capture ',
                     interface_name)
            try:
                ifr.ifr_ifrn = interface_name.encode()
                # Get current flags
                fcntl.ioctl(sock.fileno(), SIOCGIFFLAGS, ifr)  # G for Get
                # bitwise or the flags with promiscuous mode, set the new flags
                ifr.ifr_flags |= IFF_PROMISC
                fcntl.ioctl(sock.fileno(), SIOCSIFFLAGS, ifr)  # S for Set
                # Bind the socket so it can be used
                LOG.debug('Binding interface %(interface)s for protocol '
                          '%(proto)s', {'interface': interface_name,
                                        'proto': self.protocol})
                sock.bind((interface_name, self.protocol))
            except Exception:
                LOG.error('Failed to open all RawPromiscuousSockets, '
                          'attempting to close any opened sockets.')
                self.__exit__(*sys.exc_info())
                raise

        # No need to return each interfaces ifreq.
        return [(sock[0], sock[1]) for sock in self.interfaces]

    def __exit__(self, exception_type, exception_val, trace):
        for name, sock, ifr in self.interfaces:
            # bitwise or with the opposite of promiscuous mode to remove
            ifr.ifr_flags &= ~IFF_PROMISC
            try:
                fcntl.ioctl(sock.fileno(), SIOCSIFFLAGS, ifr)
                sock.close()
            except Exception:
                LOG.exception('Failed to close raw socket for interface %s',
                              name)

    def _get_socket(self):
        return socket.socket(socket.AF_PACKET, socket.SOCK_RAW, self.protocol)


def get_lldp_info(interface_names):
    """Get LLDP info from the switch(es) the agent is connected to.

    Listens on either a single or all interfaces for LLDP packets, then
    parses them. If no LLDP packets are received before lldp_timeout,
    returns a dictionary in the form {'interface': [],...}.

    :param interface_names: The interface to listen for packets on. If
                           None, will listen on each interface.
    :return: A dictionary in the form
             {'interface': [(lldp_type, lldp_data)],...}
    """
    with RawPromiscuousSockets(interface_names, LLDP_ETHERTYPE) as interfaces:
        try:
            return _get_lldp_info(interfaces)
        except Exception as e:
            LOG.exception('Error while getting LLDP info: %s', str(e))
            raise


def _parse_tlv(buff):
    """Iterate over a buffer and generate structured TLV data.

    :param buff: An ethernet packet with the header trimmed off (first
                 14 bytes)
    """
    lldp_info = []
    while len(buff) >= 2:
        # TLV structure: type (7 bits), length (9 bits), val (0-511 bytes)
        tlvhdr = struct.unpack('!H', buff[:2])[0]
        tlvtype = (tlvhdr & 0xfe00) >> 9
        tlvlen = (tlvhdr & 0x01ff)
        tlvdata = buff[2:tlvlen + 2]
        buff = buff[tlvlen + 2:]
        lldp_info.append((tlvtype, tlvdata))

    if buff:
        LOG.warning("Trailing byte received in an LLDP package: %r", buff)

    return lldp_info


def _receive_lldp_packets(sock):
    """Receive LLDP packets and process them.

    :param sock: A bound socket
    :return: A list of tuples in the form (lldp_type, lldp_data)
    """
    pkt = sock.recv(1600)
    # Filter invalid packets
    if not pkt or len(pkt) < 14:
        return []
    # Skip header (dst MAC, src MAC, ethertype)
    pkt = pkt[14:]
    return _parse_tlv(pkt)


def _get_lldp_info(interfaces):
    """Wait for packets on each socket, parse the received LLDP packets."""
    LOG.debug('Getting LLDP info for interfaces %s', interfaces)

    lldp_info = {}
    if not interfaces:
        return {}

    while interfaces:
        LOG.info('Waiting on LLDP info for interfaces: %(interfaces)s, '
                 'timeout: %(timeout)s', {'interfaces': interfaces,
                                          'timeout': CONF.lldp_timeout})

        socks = [interface[1] for interface in interfaces]
        # rlist is a list of sockets ready for reading
        rlist, _, _ = select.select(socks, [], [], CONF.lldp_timeout)
        if not rlist:
            # Empty read list means timeout on all interfaces
            LOG.warning('LLDP timed out, remaining interfaces: %s',
                        interfaces)
            break

        for s in rlist:
            # Find interface name matching socket ready for read
            # Create a copy of interfaces to avoid deleting while iterating.
            for index, interface in enumerate(list(interfaces)):
                if s == interface[1]:
                    try:
                        lldp_info[interface[0]] = _receive_lldp_packets(s)
                    except socket.error:
                        LOG.exception('Socket for network interface %s said '
                                      'that it was ready to read we were '
                                      'unable to read from the socket while '
                                      'trying to get LLDP packet. Skipping '
                                      'this network interface.', interface[0])
                    else:
                        LOG.info('Found LLDP info for interface: %s',
                                 interface[0])
                    # Remove interface from the list, only need one packet
                    del interfaces[index]

    # Add any interfaces that didn't get a packet as empty lists
    for name, _sock in interfaces:
        lldp_info[name] = []

    return lldp_info


def get_default_ip_addr(type, interface_id):
    """Retrieve default IPv4 or IPv6 address."""
    try:
        addrs = netifaces.ifaddresses(interface_id)
        return addrs[type][0]['addr']
    except (ValueError, IndexError, KeyError):
        # No default IP address found
        return None


def get_ipv4_addr(interface_id):
    return get_default_ip_addr(netifaces.AF_INET, interface_id)


def get_ipv6_addr(interface_id):
    return get_default_ip_addr(netifaces.AF_INET6, interface_id)


def get_mac_addr(interface_id):
    try:
        addrs = netifaces.ifaddresses(interface_id)
        return addrs[netifaces.AF_LINK][0]['addr']
    except (ValueError, IndexError, KeyError):
        # No mac address found
        return None


# Other options...
# 1. import os; os.uname()[1]
# 2. import platform; platform.node()
def get_hostname():
    return socket.gethostname()


def interface_has_carrier(interface_name):
    path = '/sys/class/net/{}/carrier'.format(interface_name)
    try:
        with open(path, 'rt') as fp:
            return fp.read().strip() == '1'
    except EnvironmentError:
        LOG.debug('No carrier information for interface %s',
                  interface_name)
        return False


def wrap_ipv6(ip):
    if netutils.is_valid_ipv6(ip):
        return "[%s]" % ip
    return ip


def get_wildcard_address():
    if netutils.is_ipv6_enabled():
        return "::"
    return "0.0.0.0"


def _get_configured_vlans():
    return [x.strip() for x in CONF.enable_vlan_interfaces.split(',')
            if x.strip()]


def _add_vlan_interface(interface, vlan, interfaces_list):

    vlan_name = interface + '.' + vlan

    # if any(x for x in interfaces_list if x.name == vlan_name):
    if any(x.name == vlan_name for x in interfaces_list):
        LOG.info("VLAN interface %s has already been added", vlan_name)
        return ''

    try:
        LOG.info('Adding VLAN interface %s', vlan_name)
        # Add the interface
        utils.execute('ip', 'link', 'add', 'link', interface, 'name',
                      vlan_name, 'type', 'vlan', 'id', vlan,
                      check_exit_code=[0, 2])

        # Bring up interface
        utils.execute('ip', 'link', 'set', 'dev', vlan_name, 'up')

    except Exception as exc:
        LOG.warning('Exception when running ip commands to add VLAN '
                    'interface: %s', exc)
        return ''

    return vlan_name


def _add_vlans_from_lldp(lldp, interface, interfaces_list):
    interfaces = []

    # Get the lldp packets received on this interface
    if lldp:
        for type, value in lldp:
            if (type == LLDP_TLV_ORG_SPECIFIC
                    and value.startswith(LLDP_802dot1_OUI
                                         + dot1_VLAN_NAME)):
                vlan = str(int(value[VLAN_ID_LEN: VLAN_ID_LEN + 4], 16))
                name = _add_vlan_interface(interface, vlan,
                                           interfaces_list)
                if name:
                    interfaces.append(name)
    else:
        LOG.debug('VLAN interface %s does not have lldp info', interface)

    return interfaces


def bring_up_vlan_interfaces(interfaces_list):
    """Bring up vlan interfaces based on kernel params

    Use the configured value of ``enable_vlan_interfaces`` to determine
    if VLAN interfaces should be brought up using ``ip`` commands.  If
    ``enable_vlan_interfaces`` defines a particular vlan then bring up
    that vlan.  If it defines an interface or ``all`` then use LLDP info
    to figure out which VLANs should be brought up.

    :param interfaces_list: List of current interfaces
    :return: List of vlan interface names that have been added
    """
    interfaces = []
    vlan_interfaces = _get_configured_vlans()
    for vlan_int in vlan_interfaces:
        # TODO(bfournie) skip if pxe boot interface
        if '.' in vlan_int:
            # interface and vlan are provided
            interface, vlan = vlan_int.split('.', 1)
            if any(x.name == interface for x in interfaces_list):
                name = _add_vlan_interface(interface, vlan,
                                           interfaces_list)
                if name:
                    interfaces.append(name)
            else:
                LOG.warning('Provided VLAN interface %s does not exist',
                            interface)
        elif CONF.collect_lldp:
            # Get the vlans from lldp info
            if vlan_int == 'all':
                # Use all interfaces
                for iface in interfaces_list:
                    names = _add_vlans_from_lldp(
                        iface.lldp, iface.name, interfaces_list)
                    if names:
                        interfaces.extend(names)
            else:
                # Use provided interface
                lldp = next((x.lldp for x in interfaces_list
                             if x.name == vlan_int), None)
                if lldp:
                    names = _add_vlans_from_lldp(lldp, vlan_int,
                                                 interfaces_list)
                    if names:
                        interfaces.extend(names)
                else:
                    LOG.warning('Provided interface name %s was not found',
                                vlan_int)
        else:
            LOG.warning('Attempting to add VLAN interfaces but specific '
                        'interface not provided and LLDP not enabled')

    return interfaces

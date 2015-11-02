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

from oslo_config import cfg
from oslo_log import log as logging

# FIXME(lucasagomes): If you don't import the agent module the tests in
# this file will fail, it was working before because the agent module was
# being imported at tests/agent.py
from ironic_python_agent.cmd import agent  # noqa

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

LLDP_ETHERTYPE = 0x88cc
IFF_PROMISC = 0x100
SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914


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
                LOG.warning('Failed to open all RawPromiscuousSockets, '
                            'attempting to close any opened sockets.')
                if self.__exit__(*sys.exc_info()):
                    return []
                else:
                    LOG.exception('Could not successfully close all opened '
                                  'RawPromiscuousSockets.')
                    raise
        # No need to return each interfaces ifreq.
        return [(sock[0], sock[1]) for sock in self.interfaces]

    def __exit__(self, exception_type, exception_val, trace):
        if exception_type:
            LOG.exception('Error while using raw socket: %(type)s: %(val)s',
                          {'type': exception_type, 'val': exception_val})

        for _name, sock, ifr in self.interfaces:
            # bitwise or with the opposite of promiscuous mode to remove
            ifr.ifr_flags &= ~IFF_PROMISC
            # If these raise, they shouldn't be caught
            fcntl.ioctl(sock.fileno(), SIOCSIFFLAGS, ifr)
            sock.close()
        # Return True to signify exit correctly, only used internally
        return True

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
    while buff:
        # TLV structure: type (7 bits), length (9 bits), val (0-511 bytes)
        tlvhdr = struct.unpack('!H', buff[:2])[0]
        tlvtype = (tlvhdr & 0xfe00) >> 9
        tlvlen = (tlvhdr & 0x01ff)
        tlvdata = buff[2:tlvlen + 2]
        buff = buff[tlvlen + 2:]
        lldp_info.append((tlvtype, tlvdata))
    return lldp_info


def _receive_lldp_packets(sock):
    """Receive LLDP packets and process them.

    :param sock: A bound socket
    :return: A list of tuples in the form (lldp_type, lldp_data)
    """
    pkt = sock.recv(1600)
    # Filter invalid packets
    if not pkt or len(pkt) < 14:
        return
    # Skip header (dst MAC, src MAC, ethertype)
    pkt = pkt[14:]
    return _parse_tlv(pkt)


def _get_lldp_info(interfaces):
    """Wait for packets on each socket, parse the received LLDP packets."""
    LOG.debug('Getting LLDP info for interfaces %s', interfaces)

    lldp_info = {}
    if not interfaces:
        return {}

    socks = [interface[1] for interface in interfaces]

    while interfaces:
        LOG.info('Waiting on LLDP info for interfaces: %(interfaces)s, '
                 'timeout: %(timeout)s', {'interfaces': interfaces,
                                          'timeout': CONF.lldp_timeout})

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
                    LOG.info('Found LLDP info for interface: %s',
                             interface[0])
                    lldp_info[interface[0]] = (
                        _receive_lldp_packets(s))
                    # Remove interface from the list, only need one packet
                    del interfaces[index]

    # Add any interfaces that didn't get a packet as empty lists
    for name, _sock in interfaces:
        lldp_info[name] = []

    return lldp_info

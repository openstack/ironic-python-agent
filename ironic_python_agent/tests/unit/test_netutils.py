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

import binascii

import mock
from oslo_config import cfg

from ironic_python_agent import netutils
from ironic_python_agent.tests.unit import base

# hexlify-ed output from LLDP packet
FAKE_LLDP_PACKET = binascii.unhexlify(
    '0180c200000e885a92365a3988cc'
    '0000'
    '020704885a92ec5459'
    '040d0545746865726e6574312f3138'
    '06020078'
)

cfg.CONF.import_opt('lldp_timeout', 'ironic_python_agent.config')


def socket_socket_sig(family=None, type=None, proto=None):
    # Signature for socket.socket to be used by mock
    pass


class TestNetutils(base.IronicAgentTest):
    def setUp(self):
        super(TestNetutils, self).setUp()

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('select.select', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_get_lldp_info(self, sock_mock, select_mock, fcntl_mock):
        expected_lldp = {
            'eth1': [
                (0, b''),
                (1, b'\x04\x88Z\x92\xecTY'),
                (2, b'\x05Ethernet1/18'),
                (3, b'\x00x')],
            'eth0': [
                (0, b''),
                (1, b'\x04\x88Z\x92\xecTY'),
                (2, b'\x05Ethernet1/18'),
                (3, b'\x00x')]
        }

        interface_names = ['eth0', 'eth1']

        sock1 = mock.Mock()
        sock1.recv.return_value = FAKE_LLDP_PACKET
        sock1.fileno.return_value = 4
        sock2 = mock.Mock()
        sock2.recv.return_value = FAKE_LLDP_PACKET
        sock2.fileno.return_value = 5

        sock_mock.side_effect = [sock1, sock2]

        select_mock.side_effect = [
            ([sock1], [], []),
            ([sock2], [], [])
        ]

        lldp_info = netutils.get_lldp_info(interface_names)
        self.assertEqual(expected_lldp, lldp_info)

        sock1.bind.assert_called_with(('eth0', netutils.LLDP_ETHERTYPE))
        sock2.bind.assert_called_with(('eth1', netutils.LLDP_ETHERTYPE))

        sock1.recv.assert_called_with(1600)
        sock2.recv.assert_called_with(1600)

        self.assertEqual(1, sock1.close.call_count)
        self.assertEqual(1, sock2.close.call_count)

        # 2 interfaces, 2 calls to enter promiscuous mode, 1 to leave
        self.assertEqual(6, fcntl_mock.call_count)

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('select.select', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_get_lldp_info_multiple(self, sock_mock, select_mock, fcntl_mock):
        expected_lldp = {
            'eth1': [
                (0, b''),
                (1, b'\x04\x88Z\x92\xecTY'),
                (2, b'\x05Ethernet1/18'),
                (3, b'\x00x')],
            'eth0': [
                (0, b''),
                (1, b'\x04\x88Z\x92\xecTY'),
                (2, b'\x05Ethernet1/18'),
                (3, b'\x00x')]
        }

        interface_names = ['eth0', 'eth1']

        sock1 = mock.Mock()
        sock1.recv.return_value = FAKE_LLDP_PACKET
        sock1.fileno.return_value = 4
        sock2 = mock.Mock()
        sock2.recv.return_value = FAKE_LLDP_PACKET
        sock2.fileno.return_value = 5

        sock_mock.side_effect = [sock1, sock2]

        select_mock.side_effect = [
            ([sock1], [], []),
            ([sock2], [], []),
        ]

        lldp_info = netutils.get_lldp_info(interface_names)
        self.assertEqual(expected_lldp, lldp_info)

        sock1.bind.assert_called_with(('eth0', netutils.LLDP_ETHERTYPE))
        sock2.bind.assert_called_with(('eth1', netutils.LLDP_ETHERTYPE))

        sock1.recv.assert_called_with(1600)
        sock2.recv.assert_called_with(1600)

        self.assertEqual(1, sock1.close.call_count)
        self.assertEqual(1, sock2.close.call_count)

        # 2 interfaces, 2 calls to enter promiscuous mode, 1 to leave
        self.assertEqual(6, fcntl_mock.call_count)

        expected_calls = [
            mock.call([sock1, sock2], [], [], cfg.CONF.lldp_timeout),
            mock.call([sock2], [], [], cfg.CONF.lldp_timeout),
        ]
        self.assertEqual(expected_calls, select_mock.call_args_list)

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('select.select', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_get_lldp_info_one_empty_interface(self, sock_mock, select_mock,
                                               fcntl_mock):
        expected_lldp = {
            'eth1': [],
            'eth0': [
                (0, b''),
                (1, b'\x04\x88Z\x92\xecTY'),
                (2, b'\x05Ethernet1/18'),
                (3, b'\x00x')]
        }

        interface_names = ['eth0', 'eth1']

        sock1 = mock.Mock()
        sock1.recv.return_value = FAKE_LLDP_PACKET
        sock1.fileno.return_value = 4
        sock2 = mock.Mock()
        sock2.fileno.return_value = 5

        sock_mock.side_effect = [sock1, sock2]

        select_mock.side_effect = [
            ([sock1], [], []),
            ([], [], []),
        ]

        lldp_info = netutils.get_lldp_info(interface_names)
        self.assertEqual(expected_lldp, lldp_info)

        sock1.bind.assert_called_with(('eth0', netutils.LLDP_ETHERTYPE))
        sock2.bind.assert_called_with(('eth1', netutils.LLDP_ETHERTYPE))

        sock1.recv.assert_called_with(1600)
        sock2.recv.not_called()

        self.assertEqual(1, sock1.close.call_count)
        self.assertEqual(1, sock2.close.call_count)

        # 2 interfaces, 2 calls to enter promiscuous mode, 1 to leave
        self.assertEqual(6, fcntl_mock.call_count)

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('select.select', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_get_lldp_info_empty(self, sock_mock, select_mock, fcntl_mock):
        expected_lldp = {
            'eth1': [],
            'eth0': []
        }

        interface_names = ['eth0', 'eth1']

        sock1 = mock.Mock()
        sock1.fileno.return_value = 4
        sock2 = mock.Mock()
        sock2.fileno.return_value = 5

        sock_mock.side_effect = [sock1, sock2]

        select_mock.side_effect = [
            ([], [], []),
            ([], [], [])
        ]

        lldp_info = netutils.get_lldp_info(interface_names)
        self.assertEqual(expected_lldp, lldp_info)

        sock1.bind.assert_called_with(('eth0', netutils.LLDP_ETHERTYPE))
        sock2.bind.assert_called_with(('eth1', netutils.LLDP_ETHERTYPE))

        sock1.recv.not_called()
        sock2.recv.not_called()

        self.assertEqual(1, sock1.close.call_count)
        self.assertEqual(1, sock2.close.call_count)

        # 2 interfaces * (2 calls to enter promiscuous mode + 1 to leave) = 6
        self.assertEqual(6, fcntl_mock.call_count)

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('select.select', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_get_lldp_info_malformed(self, sock_mock, select_mock, fcntl_mock):
        expected_lldp = {
            'eth1': [],
            'eth0': [],
        }

        interface_names = ['eth0', 'eth1']

        sock1 = mock.Mock()
        sock1.recv.return_value = b'123456789012345'  # odd size
        sock1.fileno.return_value = 4
        sock2 = mock.Mock()
        sock2.recv.return_value = b'1234'  # too small
        sock2.fileno.return_value = 5

        sock_mock.side_effect = [sock1, sock2]

        select_mock.side_effect = [
            ([sock1], [], []),
            ([sock2], [], []),
        ]

        lldp_info = netutils.get_lldp_info(interface_names)
        self.assertEqual(expected_lldp, lldp_info)

        sock1.bind.assert_called_with(('eth0', netutils.LLDP_ETHERTYPE))
        sock2.bind.assert_called_with(('eth1', netutils.LLDP_ETHERTYPE))

        sock1.recv.assert_called_with(1600)
        sock2.recv.assert_called_with(1600)

        self.assertEqual(1, sock1.close.call_count)
        self.assertEqual(1, sock2.close.call_count)

        # 2 interfaces, 2 calls to enter promiscuous mode, 1 to leave
        self.assertEqual(6, fcntl_mock.call_count)

        expected_calls = [
            mock.call([sock1, sock2], [], [], cfg.CONF.lldp_timeout),
            mock.call([sock2], [], [], cfg.CONF.lldp_timeout),
        ]
        self.assertEqual(expected_calls, select_mock.call_args_list)

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_raw_promiscuous_sockets(self, sock_mock, fcntl_mock):
        interfaces = ['eth0', 'ens9f1']
        protocol = 3
        sock1 = mock.Mock()
        sock2 = mock.Mock()

        sock_mock.side_effect = [sock1, sock2]

        with netutils.RawPromiscuousSockets(interfaces, protocol) as sockets:
            # 2 interfaces, 1 get, 1 set call each
            self.assertEqual(4, fcntl_mock.call_count)
            self.assertEqual([('eth0', sock1), ('ens9f1', sock2)], sockets)
            sock1.bind.assert_called_once_with(('eth0', protocol))
            sock2.bind.assert_called_once_with(('ens9f1', protocol))

        self.assertEqual(6, fcntl_mock.call_count)

        sock1.close.assert_called_once_with()
        sock2.close.assert_called_once_with()

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_raw_promiscuous_sockets_bind_fail(self, sock_mock, fcntl_mock):
        interfaces = ['eth0', 'ens9f1']
        protocol = 3
        sock1 = mock.Mock()
        sock2 = mock.Mock()

        sock_mock.side_effect = [sock1, sock2]
        sock2.bind.side_effect = RuntimeError()

        def _run_with_bind_fail():
            with netutils.RawPromiscuousSockets(interfaces, protocol):
                self.fail('Unreachable code')

        self.assertRaises(RuntimeError, _run_with_bind_fail)

        sock1.bind.assert_called_once_with(('eth0', protocol))
        sock2.bind.assert_called_once_with(('ens9f1', protocol))

        self.assertEqual(6, fcntl_mock.call_count)

        sock1.close.assert_called_once_with()
        sock2.close.assert_called_once_with()

    @mock.patch('fcntl.ioctl', autospec=True)
    @mock.patch('socket.socket', autospec=socket_socket_sig)
    def test_raw_promiscuous_sockets_exception(self, sock_mock, fcntl_mock):
        interfaces = ['eth0', 'ens9f1']
        protocol = 3
        sock1 = mock.Mock()
        sock2 = mock.Mock()

        sock_mock.side_effect = [sock1, sock2]

        def _run_with_exception():
            with netutils.RawPromiscuousSockets(interfaces, protocol):
                raise RuntimeError()

        self.assertRaises(RuntimeError, _run_with_exception)

        sock1.bind.assert_called_once_with(('eth0', protocol))
        sock2.bind.assert_called_once_with(('ens9f1', protocol))

        self.assertEqual(6, fcntl_mock.call_count)

        sock1.close.assert_called_once_with()
        sock2.close.assert_called_once_with()

    def test_wrap_ipv6(self):
        res = netutils.wrap_ipv6('1:2::3:4')
        self.assertEqual('[1:2::3:4]', res)

    def test_wrap_ipv6_with_ipv4(self):
        res = netutils.wrap_ipv6('1.2.3.4')
        self.assertEqual('1.2.3.4', res)

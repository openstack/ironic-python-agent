# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import socket
from unittest import mock

from oslo_config import cfg

from ironic_python_agent import errors
from ironic_python_agent import mdns
from ironic_python_agent.tests.unit.base import IronicAgentTest

CONF = cfg.CONF


@mock.patch('ironic_python_agent.utils.get_route_source', autospec=True)
@mock.patch('zeroconf.Zeroconf', autospec=True)
class GetEndpointTestCase(IronicAgentTest):
    def test_simple(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=80,
            properties={},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('http://192.168.1.1:80', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )
        mock_zc.return_value.close.assert_called_once_with()

    def test_v6(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            port=80,
            properties={},
            **{'parsed_addresses.return_value': ['::2']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('http://[::2]:80', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )
        mock_zc.return_value.close.assert_called_once_with()

    def test_skip_invalid(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            port=80,
            properties={},
            **{'parsed_addresses.return_value': ['::1', '::2', '::3']}
        )
        mock_route.side_effect = [None, '::4']

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('http://[::3]:80', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )
        mock_zc.return_value.close.assert_called_once_with()
        self.assertEqual(2, mock_route.call_count)

    def test_fallback(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            port=80,
            properties={},
            **{'parsed_addresses.return_value': ['::2', '::3']}
        )
        mock_route.side_effect = [None, None]

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('http://[::2]:80', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )
        mock_zc.return_value.close.assert_called_once_with()
        self.assertEqual(2, mock_route.call_count)

    def test_localhost_only(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            port=80,
            properties={},
            **{'parsed_addresses.return_value': ['::1']}
        )

        self.assertRaises(errors.ServiceLookupFailure,
                          mdns.get_endpoint, 'baremetal')
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )
        mock_zc.return_value.close.assert_called_once_with()
        self.assertFalse(mock_route.called)

    def test_https(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=443,
            properties={},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('https://192.168.1.1:443', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )

    def test_with_custom_port_and_path(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=8080,
            properties={b'path': b'/baremetal'},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('https://192.168.1.1:8080/baremetal', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )

    def test_with_custom_port_path_and_protocol(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=8080,
            properties={b'path': b'/baremetal', b'protocol': b'http'},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('http://192.168.1.1:8080/baremetal', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )

    def test_with_params(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=80,
            properties={b'ipa_debug': True},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('http://192.168.1.1:80', endp)
        self.assertEqual({'ipa_debug': True}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )

    def test_binary_data(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=80,
            properties={b'ipa_debug': True, b'binary': b'\xe2\x28\xa1'},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('http://192.168.1.1:80', endp)
        self.assertEqual({'ipa_debug': True, 'binary': b'\xe2\x28\xa1'},
                         params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )

    def test_invalid_key(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=80,
            properties={b'ipa_debug': True, b'\xc3\x28': b'value'},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        self.assertRaisesRegex(errors.ServiceLookupFailure,
                               'Cannot decode key',
                               mdns.get_endpoint, 'baremetal')
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )

    def test_with_server(self, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = mock.Mock(
            address=socket.inet_aton('192.168.1.1'),
            port=443,
            server='openstack.example.com.',
            properties={},
            **{'parsed_addresses.return_value': ['192.168.1.1']}
        )

        endp, params = mdns.get_endpoint('baremetal')
        self.assertEqual('https://openstack.example.com:443', endp)
        self.assertEqual({}, params)
        mock_zc.return_value.get_service_info.assert_called_once_with(
            'baremetal._openstack._tcp.local.',
            'baremetal._openstack._tcp.local.'
        )

    @mock.patch('time.sleep', autospec=True)
    def test_not_found(self, mock_sleep, mock_zc, mock_route):
        mock_zc.return_value.get_service_info.return_value = None

        self.assertRaisesRegex(errors.ServiceLookupFailure,
                               'baremetal service',
                               mdns.get_endpoint, 'baremetal')
        self.assertEqual(CONF.mdns.lookup_attempts - 1, mock_sleep.call_count)

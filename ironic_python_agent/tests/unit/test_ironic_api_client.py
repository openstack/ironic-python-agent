# Copyright 2013 Rackspace, Inc.
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

import mock
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import ironic_api_client

API_URL = 'http://agent-api.ironic.example.org/'


class FakeResponse(object):
    def __init__(self, content=None, status_code=200, headers=None):
        content = content or {}
        self.content = jsonutils.dumps(content)
        self.status_code = status_code
        self.headers = headers or {}


class TestBaseIronicPythonAgent(test_base.BaseTestCase):
    def setUp(self):
        super(TestBaseIronicPythonAgent, self).setUp()
        self.api_client = ironic_api_client.APIClient(API_URL)
        self.hardware_info = {
            'interfaces': [
                hardware.NetworkInterface(
                    'eth0', '00:0c:29:8c:11:b1', vendor='0x15b3',
                    product='0x1014'),
                hardware.NetworkInterface(
                    'eth1', '00:0c:29:8c:11:b2',
                    lldp=[(1, '04885a92ec5459'),
                          (2, '0545746865726e6574312f3138')],
                    vendor='0x15b3', product='0x1014'),
            ],
            'cpu': hardware.CPU('Awesome Jay CPU x10 9001', '9001', '10',
                                'ARMv9'),
            'disks': [
                hardware.BlockDevice('/dev/sdj', 'small', '9001', False),
                hardware.BlockDevice('/dev/hdj', 'big', '9002', False),
            ],
            'memory': hardware.Memory(total='8675309',
                                      physical_mb='8675'),
        }

    def test_successful_heartbeat(self):
        response = FakeResponse(status_code=202)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('192.0.2.1', '9999')
        )

        heartbeat_path = 'v1/heartbeat/deadbeef-dabb-ad00-b105-f00d00bab10c'
        request_args = self.api_client.session.request.call_args[0]
        data = self.api_client.session.request.call_args[1]['data']
        self.assertEqual('POST', request_args[0])
        self.assertEqual(API_URL + heartbeat_path, request_args[1])
        self.assertEqual('{"callback_url": "http://192.0.2.1:9999"}', data)

    def test_successful_heartbeat_ip6(self):
        response = FakeResponse(status_code=202)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('fc00:1111::4', '9999')
        )

        heartbeat_path = 'v1/heartbeat/deadbeef-dabb-ad00-b105-f00d00bab10c'
        request_args = self.api_client.session.request.call_args[0]
        data = self.api_client.session.request.call_args[1]['data']
        self.assertEqual('POST', request_args[0])
        self.assertEqual(API_URL + heartbeat_path, request_args[1])
        self.assertEqual('{"callback_url": "http://[fc00:1111::4]:9999"}',
                         data)

    def test_heartbeat_requests_exception(self):
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = Exception('api is down!')

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_invalid_status_code(self):
        response = FakeResponse(status_code=404)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_409_status_code(self):
        response = FakeResponse(status_code=409)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatConflictError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    @mock.patch('eventlet.greenthread.sleep')
    @mock.patch('ironic_python_agent.ironic_api_client.APIClient._do_lookup')
    def test_lookup_node(self, lookup_mock, sleep_mock):
        content = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        lookup_mock.side_effect = loopingcall.LoopingCallDone(
            retvalue=content)
        returned_content = self.api_client.lookup_node(
            hardware_info=self.hardware_info,
            timeout=300,
            starting_interval=1)

        self.assertEqual(content, returned_content)

    @mock.patch('eventlet.greenthread.sleep')
    @mock.patch('ironic_python_agent.ironic_api_client.APIClient._do_lookup')
    def test_lookup_timeout(self, lookup_mock, sleep_mock):
        lookup_mock.side_effect = loopingcall.LoopingCallTimeOut()
        self.assertRaises(errors.LookupNodeError,
                          self.api_client.lookup_node,
                          hardware_info=self.hardware_info,
                          timeout=300,
                          starting_interval=1)

    def test_do_lookup(self):
        response = FakeResponse(status_code=200, content={
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(loopingcall.LoopingCallDone,
                          self.api_client._do_lookup,
                          hardware_info=self.hardware_info,
                          node_uuid=None)

        url = '{api_url}v1/lookup'.format(api_url=API_URL)
        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual('GET', request_args[0])
        self.assertEqual(url, request_args[1])
        params = self.api_client.session.request.call_args[1]['params']
        self.assertEqual({'addresses': '00:0c:29:8c:11:b1,00:0c:29:8c:11:b2'},
                         params)

    def test_do_lookup_with_uuid(self):
        response = FakeResponse(status_code=200, content={
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(loopingcall.LoopingCallDone,
                          self.api_client._do_lookup,
                          hardware_info=self.hardware_info,
                          node_uuid='someuuid')

        url = '{api_url}v1/lookup'.format(api_url=API_URL)
        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual('GET', request_args[0])
        self.assertEqual(url, request_args[1])
        params = self.api_client.session.request.call_args[1]['params']
        self.assertEqual({'addresses': '00:0c:29:8c:11:b1,00:0c:29:8c:11:b2',
                          'node_uuid': 'someuuid'},
                         params)

    def test_do_lookup_bad_response_code(self):
        response = FakeResponse(status_code=400, content={
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        error = self.api_client._do_lookup(self.hardware_info,
                                           node_uuid=None)

        self.assertFalse(error)

    def test_do_lookup_bad_response_data(self):
        response = FakeResponse(status_code=200, content={
            'heartbeat_timeout': 300
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        error = self.api_client._do_lookup(self.hardware_info,
                                           node_uuid=None)

        self.assertFalse(error)

    def test_do_lookup_no_heartbeat_timeout(self):
        response = FakeResponse(status_code=200, content={
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        error = self.api_client._do_lookup(self.hardware_info,
                                           node_uuid=None)

        self.assertFalse(error)

    def test_do_lookup_bad_response_body(self):
        response = FakeResponse(status_code=200, content={
            'node_node': 'also_not_node'
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        error = self.api_client._do_lookup(self.hardware_info,
                                           node_uuid=None)

        self.assertFalse(error)

    def test_get_agent_url_ipv4(self):
        url = self.api_client._get_agent_url(('1.2.3.4', '9999'))
        self.assertEqual('http://1.2.3.4:9999', url)

    def test_get_agent_url_ipv6(self):
        url = self.api_client._get_agent_url(('1:2::3:4', '9999'))
        self.assertEqual('http://[1:2::3:4]:9999', url)

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

import httmock
import json
import mock
import time
import unittest

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import ironic_api_client

API_URL = 'http://agent-api.ironic.example.org/'


class TestBaseIronicPythonAgent(unittest.TestCase):
    def setUp(self):
        self.api_client = ironic_api_client.APIClient(API_URL)
        self.hardware_info = [
            hardware.HardwareInfo(hardware.HardwareType.MAC_ADDRESS,
                                  'aa:bb:cc:dd:ee:ff'),
            hardware.HardwareInfo(hardware.HardwareType.MAC_ADDRESS,
                                  'ff:ee:dd:cc:bb:aa'),
        ]

    def test_successful_heartbeat(self):
        expected_heartbeat_before = time.time() + 120
        response = httmock.response(status_code=204, headers={
            'Heartbeat-Before': expected_heartbeat_before,
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        heartbeat_before = self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('192.0.2.1', '9999')
        )

        self.assertEqual(heartbeat_before, expected_heartbeat_before)

        heartbeat_path = 'v1/nodes/deadbeef-dabb-ad00-b105-f00d00bab10c/' \
                       'vendor_passthru/heartbeat'
        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual(request_args[0], 'POST')
        self.assertEqual(request_args[1], API_URL + heartbeat_path)

    def test_heartbeat_requests_exception(self):
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = Exception('api is down!')

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_invalid_status_code(self):
        response = httmock.response(status_code=404)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_missing_heartbeat_before_header(self):
        response = httmock.response(status_code=204)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_invalid_heartbeat_before_header(self):
        response = httmock.response(status_code=204, headers={
            'Heartbeat-Before': 'tomorrow',
        })
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    def test_lookup_node(self):
        response = httmock.response(status_code=200, content={
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'heartbeat_timeout': 300
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.api_client.lookup_node(hardware_info=self.hardware_info)

        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual(request_args[0], 'POST')
        self.assertEqual(request_args[1],
                API_URL + 'v1/drivers/teeth/vendor_passthru/lookup')

        data = self.api_client.session.request.call_args[1]['data']
        content = json.loads(data)
        self.assertEqual(content['hardware'], [
            {
                'type': 'mac_address',
                'id': 'aa:bb:cc:dd:ee:ff',
            },
            {
                'type': 'mac_address',
                'id': 'ff:ee:dd:cc:bb:aa',
            },
        ])

    def test_lookup_node_bad_response_code(self):
        response = httmock.response(status_code=400, content={
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.LookupNodeError,
                          self.api_client.lookup_node,
                          hardware_info=self.hardware_info)

    def test_lookup_node_bad_response_data(self):
        response = httmock.response(status_code=200, content={
            'heartbeat_timeout': 300
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.LookupNodeError,
                          self.api_client.lookup_node,
                          hardware_info=self.hardware_info)

    def test_lookup_node_no_heartbeat_timeout(self):
        response = httmock.response(status_code=200, content={
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.LookupNodeError,
                          self.api_client.lookup_node,
                          hardware_info=self.hardware_info)

    def test_lookup_node_bad_response_body(self):
        response = httmock.response(status_code=200, content={
            'node_node': 'also_not_node'
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.LookupNodeError,
                          self.api_client.lookup_node,
                          hardware_info=self.hardware_info)

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

from teeth_agent import errors
from teeth_agent import hardware
from teeth_agent import overlord_agent_api

API_URL = 'http://agent-api.overlord.example.org/'


class TestBaseTeethAgent(unittest.TestCase):
    def setUp(self):
        self.api_client = overlord_agent_api.APIClient(API_URL)
        self.hardware_info = [
            hardware.HardwareInfo(hardware.HardwareType.MAC_ADDRESS,
                                  'a:b:c:d'),
            hardware.HardwareInfo(hardware.HardwareType.MAC_ADDRESS,
                                  '0:1:2:3'),
        ]

    def test_successful_heartbeat(self):
        expected_heartbeat_before = time.time() + 120
        response = httmock.response(status_code=204, headers={
            'Heartbeat-Before': expected_heartbeat_before,
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        heartbeat_before = self.api_client.heartbeat(uuid='fake-uuid')

        self.assertEqual(heartbeat_before, expected_heartbeat_before)

        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual(request_args[0], 'POST')
        self.assertEqual(request_args[1], API_URL + 'v1/nodes/fake-uuid/vendor'
                                                    '_passthru/heartbeat')

    def test_heartbeat_requests_exception(self):
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = Exception('api is down!')

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='fake-uuid')

    def test_heartbeat_invalid_status_code(self):
        response = httmock.response(status_code=404)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='fake-uuid')

    def test_heartbeat_missing_heartbeat_before_header(self):
        response = httmock.response(status_code=204)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='fake-uuid')

    def test_heartbeat_invalid_heartbeat_before_header(self):
        response = httmock.response(status_code=204, headers={
            'Heartbeat-Before': 'tomorrow',
        })
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='fake-uuid')

    def test_get_configuration(self):
        response = httmock.response(status_code=200, content={
            'node': {
                'uuid': 'fake-uuid'
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.api_client.get_configuration(
            mac_addrs=['aa:bb:cc:dd:ee:ff', '42:42:42:42:42:42'],
            ipaddr='42.42.42.42',
            hardware_info=self.hardware_info,
            version='15',
            mode='STANDBY',
        )

        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual(request_args[0], 'POST')
        self.assertEqual(request_args[1], API_URL + 'v1/drivers/teeth/lookup')

        data = self.api_client.session.request.call_args[1]['data']
        content = json.loads(data)
        self.assertEqual(content['mode'], 'STANDBY')
        self.assertEqual(content['version'], '15')
        self.assertEqual(content['hardware'], [
            {
                'type': 'mac_address',
                'id': 'a:b:c:d',
            },
            {
                'type': 'mac_address',
                'id': '0:1:2:3',
            },
        ])
        self.assertEqual(content['agent_url'], 'http://42.42.42.42:9999')

    def test_get_configuration_bad_response_code(self):
        response = httmock.response(status_code=400, content={
            'node': {
                'uuid': 'fake-uuid'
            }
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.ConfigurationError,
                          self.api_client.get_configuration,
                          mac_addrs=['aa:bb:cc:dd:ee:ff',
                                      '42:42:42:42:42:42'],
                          ipaddr='42.42.42.42',
                          hardware_info=self.hardware_info,
                          version='15',
                          mode='STANDBY',
        )

    def test_get_configuration_bad_response_data(self):
        response = httmock.response(status_code=200, content={'a'})

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.ConfigurationError,
                          self.api_client.get_configuration,
                          mac_addrs=['aa:bb:cc:dd:ee:ff',
                                      '42:42:42:42:42:42'],
                          ipaddr='42.42.42.42',
                          hardware_info=self.hardware_info,
                          version='15',
                          mode='STANDBY',
        )

    def test_get_configuration_bad_response_body(self):
        response = httmock.response(status_code=200, content={
            'node_node': 'also_not_node'
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.ConfigurationError,
                          self.api_client.get_configuration,
                          mac_addrs=['aa:bb:cc:dd:ee:ff',
                                      '42:42:42:42:42:42'],
                          ipaddr='42.42.42.42',
                          hardware_info=self.hardware_info,
                          version='15',
                          mode='STANDBY',
        )
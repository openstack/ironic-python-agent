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
from teeth_agent import overlord_agent_api

API_URL = 'http://agent-api.overlord.example.org/'


class TestBaseTeethAgent(unittest.TestCase):
    def setUp(self):
        self.api_client = overlord_agent_api.APIClient(API_URL)

    def test_successful_heartbeat(self):
        expected_heartbeat_before = time.time() + 120
        response = httmock.response(status_code=204, headers={
            'Heartbeat-Before': expected_heartbeat_before,
        })

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        heartbeat_before = self.api_client.heartbeat(
            url='http://1.2.3.4:9999/',
            mac_addr='a:b:c:d',
            version='15',
            mode='STANDBY')

        self.assertEqual(heartbeat_before, expected_heartbeat_before)

        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual(request_args[0], 'PUT')
        self.assertEqual(request_args[1], API_URL + 'v1/agents/a:b:c:d')

        data = self.api_client.session.request.call_args[1]['data']
        content = json.loads(data)
        self.assertEqual(content['url'], 'http://1.2.3.4:9999/')
        self.assertEqual(content['mode'], 'STANDBY')
        self.assertEqual(content['version'], '15')

    def test_heartbeat_requests_exception(self):
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = Exception('api is down!')

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          url='http://1.2.3.4:9999/',
                          mac_addr='a:b:c:d',
                          version='15',
                          mode='STANDBY')

    def test_heartbeat_invalid_status_code(self):
        response = httmock.response(status_code=404)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          url='http://1.2.3.4:9999/',
                          mac_addr='a:b:c:d',
                          version='15',
                          mode='STANDBY')

    def test_heartbeat_missing_heartbeat_before_header(self):
        response = httmock.response(status_code=204)
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          url='http://1.2.3.4:9999/',
                          mac_addr='a:b:c:d',
                          version='15',
                          mode='STANDBY')

    def test_heartbeat_invalid_heartbeat_before_header(self):
        response = httmock.response(status_code=204, headers={
            'Heartbeat-Before': 'tomorrow',
        })
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          url='http://1.2.3.4:9999/',
                          mac_addr='a:b:c:d',
                          version='15',
                          mode='STANDBY')

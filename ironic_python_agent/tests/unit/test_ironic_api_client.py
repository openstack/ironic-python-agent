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

import json
from unittest import mock

from oslo_config import cfg
import requests

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import ironic_api_client
from ironic_python_agent.tests.unit import base
from ironic_python_agent import version

API_URL = 'http://agent-api.ironic.example.org/'

CONF = cfg.CONF


class FakeResponse(object):
    def __init__(self, content=None, status_code=200, headers=None):
        content = content or {}
        self.text = json.dumps(content)
        # TODO(dtantsur): remove in favour of using text/json()
        self.content = self.text.encode('utf-8')
        self._json = content
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json


class TestBaseIronicPythonAgent(base.IronicAgentTest):
    def setUp(self):
        super(TestBaseIronicPythonAgent, self).setUp()
        self.api_client = ironic_api_client.APIClient(API_URL)
        self.api_client._ironic_api_version = (
            ironic_api_client.MIN_IRONIC_VERSION)
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

    def test__get_ironic_api_version_already_set(self):
        self.api_client.session.request = mock.create_autospec(
            self.api_client.session.request,
            return_value=None)

        self.assertFalse(self.api_client.session.request.called)
        self.assertEqual(ironic_api_client.MIN_IRONIC_VERSION,
                         self.api_client._get_ironic_api_version())

    def test__get_ironic_api_version_set_via_conf(self):
        self.api_client._ironic_api_version = None
        CONF.set_override('ironic_api_version', "1.47")
        self.api_client.session.request = mock.create_autospec(
            self.api_client.session.request,
            return_value=None)

        self.assertEqual((1, 47), self.api_client._get_ironic_api_version())
        self.assertFalse(self.api_client.session.request.called)

    def test__get_ironic_api_version_error(self):
        self.api_client._ironic_api_version = None
        self.api_client.session.request = mock.create_autospec(
            self.api_client.session.request,
            return_value=None)
        self.api_client.session.request.side_effect = Exception("Boom")

        self.assertEqual(ironic_api_client.MIN_IRONIC_VERSION,
                         self.api_client._get_ironic_api_version())

    def test__get_ironic_api_version_fresh(self):
        self.api_client._ironic_api_version = None
        response = FakeResponse(status_code=200, content={
            "default_version": {
                "id": "v1",
                "links": [
                    {
                        "href": "http://127.0.0.1:6385/v1/",
                        "rel": "self"
                    }
                ],
                "min_version": "1.1",
                "status": "CURRENT",
                "version": "1.31"
            }
        })
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertEqual((1, 31), self.api_client._get_ironic_api_version())
        self.assertEqual((1, 31), self.api_client._ironic_api_version)

    def test_successful_heartbeat(self):
        response = FakeResponse(status_code=202)
        req_id = "req-14c99bd0-1bb5-4d74-972b-e282a50ce441"
        self.config(global_request_id=req_id)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response
        self.api_client._ironic_api_version = (
            ironic_api_client.AGENT_VERSION_IRONIC_VERSION)

        self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('192.0.2.1', '9999')
        )

        heartbeat_path = 'v1/heartbeat/deadbeef-dabb-ad00-b105-f00d00bab10c'
        request_args = self.api_client.session.request.call_args[0]
        request_kwargs = self.api_client.session.request.call_args[1]
        data = request_kwargs["data"]
        self.assertEqual('POST', request_args[0])
        request_headers = request_kwargs["headers"]
        self.assertEqual(
            req_id, request_headers["X-OpenStack-Request-ID"])
        self.assertEqual(API_URL + heartbeat_path, request_args[1])
        expected_data = {
            'callback_url': 'http://192.0.2.1:9999',
            'agent_version': version.__version__}
        self.assertEqual(json.dumps(expected_data), data)

    def test_successful_heartbeat_ip6(self):
        response = FakeResponse(status_code=202)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response
        self.api_client._ironic_api_version = (
            ironic_api_client.AGENT_VERSION_IRONIC_VERSION)

        self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('fc00:1111::4', '9999')
        )

        heartbeat_path = 'v1/heartbeat/deadbeef-dabb-ad00-b105-f00d00bab10c'
        request_args = self.api_client.session.request.call_args[0]
        data = self.api_client.session.request.call_args[1]['data']
        self.assertEqual('POST', request_args[0])
        self.assertEqual(API_URL + heartbeat_path, request_args[1])
        expected_data = {
            'callback_url': 'http://[fc00:1111::4]:9999',
            'agent_version': version.__version__}
        self.assertEqual(json.dumps(expected_data), data)

    def test_successful_heartbeat_with_token(self):
        response = FakeResponse(status_code=202)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response
        self.api_client._ironic_api_version = (
            ironic_api_client.AGENT_TOKEN_IRONIC_VERSION)
        self.api_client.agent_token = 'magical'

        self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('192.0.2.1', '9999')
        )

        heartbeat_path = 'v1/heartbeat/deadbeef-dabb-ad00-b105-f00d00bab10c'
        request_args = self.api_client.session.request.call_args[0]
        data = self.api_client.session.request.call_args[1]['data']
        self.assertEqual('POST', request_args[0])
        self.assertEqual(API_URL + heartbeat_path, request_args[1])
        expected_data = {
            'callback_url': 'http://192.0.2.1:9999',
            'agent_token': 'magical',
            'agent_version': version.__version__}
        self.assertEqual(json.dumps(expected_data), data)

    def test_heartbeat_agent_version_unsupported(self):
        response = FakeResponse(status_code=202)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response
        self.api_client._ironic_api_version = (1, 31)

        self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('fc00:1111::4', '9999')
        )

        heartbeat_path = 'v1/heartbeat/deadbeef-dabb-ad00-b105-f00d00bab10c'
        request_args = self.api_client.session.request.call_args[0]
        data = self.api_client.session.request.call_args[1]['data']
        self.assertEqual('POST', request_args[0])
        self.assertEqual(API_URL + heartbeat_path, request_args[1])
        expected_data = {
            'callback_url': 'http://[fc00:1111::4]:9999'}
        self.assertEqual(json.dumps(expected_data), data)

    def test_successful_heartbeat_with_verify_ca(self):
        response = FakeResponse(status_code=202)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response
        self.api_client._ironic_api_version = (
            ironic_api_client.AGENT_VERIFY_CA_IRONIC_VERSION)
        self.api_client.agent_token = 'magical'

        self.api_client.heartbeat(
            uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
            advertise_address=('192.0.2.1', '9999'),
            advertise_protocol='https',
            generated_cert='I am a cert',
        )

        heartbeat_path = 'v1/heartbeat/deadbeef-dabb-ad00-b105-f00d00bab10c'
        request_args = self.api_client.session.request.call_args[0]
        data = self.api_client.session.request.call_args[1]['data']
        self.assertEqual('POST', request_args[0])
        self.assertEqual(API_URL + heartbeat_path, request_args[1])
        expected_data = {
            'callback_url': 'https://192.0.2.1:9999',
            'agent_token': 'magical',
            'agent_version': version.__version__,
            'agent_verify_ca': 'I am a cert'}
        self.assertEqual(json.dumps(expected_data), data)
        headers = self.api_client.session.request.call_args[1]['headers']
        self.assertEqual(
            '%d.%d' % ironic_api_client.AGENT_VERIFY_CA_IRONIC_VERSION,
            headers['X-OpenStack-Ironic-API-Version'])

    def test_heartbeat_requests_exception(self):
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = Exception('api is down!')

        self.assertRaises(errors.HeartbeatError,
                          self.api_client.heartbeat,
                          uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                          advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_invalid_status_code(self):
        response = FakeResponse(status_code=404)
        response.text = 'Not a JSON'
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaisesRegex(errors.HeartbeatError,
                               'Error 404: Not a JSON',
                               self.api_client.heartbeat,
                               uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                               advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_error_format_1(self):
        response = FakeResponse(
            status_code=404,
            content={'error_message': '{"faultcode": "Client", '
                     '"faultstring": "Resource could not be found.", '
                     '"debuginfo": null}'})
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaisesRegex(errors.HeartbeatError,
                               'Error 404: Resource could not be found',
                               self.api_client.heartbeat,
                               uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                               advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_error_format_2(self):
        response = FakeResponse(
            status_code=404,
            content={'error_message': {
                "faultcode\\": "Client",
                "faultstring": "Resource could not be found.",
                "debuginfo": None}})
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaisesRegex(errors.HeartbeatError,
                               'Error 404: Resource could not be found',
                               self.api_client.heartbeat,
                               uuid='deadbeef-dabb-ad00-b105-f00d00bab10c',
                               advertise_address=('192.0.2.1', '9999'))

    def test_heartbeat_error_format_3(self):
        response = FakeResponse(
            status_code=404,
            content={'error_message': {
                "code": 404,
                "title": "Resource could not be found.",
                "description": None}})
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertRaisesRegex(errors.HeartbeatError,
                               'Error 404: Resource could not be found',
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

    def test_heartbeat_requests_connection_error(self):
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = \
            requests.exceptions.ConnectionError
        self.assertRaisesRegex(errors.HeartbeatConnectionError,
                               'transitory network failure or blocking port',
                               self.api_client.heartbeat,
                               uuid='meow',
                               advertise_address=('192.0.2.1', '9999'))

    @mock.patch('time.sleep', autospec=True)
    @mock.patch('ironic_python_agent.ironic_api_client.APIClient._do_lookup',
                autospec=True)
    def test_lookup_node(self, lookup_mock, sleep_mock):
        content = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        lookup_mock.return_value = content
        returned_content = self.api_client.lookup_node(
            hardware_info=self.hardware_info,
            timeout=300,
            starting_interval=1)

        self.assertEqual(content, returned_content)

    @mock.patch('time.sleep', autospec=True)
    @mock.patch('ironic_python_agent.ironic_api_client.APIClient._do_lookup',
                autospec=True)
    def test_lookup_node_retries(self, lookup_mock, sleep_mock):
        content = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        lookup_mock.side_effect = [False, content]
        returned_content = self.api_client.lookup_node(
            hardware_info=self.hardware_info,
            timeout=300,
            starting_interval=0.001)

        self.assertEqual(content, returned_content)

    @mock.patch('time.sleep', autospec=True)
    @mock.patch('ironic_python_agent.ironic_api_client.APIClient._do_lookup',
                autospec=True)
    def test_lookup_timeout(self, lookup_mock, sleep_mock):
        lookup_mock.return_value = False
        self.assertRaises(errors.LookupNodeError,
                          self.api_client.lookup_node,
                          hardware_info=self.hardware_info,
                          timeout=0.1,
                          starting_interval=0.001)

    def test_do_lookup(self):
        content = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        response = FakeResponse(status_code=200, content=content)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertEqual(content, self.api_client._do_lookup(
            hardware_info=self.hardware_info,
            node_uuid=None))

        url = '{api_url}v1/lookup'.format(api_url=API_URL)
        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual('GET', request_args[0])
        self.assertEqual(url, request_args[1])
        params = self.api_client.session.request.call_args[1]['params']
        self.assertEqual({'addresses': '00:0c:29:8c:11:b1,00:0c:29:8c:11:b2'},
                         params)

    def test_do_lookup_with_uuid(self):
        content = {
            'node': {
                'uuid': 'deadbeef-dabb-ad00-b105-f00d00bab10c'
            },
            'config': {
                'heartbeat_timeout': 300
            }
        }
        response = FakeResponse(status_code=200, content=content)

        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.return_value = response

        self.assertEqual(content, self.api_client._do_lookup(
            hardware_info=self.hardware_info,
            node_uuid='someuuid'))

        url = '{api_url}v1/lookup'.format(api_url=API_URL)
        request_args = self.api_client.session.request.call_args[0]
        self.assertEqual('GET', request_args[0])
        self.assertEqual(url, request_args[1])
        params = self.api_client.session.request.call_args[1]['params']
        self.assertEqual({'addresses': '00:0c:29:8c:11:b1,00:0c:29:8c:11:b2',
                          'node_uuid': 'someuuid'},
                         params)

    @mock.patch.object(ironic_api_client, 'LOG', autospec=True)
    def test_do_lookup_transient_exceptions(self, mock_log):
        exc_list = [requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout,
                    requests.exceptions.HTTPError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ConnectTimeout]
        self.api_client.session.request = mock.Mock()
        for exc in exc_list:
            self.api_client.session.request.reset_mock()
            mock_log.reset_mock()
            self.api_client.session.request.side_effect = exc
            error = self.api_client._do_lookup(self.hardware_info,
                                               node_uuid=None)
            self.assertFalse(error)
            mock_log.error.assert_has_calls([])
            self.assertEqual(1, mock_log.warning.call_count)

    @mock.patch.object(ironic_api_client, 'LOG', autospec=True)
    def test_do_lookup_unknown_exception(self, mock_log):
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = \
            requests.exceptions.RequestException('meow')
        self.assertFalse(
            self.api_client._do_lookup(self.hardware_info,
                                       node_uuid=None))
        self.assertEqual(1, mock_log.exception.call_count)

    @mock.patch.object(ironic_api_client, 'LOG', autospec=True)
    def test_do_lookup_unknown_exception_fallback(self, mock_log):
        mock_log.exception.side_effect = TypeError
        self.api_client.session.request = mock.Mock()
        self.api_client.session.request.side_effect = \
            requests.exceptions.RequestException('meow')
        self.assertRaises(errors.LookupNodeError,
                          self.api_client._do_lookup,
                          self.hardware_info,
                          node_uuid=None)
        self.assertEqual(1, mock_log.exception.call_count)
        self.assertEqual(2, mock_log.error.call_count)

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

    def test_get_agent_url_protocol(self):
        url = self.api_client._get_agent_url(('1:2::3:4', '9999'), 'https')
        self.assertEqual('https://[1:2::3:4]:9999', url)

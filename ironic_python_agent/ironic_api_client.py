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

import json

import requests

from ironic_python_agent import encoding
from ironic_python_agent import errors


class APIClient(object):
    api_version = 'v1'

    def __init__(self, api_url):
        self.api_url = api_url.rstrip('/')
        self.session = requests.Session()
        self.encoder = encoding.RESTJSONEncoder()

    def _request(self, method, path, data=None):
        request_url = '{api_url}{path}'.format(api_url=self.api_url, path=path)

        if data is not None:
            data = self.encoder.encode(data)

        request_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        return self.session.request(method,
                                    request_url,
                                    headers=request_headers,
                                    data=data)

    def heartbeat(self, uuid, advertise_address):
        path = '/{api_version}/nodes/{uuid}/vendor_passthru/heartbeat'.format(
            api_version=self.api_version,
            uuid=uuid
        )
        data = {
            'agent_url': self._get_agent_url(advertise_address)
        }
        try:
            response = self._request('POST', path, data=data)
        except Exception as e:
            raise errors.HeartbeatError(str(e))

        if response.status_code != requests.codes.NO_CONTENT:
            msg = 'Invalid status code: {0}'.format(response.status_code)
            raise errors.HeartbeatError(msg)

        try:
            return float(response.headers['Heartbeat-Before'])
        except KeyError:
            raise errors.HeartbeatError('Missing Heartbeat-Before header')
        except Exception:
            raise errors.HeartbeatError('Invalid Heartbeat-Before header')

    def lookup_node(self, hardware_info):
        path = '/{api_version}/drivers/teeth/lookup'.format(
            api_version=self.api_version
        )
        # This hardware won't be saved on the node currently, because of how
        # driver_vendor_passthru is implemented (no node saving).
        data = {
            'hardware': hardware_info,
        }

        try:
            response = self._request('POST', path, data=data)
        except Exception as e:
            raise errors.LookupNodeError(str(e))

        if response.status_code != requests.codes.OK:
            msg = 'Invalid status code: {0}'.format(response.status_code)
            raise errors.LookupNodeError(msg)

        try:
            content = json.loads(response.content)
        except Exception as e:
            raise errors.LookupNodeError('Error decoding response: '
                                            + str(e))

        if 'node' not in content or 'uuid' not in content['node']:
            raise errors.LookupNodeError('Got invalid data from the API: '
                                            '{0}'.format(content))
        return content['node']

    def _get_agent_url(self, advertise_address):
        return 'http://{0}:{1}'.format(advertise_address[0],
                                       advertise_address[1])

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

from teeth_agent import encoding
from teeth_agent import errors


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

    def heartbeat(self, hardware_info, mode, version):
        path = '/{api_version}/agents'.format(api_version=self.api_version)

        data = {
            'hardware': hardware_info,
            'mode': mode,
            'version': version,
        }

        try:
            response = self._request('PUT', path, data=data)
        except Exception as e:
            raise errors.HeartbeatError(str(e))

        if response.status_code != requests.codes.NO_CONTENT:
            msg = 'Invalid status code: {}'.format(response.status_code)
            raise errors.HeartbeatError(msg)

        try:
            return float(response.headers['Heartbeat-Before'])
        except KeyError:
            raise errors.HeartbeatError('Missing Heartbeat-Before header')
        except Exception:
            raise errors.HeartbeatError('Invalid Heartbeat-Before header')

    def get_configuration(self, mac_addr):
        path = '/{api_version}/agents/{mac_addr}/configuration'.format(
            api_version=self.api_version,
            mac_addr=mac_addr)

        response = self._request('GET', path)

        if response.status_code != requests.codes.OK:
            msg = 'Invalid status code: {}'.format(response.status_code)
            raise errors.OverlordAPIError(msg)

        try:
            return json.loads(response.content)
        except Exception as e:
            raise errors.OverlordAPIError('Error decoding response: ' + str(e))

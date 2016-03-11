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

from oslo_log import log
from oslo_service import loopingcall
import requests

from ironic_python_agent import encoding
from ironic_python_agent import errors


LOG = log.getLogger(__name__)


class APIClient(object):
    api_version = 'v1'
    payload_version = '2'

    def __init__(self, api_url, driver_name):
        self.api_url = api_url.rstrip('/')
        self.driver_name = driver_name

        # Only keep alive a maximum of 2 connections to the API. More will be
        # opened if they are needed, but they will be closed immediately after
        # use.
        adapter = requests.adapters.HTTPAdapter(pool_connections=2,
                                                pool_maxsize=2)
        self.session = requests.Session()
        self.session.mount(self.api_url, adapter)

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

        if response.status_code == requests.codes.CONFLICT:
            data = json.loads(response.content)
            raise errors.HeartbeatConflictError(data.get('faultstring'))
        elif response.status_code != requests.codes.ACCEPTED:
            msg = 'Invalid status code: {0}'.format(response.status_code)
            raise errors.HeartbeatError(msg)

    def lookup_node(self, hardware_info, timeout, starting_interval,
                    node_uuid=None):
        timer = loopingcall.BackOffLoopingCall(
            self._do_lookup,
            hardware_info=hardware_info,
            node_uuid=node_uuid)
        try:
            node_content = timer.start(starting_interval=starting_interval,
                                       timeout=timeout).wait()
        except loopingcall.LoopingCallTimeOut:
            raise errors.LookupNodeError('Could not look up node info. Check '
                                         'logs for details.')
        return node_content

    def _do_lookup(self, hardware_info, node_uuid):
        """The actual call to lookup a node.

        Should be called as a `loopingcall.BackOffLoopingCall`.
        """
        path = '/{api_version}/drivers/{driver}/vendor_passthru/lookup'.format(
            api_version=self.api_version,
            driver=self.driver_name
        )
        # This hardware won't be saved on the node currently, because of
        # how driver_vendor_passthru is implemented (no node saving).
        data = {
            'version': self.payload_version,
            'inventory': hardware_info
        }
        if node_uuid:
            data['node_uuid'] = node_uuid

        # Make the POST, make sure we get back normal data/status codes and
        # content
        try:
            response = self._request('POST', path, data=data)
        except Exception as e:
            LOG.warning('POST failed: %s' % str(e))
            return False

        if response.status_code != requests.codes.OK:
            LOG.warning('Invalid status code: %s' % response.status_code)
            return False

        try:
            content = json.loads(response.content)
        except Exception as e:
            LOG.warning('Error decoding response: %s' % str(e))
            return False

        # Check for valid response data
        if 'node' not in content or 'uuid' not in content['node']:
            LOG.warning('Got invalid node data from the API: %s' % content)
            return False

        if 'heartbeat_timeout' not in content:
            LOG.warning('Got invalid heartbeat from the API: %s' % content)
            return False

        # Got valid content
        raise loopingcall.LoopingCallDone(retvalue=content)

    def _get_agent_url(self, advertise_address):
        return 'http://{0}:{1}'.format(advertise_address[0],
                                       advertise_address[1])

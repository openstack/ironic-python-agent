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


from oslo_config import cfg
from oslo_log import log
from oslo_serialization import jsonutils
from oslo_service import loopingcall
import requests

from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent import netutils
from ironic_python_agent import utils


CONF = cfg.CONF
LOG = log.getLogger(__name__)


class APIClient(object):
    api_version = 'v1'
    lookup_api = '/%s/lookup' % api_version
    heartbeat_api = '/%s/heartbeat/{uuid}' % api_version
    ramdisk_api_headers = {'X-OpenStack-Ironic-API-Version': '1.22'}

    def __init__(self, api_url):
        self.api_url = api_url.rstrip('/')

        # Only keep alive a maximum of 2 connections to the API. More will be
        # opened if they are needed, but they will be closed immediately after
        # use.
        adapter = requests.adapters.HTTPAdapter(pool_connections=2,
                                                pool_maxsize=2)
        self.session = requests.Session()
        self.session.mount(self.api_url, adapter)

        self.encoder = encoding.RESTJSONEncoder()

    def _request(self, method, path, data=None, headers=None, **kwargs):
        request_url = '{api_url}{path}'.format(api_url=self.api_url, path=path)

        if data is not None:
            data = self.encoder.encode(data)

        headers = headers or {}
        headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

        verify, cert = utils.get_ssl_client_options(CONF)
        return self.session.request(method,
                                    request_url,
                                    headers=headers,
                                    data=data,
                                    verify=verify,
                                    cert=cert,
                                    **kwargs)

    def heartbeat(self, uuid, advertise_address):
        path = self.heartbeat_api.format(uuid=uuid)
        data = {'callback_url': self._get_agent_url(advertise_address)}
        try:
            response = self._request('POST', path, data=data,
                                     headers=self.ramdisk_api_headers)
        except Exception as e:
            raise errors.HeartbeatError(str(e))

        if response.status_code == requests.codes.CONFLICT:
            data = jsonutils.loads(response.content)
            raise errors.HeartbeatConflictError(data.get('faultstring'))
        elif response.status_code != requests.codes.ACCEPTED:
            msg = 'Invalid status code: {}'.format(response.status_code)
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
        params = {
            'addresses': ','.join(iface.mac_address
                                  for iface in hardware_info['interfaces']
                                  if iface.mac_address)
        }
        if node_uuid:
            params['node_uuid'] = node_uuid

        try:
            response = self._request('GET', self.lookup_api,
                                     headers=self.ramdisk_api_headers,
                                     params=params)
        except Exception:
            LOG.exception('Lookup failed')
            return False

        if response.status_code != requests.codes.OK:
            LOG.warning('Failure status code: %s', response.status_code)
            return False

        try:
            content = jsonutils.loads(response.content)
        except Exception as e:
            LOG.warning('Error decoding response: %s', e)
            return False

        # Check for valid response data
        if 'node' not in content or 'uuid' not in content['node']:
            LOG.warning('Got invalid node data from the API: %s', content)
            return False

        if 'config' not in content:
            # Old API
            try:
                content['config'] = {'heartbeat_timeout':
                                     content.pop('heartbeat_timeout')}
            except KeyError:
                LOG.warning('Got invalid heartbeat from the API: %s', content)
                return False

        # Got valid content
        raise loopingcall.LoopingCallDone(retvalue=content)

    def _get_agent_url(self, advertise_address):
        return 'http://{}:{}'.format(netutils.wrap_ipv6(advertise_address[0]),
                                     advertise_address[1])

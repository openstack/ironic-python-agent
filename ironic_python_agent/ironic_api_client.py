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
import requests
import tenacity

from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent import netutils
from ironic_python_agent import utils
from ironic_python_agent import version


CONF = cfg.CONF
LOG = log.getLogger(__name__)

# TODO(TheJulia): This should be increased at some point.
MIN_IRONIC_VERSION = (1, 31)
AGENT_VERSION_IRONIC_VERSION = (1, 36)
AGENT_TOKEN_IRONIC_VERSION = (1, 62)
AGENT_VERIFY_CA_IRONIC_VERSION = (1, 68)
# NOTE(dtantsur): change this constant every time you add support for more
# versions to ensure that we send the highest version we know about.
MAX_KNOWN_VERSION = AGENT_VERIFY_CA_IRONIC_VERSION


class APIClient(object):
    api_version = 'v1'
    lookup_api = '/%s/lookup' % api_version
    heartbeat_api = '/%s/heartbeat/{uuid}' % api_version
    _ironic_api_version = None
    agent_token = None

    def __init__(self, api_url):
        """
        Initialize the connection.

        Args:
            self: (todo): write your description
            api_url: (str): write your description
        """
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
        """
        Make an http request.

        Args:
            self: (todo): write your description
            method: (str): write your description
            path: (str): write your description
            data: (str): write your description
            headers: (dict): write your description
        """
        request_url = '{api_url}{path}'.format(api_url=self.api_url, path=path)

        if data is not None:
            data = self.encoder.encode(data)

        headers = headers or {}
        headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
        if CONF.global_request_id:
            headers["X-OpenStack-Request-ID"] = CONF.global_request_id

        verify, cert = utils.get_ssl_client_options(CONF)
        return self.session.request(method,
                                    request_url,
                                    headers=headers,
                                    data=data,
                                    verify=verify,
                                    cert=cert,
                                    **kwargs)

    def _get_ironic_api_version_header(self, version=None):
        """
        Return the api header.

        Args:
            self: (todo): write your description
            version: (str): write your description
        """
        if version is None:
            ironic_version = self._get_ironic_api_version()
            version = min(ironic_version, AGENT_TOKEN_IRONIC_VERSION)
        return {'X-OpenStack-Ironic-API-Version': '%d.%d' % version}

    def _get_ironic_api_version(self):
        """
        Get api version.

        Args:
            self: (todo): write your description
        """
        if self._ironic_api_version:
            return self._ironic_api_version

        if CONF.ironic_api_version is not None:
            try:
                version = CONF.ironic_api_version.split('.')
                self._ironic_api_version = (int(version[0]), int(version[1]))
                return self._ironic_api_version
            except Exception:
                LOG.exception("An error occurred while attempting to parse"
                              "the ironic_api_version. Will fall back to "
                              "auto-detection")

        try:
            response = self._request('GET', '/')
            data = jsonutils.loads(response.content)
            version = data['default_version']['version'].split('.')
            self._ironic_api_version = (int(version[0]), int(version[1]))
            return self._ironic_api_version
        except Exception:
            LOG.exception("An error occurred while attempting to discover "
                          "the available Ironic API versions, falling "
                          "back to using version %s",
                          ".".join(map(str, MIN_IRONIC_VERSION)))
            return MIN_IRONIC_VERSION

    def supports_auto_tls(self):
        """
        Returns true if auto - tls api version is on.

        Args:
            self: (todo): write your description
        """
        return self._get_ironic_api_version() >= AGENT_VERIFY_CA_IRONIC_VERSION

    def heartbeat(self, uuid, advertise_address, advertise_protocol='http',
                  generated_cert=None):
        """
        Sends a heartbeat.

        Args:
            self: (todo): write your description
            uuid: (str): write your description
            advertise_address: (bool): write your description
            advertise_protocol: (bool): write your description
            generated_cert: (todo): write your description
        """
        path = self.heartbeat_api.format(uuid=uuid)

        data = {'callback_url': self._get_agent_url(advertise_address,
                                                    advertise_protocol)}

        api_ver = self._get_ironic_api_version()

        if api_ver >= AGENT_TOKEN_IRONIC_VERSION:
            data['agent_token'] = self.agent_token

        if api_ver >= AGENT_VERSION_IRONIC_VERSION:
            data['agent_version'] = version.version_info.release_string()

        if api_ver >= AGENT_VERIFY_CA_IRONIC_VERSION and generated_cert:
            data['agent_verify_ca'] = generated_cert

        api_ver = min(MAX_KNOWN_VERSION, api_ver)
        headers = self._get_ironic_api_version_header(api_ver)

        LOG.debug('Heartbeat: announcing callback URL %s, API version is '
                  '%d.%d', data['callback_url'], *api_ver)
        try:
            response = self._request('POST', path, data=data, headers=headers)
        except requests.exceptions.ConnectionError as e:
            raise errors.HeartbeatConnectionError(str(e))
        except Exception as e:
            raise errors.HeartbeatError(str(e))

        if response.status_code == requests.codes.CONFLICT:
            data = jsonutils.loads(response.content)
            raise errors.HeartbeatConflictError(data.get('faultstring'))
        elif response.status_code != requests.codes.ACCEPTED:
            msg = 'Invalid status code: {}'.format(response.status_code)
            raise errors.HeartbeatError(msg)

    def lookup_node(self, hardware_info, timeout, starting_interval,
                    node_uuid=None, max_interval=30):
        """
        Look up a node.

        Args:
            self: (todo): write your description
            hardware_info: (bool): write your description
            timeout: (float): write your description
            starting_interval: (int): write your description
            node_uuid: (str): write your description
            max_interval: (int): write your description
        """
        retry = tenacity.retry(
            retry=tenacity.retry_if_result(lambda r: r is False),
            stop=tenacity.stop_after_delay(timeout),
            wait=tenacity.wait_random_exponential(min=starting_interval,
                                                  max=max_interval),
            reraise=True)
        try:
            return retry(self._do_lookup)(hardware_info=hardware_info,
                                          node_uuid=node_uuid)
        except tenacity.RetryError:
            raise errors.LookupNodeError('Could not look up node info. Check '
                                         'logs for details.')

    def _do_lookup(self, hardware_info, node_uuid):
        """The actual call to lookup a node."""
        params = {
            'addresses': ','.join(iface.mac_address
                                  for iface in hardware_info['interfaces']
                                  if iface.mac_address)
        }
        if node_uuid:
            params['node_uuid'] = node_uuid

        LOG.debug('Looking up node with addresses %r and UUID %s at %s',
                  params['addresses'], node_uuid, self.api_url)

        try:
            response = self._request(
                'GET', self.lookup_api,
                headers=self._get_ironic_api_version_header(),
                params=params)
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.HTTPError) as err:
            LOG.warning(
                'Error detected while attempting to perform lookup '
                'with %s, retrying. Error: %s', self.api_url, err
            )
            return False
        except Exception as err:
            # NOTE(TheJulia): If you're looking here, and you're wondering
            # why the retry logic is not working or your investigating a weird
            # error or even IPA just exiting,
            # See https://storyboard.openstack.org/#!/story/2007968
            # To be clear, we're going to try to provide as much detail as
            # possible in the exit handling
            msg = ('Unhandled error looking up node with addresses {} at '
                   '{}: {}'.format(params['addresses'], self.api_url, err))
            # No matter what we do at this point, IPA is going to exit.
            # This is because we don't know why the exception occured and
            # we likely should not try to retry as such.
            # We will attempt to provide as much detail to the logs as
            # possible as to what occured, although depending on the logging
            # subsystem, additional errors can occur, thus the additional
            # handling below.
            try:
                LOG.exception(msg)
                return False
            except Exception as exc_err:
                LOG.error(msg)
                exc_msg = ('Unexpected exception occured while trying to '
                           'log additional detail. Error: {}'.format(exc_err))
                LOG.error(exc_msg)
                raise errors.LookupNodeError(msg)

        if response.status_code != requests.codes.OK:
            LOG.warning(
                'Failed looking up node with addresses %r at %s, '
                'status code: %s. Check if inspection has completed.',
                params['addresses'], self.api_url, response.status_code,
            )
            return False

        try:
            content = jsonutils.loads(response.content)
        except Exception as e:
            LOG.warning('Error decoding response: %s', e)
            return False

        # Check for valid response data
        if 'node' not in content or 'uuid' not in content['node']:
            LOG.warning(
                'Got invalid node data in response to query for node '
                'with addresses %r from %s: %s',
                params['addresses'], self.api_url, content,
            )
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
        return content

    def _get_agent_url(self, advertise_address, advertise_protocol='http'):
        """
        Returns the url for an agent.

        Args:
            self: (todo): write your description
            advertise_address: (str): write your description
            advertise_protocol: (str): write your description
        """
        return '{}://{}:{}'.format(advertise_protocol,
                                   netutils.wrap_ipv6(advertise_address[0]),
                                   advertise_address[1])

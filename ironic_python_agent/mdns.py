#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Multicast DNS implementation for API discovery.

This implementation follows RFC 6763 as clarified by the API SIG guideline
https://review.opendev.org/651222.
"""

import ipaddress
import logging
import time

from oslo_config import cfg
from oslo_config import types as cfg_types
import zeroconf

from ironic_python_agent import errors
from ironic_python_agent import utils


opts = [
    cfg.IntOpt('lookup_attempts',
               min=1, default=3,
               help='Number of attempts to lookup a service.'),
    cfg.Opt('params',
            # This is required for values that contain commas.
            type=cfg_types.Dict(cfg_types.String(quotes=True)),
            default={},
            help='Additional parameters to pass for the registered '
                 'service.'),
    cfg.ListOpt('interfaces',
                help='List of IP addresses of interfaces to use for mDNS. '
                     'Defaults to all interfaces on the system.'),
]

CONF = cfg.CONF
opt_group = cfg.OptGroup(name='mdns', title='Options for multicast DNS client')
CONF.register_group(opt_group)
CONF.register_opts(opts, opt_group)

LOG = logging.getLogger(__name__)

_MDNS_DOMAIN = '_openstack._tcp.local.'


class Zeroconf(object):
    """Multicast DNS implementation client and server.

    Uses threading internally, so there is no start method. It starts
    automatically on creation.

    .. warning::
        The underlying library does not yet support IPv6.
    """

    def __init__(self):
        """Initialize and start the mDNS server."""
        interfaces = (CONF.mdns.interfaces if CONF.mdns.interfaces
                      else zeroconf.InterfaceChoice.All)
        # If interfaces are set, let zeroconf auto-detect the version
        ip_version = None if CONF.mdns.interfaces else zeroconf.IPVersion.All
        self._zc = zeroconf.Zeroconf(interfaces=interfaces,
                                     ip_version=ip_version)
        self._registered = []

    def get_endpoint(self, service_type, skip_loopback=True,
                     skip_link_local=False):
        """Get an endpoint and its properties from mDNS.

        If the requested endpoint is already in the built-in server cache, and
        its TTL is not exceeded, the cached value is returned.

        :param service_type: OpenStack service type.
        :param skip_loopback: Whether to ignore loopback addresses.
        :param skip_link_local: Whether to ignore link local V6 addresses.
        :returns: tuple (endpoint URL, properties as a dict).
        :raises: :exc:`.ServiceLookupFailure` if the service cannot be found.
        """
        delay = 0.1
        for attempt in range(CONF.mdns.lookup_attempts):
            name = '%s.%s' % (service_type, _MDNS_DOMAIN)
            info = self._zc.get_service_info(name, name)
            if info is not None:
                break
            elif attempt == CONF.mdns.lookup_attempts - 1:
                raise errors.ServiceLookupFailure(service=service_type)
            else:
                time.sleep(delay)
                delay *= 2

        all_addr = info.parsed_addresses()

        # Try to find the first routable address
        fallback = None
        for addr in all_addr:
            try:
                loopback = ipaddress.ip_address(addr).is_loopback
            except ValueError:
                LOG.debug('Skipping invalid IP address %s', addr)
                continue
            else:
                if loopback and skip_loopback:
                    LOG.debug('Skipping loopback IP address %s', addr)
                    continue

            if utils.get_route_source(addr, skip_link_local):
                address = addr
                break
            elif fallback is None:
                fallback = addr
        else:
            if fallback is None:
                raise errors.ServiceLookupFailure(
                    f'None of addresses {all_addr} for service %('
                    '{service_type} are valid')
            else:
                LOG.warning('None of addresses %s seem routable, '
                            'using %s', all_addr, fallback)
                address = fallback

        properties = {}
        for key, value in info.properties.items():
            try:
                if isinstance(key, bytes):
                    key = key.decode('utf-8')
            except UnicodeError as exc:
                raise errors.ServiceLookupFailure(
                    f'Invalid properties for service {service_type}. Cannot '
                    f'decode key {key!r}: {exc!r}')
            try:
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
            except UnicodeError as exc:
                LOG.debug('Cannot convert value %(value)r for key %(key)s '
                          'to string, assuming binary: %(exc)s',
                          {'key': key, 'value': value, 'exc': exc})

            properties[key] = value

        path = properties.pop('path', '')
        protocol = properties.pop('protocol', None)
        if not protocol:
            if info.port == 80:
                protocol = 'http'
            else:
                protocol = 'https'

        if info.server.endswith('.local.'):
            # Local hostname means that the catalog lists an IP address,
            # so use it
            host = address
            if int(ipaddress.ip_address(host).version) == 6:
                host = '[%s]' % host
        else:
            # Otherwise use the provided hostname.
            host = info.server.rstrip('.')

        return ('{proto}://{host}:{port}{path}'.format(proto=protocol,
                                                       host=host,
                                                       port=info.port,
                                                       path=path),
                properties)

    def close(self):
        """Shut down mDNS and unregister services.

        .. note::
            If another server is running for the same services, it will
            re-register them immediately.
        """
        for info in self._registered:
            try:
                self._zc.unregister_service(info)
            except Exception:
                LOG.exception('Cound not unregister mDNS service %s', info)
        self._zc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_endpoint(service_type):
    """Get an endpoint and its properties from mDNS.

    If the requested endpoint is already in the built-in server cache, and
    its TTL is not exceeded, the cached value is returned.

    :param service_type: OpenStack service type.
    :returns: tuple (endpoint URL, properties as a dict).
    :raises: :exc:`.ServiceLookupFailure` if the service cannot be found.
    """
    with Zeroconf() as zc:
        return zc.get_endpoint(service_type)


def list_opts():
    """Entry point for oslo-config-generator."""
    return [('mdns', opts)]

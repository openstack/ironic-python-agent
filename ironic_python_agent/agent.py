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

import collections
import os
import random
import select
import socket
import threading
import time

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
from oslo_utils import netutils
import pkg_resources
from six.moves.urllib import parse as urlparse
from stevedore import extension
from wsgiref import simple_server

from ironic_python_agent.api import app
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import inspector
from ironic_python_agent import ironic_api_client
from ironic_python_agent import utils

LOG = log.getLogger(__name__)

# Time(in seconds) to wait for any of the interfaces to be up
# before lookup of the node is attempted
NETWORK_WAIT_TIMEOUT = 60

# Time(in seconds) to wait before reattempt
NETWORK_WAIT_RETRY = 5

cfg.CONF.import_group('metrics', 'ironic_lib.metrics_utils')
cfg.CONF.import_group('metrics_statsd', 'ironic_lib.metrics_statsd')

Host = collections.namedtuple('Host', ['hostname', 'port'])


def _time():
    """Wraps time.time() for simpler testing."""
    return time.time()


class IronicPythonAgentStatus(encoding.Serializable):
    """Represents the status of an agent."""

    serializable_fields = ('started_at', 'version')

    def __init__(self, started_at, version):
        self.started_at = started_at
        self.version = version


class IronicPythonAgentHeartbeater(threading.Thread):
    """Thread that periodically heartbeats to Ironic."""

    # If we could wait at most N seconds between heartbeats (or in case of an
    # error) we will instead wait r x N seconds, where r is a random value
    # between these multipliers.
    min_jitter_multiplier = 0.3
    max_jitter_multiplier = 0.6

    # Exponential backoff values used in case of an error. In reality we will
    # only wait a portion of either of these delays based on the jitter
    # multipliers.
    initial_delay = 1.0
    max_delay = 300.0
    backoff_factor = 2.7

    def __init__(self, agent):
        """Initialize the heartbeat thread.

        :param agent: an :class:`ironic_python_agent.agent.IronicPythonAgent`
                      instance.
        """
        super(IronicPythonAgentHeartbeater, self).__init__()
        self.agent = agent
        self.api = agent.api_client
        self.error_delay = self.initial_delay
        self.reader = None
        self.writer = None

    def run(self):
        """Start the heartbeat thread."""
        # The first heartbeat happens immediately
        LOG.info('starting heartbeater')
        interval = 0
        self.agent.set_agent_advertise_addr()

        self.reader, self.writer = os.pipe()
        p = select.poll()
        p.register(self.reader, select.POLLIN)
        try:
            while True:
                if p.poll(interval * 1000):
                    if os.read(self.reader, 1) == 'a':
                        break

                self.do_heartbeat()
                interval_multiplier = random.uniform(
                    self.min_jitter_multiplier,
                    self.max_jitter_multiplier)
                interval = self.agent.heartbeat_timeout * interval_multiplier
                log_msg = 'sleeping before next heartbeat, interval: {}'
                LOG.info(log_msg.format(interval))
        finally:
            os.close(self.reader)
            os.close(self.writer)
            self.reader = None
            self.writer = None

    def do_heartbeat(self):
        """Send a heartbeat to Ironic."""
        try:
            self.api.heartbeat(
                uuid=self.agent.get_node_uuid(),
                advertise_address=self.agent.advertise_address
            )
            self.error_delay = self.initial_delay
            LOG.info('heartbeat successful')
        except errors.HeartbeatConflictError:
            LOG.warning('conflict error sending heartbeat')
            self.error_delay = min(self.error_delay * self.backoff_factor,
                                   self.max_delay)
        except Exception:
            LOG.exception('error sending heartbeat')
            self.error_delay = min(self.error_delay * self.backoff_factor,
                                   self.max_delay)

    def force_heartbeat(self):
        os.write(self.writer, 'b')

    def stop(self):
        """Stop the heartbeat thread."""
        if self.writer is not None:
            LOG.info('stopping heartbeater')
            os.write(self.writer, 'a')
            return self.join()


class IronicPythonAgent(base.ExecuteCommandMixin):
    """Class for base agent functionality."""

    def __init__(self, api_url, advertise_address, listen_address,
                 ip_lookup_attempts, ip_lookup_sleep, network_interface,
                 lookup_timeout, lookup_interval, standalone,
                 hardware_initialization_delay=0):
        super(IronicPythonAgent, self).__init__()
        if bool(cfg.CONF.keyfile) != bool(cfg.CONF.certfile):
            LOG.warning("Only one of 'keyfile' and 'certfile' options is "
                        "defined in config file. Its value will be ignored.")
        self.ext_mgr = extension.ExtensionManager(
            namespace='ironic_python_agent.extensions',
            invoke_on_load=True,
            propagate_map_exceptions=True,
            invoke_kwds={'agent': self},
        )
        self.api_url = api_url
        if self.api_url:
            self.api_client = ironic_api_client.APIClient(self.api_url)
            self.heartbeater = IronicPythonAgentHeartbeater(self)
        self.listen_address = listen_address
        self.advertise_address = advertise_address
        self.version = pkg_resources.get_distribution('ironic-python-agent')\
            .version
        self.api = app.VersionSelectorApplication(self)
        self.heartbeat_timeout = None
        self.started_at = None
        self.node = None
        # lookup timeout in seconds
        self.lookup_timeout = lookup_timeout
        self.lookup_interval = lookup_interval
        self.ip_lookup_attempts = ip_lookup_attempts
        self.ip_lookup_sleep = ip_lookup_sleep
        self.network_interface = network_interface
        self.standalone = standalone
        self.hardware_initialization_delay = hardware_initialization_delay

    def get_status(self):
        """Retrieve a serializable status.

        :returns: a :class:`ironic_python_agent.agent.IronicPythonAgent`
                  instance describing the agent's status.
        """
        return IronicPythonAgentStatus(
            started_at=self.started_at,
            version=self.version
        )

    def _get_route_source(self, dest):
        """Get the IP address to send packages to destination."""
        try:
            out, _err = utils.execute('ip', 'route', 'get', dest)
        except (EnvironmentError, processutils.ProcessExecutionError) as e:
            LOG.warning('Cannot get route to host %(dest)s: %(err)s',
                        {'dest': dest, 'err': e})
            return

        try:
            return out.strip().split('\n')[0].split('src')[1].split()[0]
        except IndexError:
            LOG.warning('No route to host %(dest)s, route record: %(rec)s',
                        {'dest': dest, 'rec': out})

    def set_agent_advertise_addr(self):
        """Set advertised IP address for the agent, if not already set.

        If agent's advertised IP address is still default (None), try to
        find a better one.  If the agent's network interface is None, replace
        that as well.

        :raises: LookupAgentIPError if an IP address could not be found
        """
        if self.advertise_address.hostname is not None:
            return

        found_ip = None
        if self.network_interface is not None:
            # TODO(dtantsur): deprecate this
            found_ip = hardware.dispatch_to_managers('get_ipv4_addr',
                                                     self.network_interface)
        else:
            url = urlparse.urlparse(self.api_url)
            ironic_host = url.hostname
            # Try resolving it in case it's not an IP address
            try:
                ironic_host = socket.gethostbyname(ironic_host)
            except socket.gaierror:
                LOG.debug('Count not resolve %s, maybe no DNS', ironic_host)

            for attempt in range(self.ip_lookup_attempts):
                found_ip = self._get_route_source(ironic_host)
                if found_ip:
                    break

                time.sleep(self.ip_lookup_sleep)

        if found_ip:
            self.advertise_address = Host(hostname=found_ip,
                                          port=self.advertise_address.port)
        else:
            raise errors.LookupAgentIPError('Agent could not find a valid IP '
                                            'address.')

    def get_node_uuid(self):
        """Get UUID for Ironic node.

        If the agent has not yet heartbeated to Ironic, it will not have
        the UUID and this will raise an exception.

        :returns: A string containing the UUID for the Ironic node.
        :raises: UnknownNodeError if UUID is unknown.
        """
        if self.node is None or 'uuid' not in self.node:
            raise errors.UnknownNodeError()
        return self.node['uuid']

    def list_command_results(self):
        """Get a list of command results.

        :returns: list of :class:`ironic_python_agent.extensions.base.
                  BaseCommandResult` objects.
        """
        return list(self.command_results.values())

    def get_command_result(self, result_id):
        """Get a specific command result by ID.

        :returns: a :class:`ironic_python_agent.extensions.base.
                  BaseCommandResult` object.
        :raises: RequestedObjectNotFoundError if command with the given ID
                 is not found.
        """
        try:
            return self.command_results[result_id]
        except KeyError:
            raise errors.RequestedObjectNotFoundError('Command Result',
                                                      result_id)

    def force_heartbeat(self):
        if not self.standalone:
            self.heartbeater.force_heartbeat()

    def _wait_for_interface(self):
        """Wait until at least one interface is up."""

        wait_till = time.time() + NETWORK_WAIT_TIMEOUT
        while time.time() < wait_till:
            interfaces = hardware.dispatch_to_managers(
                'list_network_interfaces')
            if not any(ifc.mac_address for ifc in interfaces):
                LOG.debug('Network is not up yet. '
                          'No valid interfaces found, retrying ...')
                time.sleep(NETWORK_WAIT_RETRY)
            else:
                break

        else:
            LOG.warning("No valid network interfaces found. "
                        "Node lookup will probably fail.")

    def run(self):
        """Run the Ironic Python Agent."""
        # Get the UUID so we can heartbeat to Ironic. Raises LookupNodeError
        # if there is an issue (uncaught, restart agent)
        self.started_at = _time()

        # Cached hw managers at runtime, not load time. See bug 1490008.
        hardware.load_managers()
        # Operator-settable delay before hardware actually comes up.
        # Helps with slow RAID drivers - see bug 1582797.
        if self.hardware_initialization_delay > 0:
            LOG.info('Waiting %d seconds before proceeding',
                     self.hardware_initialization_delay)
            time.sleep(self.hardware_initialization_delay)

        if not self.standalone:
            # Inspection should be started before call to lookup, otherwise
            # lookup will fail due to unknown MAC.
            uuid = None
            if cfg.CONF.inspection_callback_url:
                uuid = inspector.inspect()

            if self.api_url:
                self._wait_for_interface()
                content = self.api_client.lookup_node(
                    hardware_info=hardware.dispatch_to_managers(
                        'list_hardware_info'),
                    timeout=self.lookup_timeout,
                    starting_interval=self.lookup_interval,
                    node_uuid=uuid)

                LOG.debug('Received lookup results: %s', content)
                self.node = content['node']
                LOG.info('Lookup succeeded, node UUID is %s',
                         self.node['uuid'])
                hardware.cache_node(self.node)
                self.heartbeat_timeout = content['config']['heartbeat_timeout']

                # Update config with values from Ironic
                config = content.get('config', {})
                if config.get('metrics'):
                    for opt, val in config.items():
                        setattr(cfg.CONF.metrics, opt, val)
                if config.get('metrics_statsd'):
                    for opt, val in config.items():
                        setattr(cfg.CONF.metrics_statsd, opt, val)
            elif cfg.CONF.inspection_callback_url:
                LOG.info('No ipa-api-url configured, Heartbeat and lookup '
                         'skipped for inspector.')
            else:
                LOG.error('Neither ipa-api-url nor inspection_callback_url'
                          'found, please check your pxe append parameters.')

        if netutils.is_ipv6_enabled():
            # Listens to both IP versions, assuming IPV6_V6ONLY isn't enabled,
            # (the default behaviour in linux)
            simple_server.WSGIServer.address_family = socket.AF_INET6
        wsgi = simple_server.make_server(
            self.listen_address.hostname,
            self.listen_address.port,
            self.api,
            server_class=simple_server.WSGIServer)

        if not self.standalone and self.api_url:
            # Don't start heartbeating until the server is listening
            self.heartbeater.start()

        try:
            wsgi.serve_forever()
        except BaseException:
            LOG.exception('shutting down')

        if not self.standalone and self.api_url:
            self.heartbeater.stop()

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
import ipaddress
import random
import socket
import threading
import time
from urllib import parse as urlparse

import eventlet
from ironic_lib import exception as lib_exc
from ironic_lib import mdns
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
import pkg_resources

from ironic_python_agent.api import app
from ironic_python_agent import config
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

    def __init__(self, agent):
        """Initialize the heartbeat thread.

        :param agent: an :class:`ironic_python_agent.agent.IronicPythonAgent`
                      instance.
        """
        super(IronicPythonAgentHeartbeater, self).__init__()
        self.agent = agent
        self.stop_event = threading.Event()
        self.api = agent.api_client
        self.interval = 0
        self.heartbeat_forced = False
        self.previous_heartbeat = 0

    def run(self):
        """Start the heartbeat thread."""
        # The first heartbeat happens immediately
        LOG.info('Starting heartbeater')
        self.agent.set_agent_advertise_addr()

        while not self.stop_event.wait(min(self.interval, 5)):
            if self._heartbeat_expected():
                self.do_heartbeat()
            eventlet.sleep(0)

    def _heartbeat_expected(self):
        # Normal heartbeating
        if _time() > self.previous_heartbeat + self.interval:
            return True

        # Forced heartbeating, but once in 5 seconds
        if (self.heartbeat_forced
                and _time() > self.previous_heartbeat + 5):
            return True

    def do_heartbeat(self):
        """Send a heartbeat to Ironic."""
        try:
            self.api.heartbeat(
                uuid=self.agent.get_node_uuid(),
                advertise_address=self.agent.advertise_address,
                advertise_protocol=self.agent.advertise_protocol,
                generated_cert=self.agent.generated_cert,
            )
            LOG.info('heartbeat successful')
            self.heartbeat_forced = False
            self.previous_heartbeat = _time()
        except errors.HeartbeatConflictError:
            LOG.warning('conflict error sending heartbeat to %s',
                        self.agent.api_url)
        except Exception:
            LOG.exception('error sending heartbeat to %s', self.agent.api_url)
        finally:
            interval_multiplier = random.uniform(self.min_jitter_multiplier,
                                                 self.max_jitter_multiplier)
            self.interval = self.agent.heartbeat_timeout * interval_multiplier
            LOG.info('sleeping before next heartbeat, interval: %s',
                     self.interval)

    def force_heartbeat(self):
        self.heartbeat_forced = True

    def stop(self):
        """Stop the heartbeat thread."""
        LOG.info('stopping heartbeater')
        self.stop_event.set()
        return self.join()


class IronicPythonAgent(base.ExecuteCommandMixin):
    """Class for base agent functionality."""

    def __init__(self, api_url, advertise_address, listen_address,
                 ip_lookup_attempts, ip_lookup_sleep, network_interface,
                 lookup_timeout, lookup_interval, standalone, agent_token,
                 hardware_initialization_delay=0, advertise_protocol='http'):
        super(IronicPythonAgent, self).__init__()
        if bool(cfg.CONF.keyfile) != bool(cfg.CONF.certfile):
            LOG.warning("Only one of 'keyfile' and 'certfile' options is "
                        "defined in config file. Its value will be ignored.")
        self.ext_mgr = base.init_ext_manager(self)
        self.api_url = api_url
        if (not self.api_url or self.api_url == 'mdns') and not standalone:
            try:
                self.api_url, params = mdns.get_endpoint('baremetal')
            except lib_exc.ServiceLookupFailure:
                if self.api_url:
                    # mDNS explicitly requested, report failure.
                    raise
                else:
                    # implicit fallback to mDNS, do not fail (maybe we're only
                    # running inspection).
                    LOG.warning('Could not get baremetal endpoint from mDNS, '
                                'will not heartbeat')
            else:
                config.override(params)

        if self.api_url:
            self.api_client = ironic_api_client.APIClient(self.api_url)
            self.heartbeater = IronicPythonAgentHeartbeater(self)
        self.listen_address = listen_address
        self.advertise_address = advertise_address
        self.advertise_protocol = advertise_protocol
        self.version = pkg_resources.get_distribution('ironic-python-agent')\
            .version
        self.api = app.Application(self, cfg.CONF)
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
        # IPA will stop serving requests and exit after this is set to False
        self.serve_api = True
        self.agent_token = agent_token
        # Allows this to be turned on by the conductor while running,
        # in the event of long running ramdisks where the conductor
        # got upgraded somewhere along the way.
        self.agent_token_required = cfg.CONF.agent_token_required
        self.generated_cert = None

    def get_status(self):
        """Retrieve a serializable status.

        :returns: a :class:`ironic_python_agent.agent.IronicPythonAgent`
                  instance describing the agent's status.
        """
        return IronicPythonAgentStatus(
            started_at=self.started_at,
            version=self.version
        )

    def validate_agent_token(self, token):
        # We did not get a token, i.e. None and
        # we've previously seen a token, which is
        # a mid-cluster upgrade case with long-running ramdisks.
        if (not token and self.agent_token
                and not self.agent_token_required):
            # TODO(TheJulia): Rip this out during or after the V cycle.
            LOG.warning('Agent token for requests are not required '
                        'by the conductor, yet we received a token. '
                        'Cluster may be mid-upgrade. Support to '
                        'not fail in this condition will be removed in '
                        'the Victoria development cycle.')
            # Tell the API everything is okay.
            return True

        return self.agent_token == token

    def _get_route_source(self, dest):
        """Get the IP address to send packages to destination."""
        try:
            out, _err = utils.execute('ip', 'route', 'get', dest)
        except (EnvironmentError, processutils.ProcessExecutionError) as e:
            LOG.warning('Cannot get route to host %(dest)s: %(err)s',
                        {'dest': dest, 'err': e})
            return

        try:
            source = out.strip().split('\n')[0].split('src')[1].split()[0]
        except IndexError:
            LOG.warning('No route to host %(dest)s, route record: %(rec)s',
                        {'dest': dest, 'rec': out})
            return

        try:
            if ipaddress.ip_address(source).is_link_local:
                LOG.info('Ignoring link-local source to %(dest)s: %(rec)s',
                         {'dest': dest, 'rec': out})
                return
        except ValueError as exc:
            LOG.warning('Invalid IP address %(addr)s returned as a route '
                        'to host %(dest)s: %(err)s',
                        {'dest': dest, 'addr': source, 'err': exc})

        return source

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

    def _start_auto_tls(self):
        # NOTE(dtantsur): if listen_tls is True, assume static TLS
        # configuration and don't auto-generate anything.
        if cfg.CONF.listen_tls or not cfg.CONF.enable_auto_tls:
            LOG.debug('Automated TLS is disabled')
            return None, None

        if not self.api_url or not self.api_client.supports_auto_tls():
            LOG.warning('Ironic does not support automated TLS')
            return None, None

        self.set_agent_advertise_addr()

        LOG.info('Generating TLS parameters automatically for IP %s',
                 self.advertise_address.hostname)
        tls_info = hardware.dispatch_to_managers(
            'generate_tls_certificate', self.advertise_address.hostname)
        self.generated_cert = tls_info.text
        self.advertise_protocol = 'https'
        return tls_info.path, tls_info.private_key_path

    def serve_ipa_api(self):
        """Serve the API until an extension terminates it."""
        cert_file, key_file = self._start_auto_tls()
        self.api.start(cert_file, key_file)
        if not self.standalone and self.api_url:
            # Don't start heartbeating until the server is listening
            self.heartbeater.start()
        try:
            while self.serve_api:
                eventlet.sleep(0.1)
        except KeyboardInterrupt:
            LOG.info('Caught keyboard interrupt, exiting')
        self.api.stop()

    def process_lookup_data(self, content):
        """Update agent configuration from lookup data."""

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
        if config.get('agent_token_required'):
            self.agent_token_required = True
        token = config.get('agent_token')
        if token:
            if len(token) >= 32:
                LOG.debug('Agent token recorded as designated by '
                          'the ironic installation.')
                self.agent_token = token
                # set with-in the API client.
                if not self.standalone:
                    self.api_client.agent_token = token
            elif token == '******':
                LOG.warning('The agent token has already been '
                            'retrieved. IPA may not operate as '
                            'intended and the deployment may fail '
                            'depending on settings in the ironic '
                            'deployment.')
                if not self.agent_token and self.agent_token_required:
                    LOG.error('Ironic is signaling that agent tokens '
                              'are required, however we do not have '
                              'a token on file. '
                              'This is likely **FATAL**.')
            else:
                LOG.info('An invalid token was received.')
        if self.agent_token and not self.standalone:
            # Explicitly set the token in our API client before
            # starting heartbeat operations.
            self.api_client.agent_token = self.agent_token

    def run(self):
        """Run the Ironic Python Agent."""
        LOG.info('Starting ironic-python-agent version: %s',
                 self.version)
        # Get the UUID so we can heartbeat to Ironic. Raises LookupNodeError
        # if there is an issue (uncaught, restart agent)
        self.started_at = _time()
        # Attempt to sync the software clock
        utils.sync_clock(ignore_errors=True)

        # Cached hw managers at runtime, not load time. See bug 1490008.
        hardware.get_managers()
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
            # We can't try to inspect or heartbeat until we have valid
            # interfaces to perform those actions over.
            self._wait_for_interface()

            if cfg.CONF.inspection_callback_url:
                try:
                    # Attempt inspection. This may fail, and previously
                    # an error would be logged.
                    uuid = inspector.inspect()
                except errors.InspectionError as e:
                    LOG.error('Failed to perform inspection: %s', e)

            if self.api_url:
                content = self.api_client.lookup_node(
                    hardware_info=hardware.list_hardware_info(use_cache=True),
                    timeout=self.lookup_timeout,
                    starting_interval=self.lookup_interval,
                    node_uuid=uuid)
                LOG.debug('Received lookup results: %s', content)
                self.process_lookup_data(content)
                # Save the API url in case we need it later.
                hardware.save_api_client(
                    self.api_client, self.lookup_timeout,
                    self.lookup_interval)

            elif cfg.CONF.inspection_callback_url:
                LOG.info('No ipa-api-url configured, Heartbeat and lookup '
                         'skipped for inspector.')
            else:
                # NOTE(TheJulia): Once communication flow capability is
                # able to be driven solely from the conductor, this is no
                # longer a major issue.
                LOG.error('Neither ipa-api-url nor inspection_callback_url'
                          'found, please check your pxe append parameters.')

        self.serve_ipa_api()

        if not self.standalone and self.api_url:
            self.heartbeater.stop()

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

import random
import threading
import time

import pkg_resources
import six
from stevedore import extension
from wsgiref import simple_server

from ironic_python_agent.api import app
from ironic_python_agent import base
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import ironic_api_client
from ironic_python_agent.openstack.common import log
from ironic_python_agent import utils


def _time():
    """Wraps time.time() for simpler testing."""
    return time.time()


class IronicPythonAgentStatus(encoding.Serializable):
    def __init__(self, started_at, version):
        self.started_at = started_at
        self.version = version

    def serialize(self):
        """Turn the status into a dict."""
        return utils.get_ordereddict([
            ('started_at', self.started_at),
            ('version', self.version),
        ])


class IronicPythonAgentHeartbeater(threading.Thread):
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
        super(IronicPythonAgentHeartbeater, self).__init__()
        self.agent = agent
        self.hardware = hardware.get_manager()
        self.api = ironic_api_client.APIClient(agent.api_url)
        self.log = log.getLogger(__name__)
        self.stop_event = threading.Event()
        self.error_delay = self.initial_delay

    def run(self):
        # The first heartbeat happens now
        self.log.info('starting heartbeater')
        interval = 0

        while not self.stop_event.wait(interval):
            self.do_heartbeat()
            interval_multiplier = random.uniform(self.min_jitter_multiplier,
                                                 self.max_jitter_multiplier)
            interval = self.agent.heartbeat_timeout * interval_multiplier
            log_msg = 'sleeping before next heartbeat, interval: {0}'
            self.log.info(log_msg.format(interval))

    def do_heartbeat(self):
        try:
            self.api.heartbeat(
                uuid=self.agent.get_node_uuid(),
                advertise_address=self.agent.advertise_address
            )
            self.error_delay = self.initial_delay
            self.log.info('heartbeat successful')
        except Exception:
            self.log.exception('error sending heartbeat')
            self.error_delay = min(self.error_delay * self.backoff_factor,
                                   self.max_delay)

    def stop(self):
        self.log.info('stopping heartbeater')
        self.stop_event.set()
        return self.join()


class IronicPythonAgent(object):
    def __init__(self, api_url, advertise_address, listen_address,
                 lookup_timeout, lookup_interval):
        self.api_url = api_url
        self.api_client = ironic_api_client.APIClient(self.api_url)
        self.listen_address = listen_address
        self.advertise_address = advertise_address
        self.version = pkg_resources.get_distribution('ironic-python-agent')\
            .version
        self.api = app.VersionSelectorApplication(self)
        self.command_results = utils.get_ordereddict()
        self.heartbeater = IronicPythonAgentHeartbeater(self)
        self.heartbeat_timeout = None
        self.hardware = hardware.get_manager()
        self.command_lock = threading.Lock()
        self.log = log.getLogger(__name__)
        self.started_at = None
        self.node = None
        self.ext_mgr = extension.ExtensionManager(
            namespace='ironic_python_agent.extensions',
            invoke_on_load=True,
            propagate_map_exceptions=True,
        )
        # lookup timeout in seconds
        self.lookup_timeout = lookup_timeout
        self.lookup_interval = lookup_interval

    def get_status(self):
        """Retrieve a serializable status."""
        return IronicPythonAgentStatus(
            started_at=self.started_at,
            version=self.version
        )

    def get_agent_mac_addr(self):
        return self.hardware.get_primary_mac_address()

    def get_node_uuid(self):
        if 'uuid' not in self.node:
            errors.HeartbeatError('Tried to heartbeat without node UUID.')
        return self.node['uuid']

    def list_command_results(self):
        return list(self.command_results.values())

    def get_command_result(self, result_id):
        try:
            return self.command_results[result_id]
        except KeyError:
            raise errors.RequestedObjectNotFoundError('Command Result',
                                                      result_id)

    def _split_command(self, command_name):
        command_parts = command_name.split('.', 1)
        if len(command_parts) != 2:
            raise errors.InvalidCommandError(
                'Command name must be of the form <extension>.<name>')

        return (command_parts[0], command_parts[1])

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        with self.command_lock:
            extension_part, command_part = self._split_command(command_name)

            if len(self.command_results) > 0:
                last_command = list(self.command_results.values())[-1]
                if not last_command.is_done():
                    raise errors.CommandExecutionError('agent is busy')

            try:
                ext = self.ext_mgr[extension_part].obj
                result = ext.execute(command_part, **kwargs)
            except KeyError:
                # Extension Not found
                raise errors.RequestedObjectNotFoundError('Extension',
                                                          extension_part)
            except errors.InvalidContentError as e:
                # Any command may raise a InvalidContentError which will be
                # returned to the caller directly.
                raise e
            except Exception as e:
                # Other errors are considered command execution errors, and are
                # recorded as an
                result = base.SyncCommandResult(command_name,
                                                kwargs,
                                                False,
                                                six.text_type(e))

            self.command_results[result.id] = result
            return result

    def run(self):
        """Run the Ironic Python Agent."""
        # Get the UUID so we can heartbeat to Ironic. Raises LookupNodeError
        # if there is an issue (uncaught, restart agent)
        self.started_at = _time()
        content = self.api_client.lookup_node(
                hardware_info=self.hardware.list_hardware_info(),
                timeout=self.lookup_timeout,
                starting_interval=self.lookup_interval)

        self.node = content['node']
        self.heartbeat_timeout = content['heartbeat_timeout']
        self.heartbeater.start()
        wsgi = simple_server.make_server(
            self.listen_address[0],
            self.listen_address[1],
            self.api,
            server_class=simple_server.WSGIServer)

        try:
            wsgi.serve_forever()
        except BaseException:
            self.log.exception('shutting down')

        self.heartbeater.stop()


def build_agent(api_url,
                advertise_host,
                advertise_port,
                listen_host,
                listen_port,
                lookup_timeout,
                lookup_interval):

    return IronicPythonAgent(api_url,
                             (advertise_host, advertise_port),
                             (listen_host, listen_port),
                             lookup_timeout,
                             lookup_interval)

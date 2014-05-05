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

import random
import threading
import time

import pkg_resources
from stevedore import extension
from wsgiref import simple_server

from ironic_python_agent.api import app
from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import ironic_api_client
from ironic_python_agent.openstack.common import log


def _time():
    """Wraps time.time() for simpler testing."""
    return time.time()


class IronicPythonAgentStatus(encoding.Serializable):
    serializable_fields = ('started_at', 'version')

    def __init__(self, started_at, version):
        self.started_at = started_at
        self.version = version


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
        self.api = ironic_api_client.APIClient(agent.api_url,
                                               agent.driver_name)
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


class IronicPythonAgent(base.ExecuteCommandMixin):
    def __init__(self, api_url, advertise_address, listen_address,
                 lookup_timeout, lookup_interval, driver_name):
        super(IronicPythonAgent, self).__init__()
        self.api_url = api_url
        self.driver_name = driver_name
        self.api_client = ironic_api_client.APIClient(self.api_url,
                                                      self.driver_name)
        self.listen_address = listen_address
        self.advertise_address = advertise_address
        self.version = pkg_resources.get_distribution('ironic-python-agent')\
            .version
        self.api = app.VersionSelectorApplication(self)
        self.heartbeater = IronicPythonAgentHeartbeater(self)
        self.heartbeat_timeout = None
        self.hardware = hardware.get_manager()
        self.log = log.getLogger(__name__)
        self.started_at = None
        self.node = None
        # lookup timeout in seconds
        self.lookup_timeout = lookup_timeout
        self.lookup_interval = lookup_interval

    def get_extension_manager(self):
        return extension.ExtensionManager(
            namespace='ironic_python_agent.extensions',
            invoke_on_load=True,
            propagate_map_exceptions=True,
        )

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

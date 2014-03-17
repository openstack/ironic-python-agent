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

import collections
import random
import threading
import time

import pkg_resources
from stevedore import driver
import structlog
from wsgiref import simple_server

from teeth_agent.api import app
from teeth_agent import base
from teeth_agent import encoding
from teeth_agent import errors
from teeth_agent import hardware
from teeth_agent import overlord_agent_api


class TeethAgentStatus(encoding.Serializable):
    def __init__(self, mode, started_at, version):
        self.mode = mode
        self.started_at = started_at
        self.version = version

    def serialize(self):
        """Turn the status into a dict."""
        return collections.OrderedDict([
            ('mode', self.mode),
            ('started_at', self.started_at),
            ('version', self.version),
        ])


class TeethAgentHeartbeater(threading.Thread):
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
        super(TeethAgentHeartbeater, self).__init__()
        self.agent = agent
        self.hardware = hardware.get_manager()
        self.api = overlord_agent_api.APIClient(agent.api_url)
        self.log = structlog.get_logger(api_url=agent.api_url)
        self.stop_event = threading.Event()
        self.error_delay = self.initial_delay

    def run(self):
        # The first heartbeat happens now
        self.log.info('starting heartbeater')
        interval = 0

        while not self.stop_event.wait(interval):
            next_heartbeat_by = self.do_heartbeat()
            interval_multiplier = random.uniform(self.min_jitter_multiplier,
                                                 self.max_jitter_multiplier)
            interval = (next_heartbeat_by - time.time()) * interval_multiplier
            self.log.info('sleeping before next heartbeat', interval=interval)

    def do_heartbeat(self):
        try:
            deadline = self.api.heartbeat(
                hardware_info=self.hardware.list_hardware_info(),
                version=self.agent.version,
                mode=self.agent.get_mode_name())
            self.error_delay = self.initial_delay
            self.log.info('heartbeat successful')
        except Exception as e:
            self.log.error('error sending heartbeat', exception=e)
            deadline = time.time() + self.error_delay
            self.error_delay = min(self.error_delay * self.backoff_factor,
                                   self.max_delay)
            pass

        return deadline

    def stop(self):
        self.log.info('stopping heartbeater')
        self.stop_event.set()
        return self.join()


class TeethAgent(object):
    def __init__(self, api_url, listen_address, ipaddr):
        self.api_url = api_url
        self.listen_address = listen_address
        self.ipaddr = ipaddr
        self.mode_implementation = None
        self.version = pkg_resources.get_distribution('teeth-agent').version
        self.api = app.VersionSelectorApplication(self)
        self.command_results = collections.OrderedDict()
        self.heartbeater = TeethAgentHeartbeater(self)
        self.hardware = hardware.get_manager()
        self.command_lock = threading.Lock()
        self.log = structlog.get_logger()
        self.started_at = None

    def get_mode_name(self):
        if self.mode_implementation:
            return self.mode_implementation.name
        else:
            return 'NONE'

    def get_status(self):
        """Retrieve a serializable status."""
        return TeethAgentStatus(
            mode=self.get_mode_name(),
            started_at=self.started_at,
            version=self.version
        )

    def get_agent_mac_addr(self):
        return self.hardware.get_primary_mac_address()

    def list_command_results(self):
        return self.command_results.values()

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
                'Command name must be of the form <mode>.<name>')

        return (command_parts[0], command_parts[1])

    def _verify_mode(self, mode_name, command_name):
        if not self.mode_implementation:
            try:
                self.mode_implementation = _load_mode_implementation(mode_name)
            except Exception:
                raise errors.InvalidCommandError(
                    'Unknown mode: {}'.format(mode_name))
        elif self.get_mode_name().lower() != mode_name:
            raise errors.InvalidCommandError(
                'Agent is already in {} mode'.format(self.get_mode_name()))

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        with self.command_lock:
            mode_part, command_part = self._split_command(command_name)
            self._verify_mode(mode_part, command_part)

            if len(self.command_results) > 0:
                last_command = self.command_results.values()[-1]
                if not last_command.is_done():
                    raise errors.CommandExecutionError('agent is busy')

            try:
                result = self.mode_implementation.execute(command_part,
                                                          **kwargs)
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
                                                unicode(e))

            self.command_results[result.id] = result
            return result

    def run(self):
        """Run the Teeth Agent."""
        self.started_at = time.time()
        self.heartbeater.start()
        wsgi = simple_server.make_server(
            self.listen_address[0],
            self.listen_address[1],
            self.api,
            server_class=simple_server.WSGIServer)

        try:
            wsgi.serve_forever()
        except BaseException as e:
            self.log.error('shutting down', exception=e)

        self.heartbeater.stop()


def _load_mode_implementation(mode_name):
    mgr = driver.DriverManager(
        namespace='teeth_agent.modes',
        name=mode_name.lower(),
        invoke_on_load=True,
        invoke_args=[],
    )
    return mgr.driver


def build_agent(api_url, listen_host, listen_port, ipaddr):
    return TeethAgent(api_url, (listen_host, listen_port), ipaddr)

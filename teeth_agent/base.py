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

import abc
import collections
import random
import threading
import time
import uuid

from cherrypy import wsgiserver
import pkg_resources
import structlog
from teeth_rest import encoding
from teeth_rest import errors as rest_errors

from teeth_agent import api
from teeth_agent import errors
from teeth_agent import hardware
from teeth_agent import overlord_agent_api


class TeethAgentStatus(encoding.Serializable):
    def __init__(self, mode, started_at, version):
        self.mode = mode
        self.started_at = started_at
        self.version = version

    def serialize(self, view):
        """Turn the status into a dict."""
        return collections.OrderedDict([
            ('mode', self.mode),
            ('started_at', self.started_at),
            ('version', self.version),
        ])


class AgentCommandStatus(object):
    RUNNING = 'RUNNING'
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'


class BaseCommandResult(encoding.Serializable):
    def __init__(self, command_name, command_params):
        self.id = str(uuid.uuid4())
        self.command_name = command_name
        self.command_params = command_params
        self.command_status = AgentCommandStatus.RUNNING
        self.command_error = None
        self.command_result = None

    def serialize(self, view):
        return collections.OrderedDict([
            ('id', self.id),
            ('command_name', self.command_name),
            ('command_params', self.command_params),
            ('command_status', self.command_status),
            ('command_error', self.command_error),
            ('command_result', self.command_result),
        ])

    def is_done(self):
        return self.command_status != AgentCommandStatus.RUNNING

    def join(self):
        return self


class SyncCommandResult(BaseCommandResult):
    def __init__(self, command_name, command_params, success, result_or_error):
        super(SyncCommandResult, self).__init__(command_name,
                                                command_params)
        if success:
            self.command_status = AgentCommandStatus.SUCCEEDED
            self.command_result = result_or_error
        else:
            self.command_status = AgentCommandStatus.FAILED
            self.command_error = result_or_error


class AsyncCommandResult(BaseCommandResult):
    """A command that executes asynchronously in the background. Subclasses
    should override `execute` to implement actual command execution.
    """
    def __init__(self, command_name, command_params):
        super(AsyncCommandResult, self).__init__(command_name, command_params)
        self.command_state_lock = threading.Lock()

        thread_name = 'agent-command-{}'.format(self.id)
        self.execution_thread = threading.Thread(target=self.run,
                                                 name=thread_name)

    def serialize(self, view):
        with self.command_state_lock:
            return super(AsyncCommandResult, self).serialize(view)

    def start(self):
        self.execution_thread.start()
        return self

    def join(self):
        self.execution_thread.join()
        return self

    def is_done(self):
        with self.command_state_lock:
            return super(AsyncCommandResult, self).is_done()

    def run(self):
        try:
            result = self.execute()
            with self.command_state_lock:
                self.command_result = result
                self.command_status = AgentCommandStatus.SUCCEEDED

        except Exception as e:
            if not isinstance(e, rest_errors.RESTError):
                e = errors.CommandExecutionError(str(e))

            with self.command_state_lock:
                self.command_error = e
                self.command_status = AgentCommandStatus.FAILED

    @abc.abstractmethod
    def execute(self):
        pass


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
                mac_addr=self.agent.get_agent_mac_addr(),
                url=self.agent.get_agent_url(),
                version=self.agent.version,
                mode=self.agent.mode)
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


class BaseTeethAgent(object):
    def __init__(self, listen_host, listen_port, api_url, mode):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.api_url = api_url
        self.started_at = None
        self.mode = mode
        self.version = pkg_resources.get_distribution('teeth-agent').version
        self.api = api.TeethAgentAPIServer(self)
        self.command_results = collections.OrderedDict()
        self.command_map = {}
        self.heartbeater = TeethAgentHeartbeater(self)
        self.hardware = hardware.HardwareInspector()
        self.command_lock = threading.Lock()

    def get_status(self):
        """Retrieve a serializable status."""
        return TeethAgentStatus(
            mode=self.mode,
            started_at=self.started_at,
            version=self.version
        )

    def get_agent_url(self):
        # If we put this behind any sort of proxy (ie, stunnel) we're going to
        # need to (re)think this.
        return 'http://{host}:{port}/'.format(host=self.listen_host,
                                              port=self.listen_port)

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

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        with self.command_lock:
            if len(self.command_results) > 0:
                last_command = self.command_results.values()[-1]
                if not last_command.is_done():
                    raise errors.CommandExecutionError('agent is busy')

            if command_name not in self.command_map:
                raise errors.InvalidCommandError(command_name)

            try:
                result = self.command_map[command_name](command_name, **kwargs)
                if not isinstance(result, BaseCommandResult):
                    result = SyncCommandResult(command_name,
                                               kwargs,
                                               True,
                                               result)
            except rest_errors.InvalidContentError as e:
                # Any command may raise a InvalidContentError which will be
                # returned to the caller directly.
                raise e
            except Exception as e:
                # Other errors are considered command execution errors, and are
                # recorded as an
                result = SyncCommandResult(command_name, kwargs, False, e)

            self.command_results[result.id] = result
            return result

    def run(self):
        """Run the Teeth Agent."""
        if self.started_at:
            raise RuntimeError('Agent was already started')

        self.started_at = time.time()
        self.heartbeater.start()

        listen_address = (self.listen_host, self.listen_port)
        server = wsgiserver.CherryPyWSGIServer(listen_address, self.api)

        try:
            server.start()
        except BaseException:
            server.stop()

        self.heartbeater.stop()

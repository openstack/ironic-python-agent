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
import threading
import time
import uuid

import pkg_resources
from teeth_rest import encoding
from teeth_rest import errors as rest_errors
from werkzeug import serving

from teeth_agent import api
from teeth_agent import errors


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
        return self.execution_thread.start()

    def join(self):
        return self.execution_thread.join()

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


class BaseTeethAgent(object):
    def __init__(self, listen_host, listen_port, api_url, mode):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.api_url = api_url
        self.started_at = None
        self.mode = mode
        self.version = pkg_resources.get_distribution('teeth-agent').version
        self.api = api.TeethAgentAPIServer(self)
        self.command_results = {}
        self.command_map = {}

    def get_status(self):
        """Retrieve a serializable status."""
        return TeethAgentStatus(
            mode=self.mode,
            started_at=self.started_at,
            version=self.version
        )

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        if command_name not in self.command_map:
            raise errors.InvalidCommandError(command_name)

        try:
            result = self.command_map[command_name](command_name, **kwargs)
            if not isinstance(result, BaseCommandResult):
                result = SyncCommandResult(command_name, kwargs, True, result)
        except rest_errors.ValidationError as e:
            # Any command may raise a ValidationError which will be returned
            # to the caller directly.
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
        serving.run_simple(self.listen_host, self.listen_port, self.api)

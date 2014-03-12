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

import threading
import uuid

import structlog
from teeth_rest import encoding
from teeth_rest import errors as rest_errors

from teeth_agent import errors


class AgentCommandStatus(object):
    RUNNING = u'RUNNING'
    SUCCEEDED = u'SUCCEEDED'
    FAILED = u'FAILED'


class BaseCommandResult(encoding.Serializable):
    def __init__(self, command_name, command_params):
        self.id = unicode(uuid.uuid4())
        self.command_name = command_name
        self.command_params = command_params
        self.command_status = AgentCommandStatus.RUNNING
        self.command_error = None
        self.command_result = None

    def serialize(self, view):
        return dict((
            (u'id', self.id),
            (u'command_name', self.command_name),
            (u'command_params', self.command_params),
            (u'command_status', self.command_status),
            (u'command_error', self.command_error),
            (u'command_result', self.command_result),
        ))

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
    """A command that executes asynchronously in the background.

    :param execute_method: a callable to be executed asynchronously
    """
    def __init__(self, command_name, command_params, execute_method):
        super(AsyncCommandResult, self).__init__(command_name, command_params)
        self.execute_method = execute_method
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
            result = self.execute_method(self.command_name,
                                         **self.command_params)
            with self.command_state_lock:
                self.command_result = result
                self.command_status = AgentCommandStatus.SUCCEEDED

        except Exception as e:
            if not isinstance(e, rest_errors.RESTError):
                e = errors.CommandExecutionError(str(e))

            with self.command_state_lock:
                self.command_error = e
                self.command_status = AgentCommandStatus.FAILED


class BaseAgentMode(object):
    def __init__(self, name):
        super(BaseAgentMode, self).__init__()
        self.log = structlog.get_logger(agent_mode=name)
        self.name = name
        self.command_map = {}

    def execute(self, command_name, **kwargs):
        if command_name not in self.command_map:
            raise errors.InvalidCommandError(
                'Unknown command: {}'.format(command_name))

        result = self.command_map[command_name](command_name, **kwargs)

        # In order to enable extremely succinct synchronous commands, we allow
        # them to return a value directly, and we'll handle wrapping it up in a
        # SyncCommandResult
        if not isinstance(result, BaseCommandResult):
            result = SyncCommandResult(command_name, kwargs, True, result)

        return result

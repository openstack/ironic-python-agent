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

import functools
import threading
import uuid

import six

from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent.openstack.common import log
from ironic_python_agent import utils


class AgentCommandStatus(object):
    RUNNING = u'RUNNING'
    SUCCEEDED = u'SUCCEEDED'
    FAILED = u'FAILED'


class BaseCommandResult(encoding.Serializable):
    def __init__(self, command_name, command_params):
        self.id = six.text_type(uuid.uuid4())
        self.command_name = command_name
        self.command_params = command_params
        self.command_status = AgentCommandStatus.RUNNING
        self.command_error = None
        self.command_result = None

    def serialize(self):
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

        thread_name = 'agent-command-{0}'.format(self.id)
        self.execution_thread = threading.Thread(target=self.run,
                                                 name=thread_name)

    def serialize(self):
        with self.command_state_lock:
            return super(AsyncCommandResult, self).serialize()

    def start(self):
        self.execution_thread.start()
        return self

    def join(self, timeout=None):
        self.execution_thread.join(timeout)
        return self

    def is_done(self):
        with self.command_state_lock:
            return super(AsyncCommandResult, self).is_done()

    def run(self):
        try:
            result = self.execute_method(**self.command_params)
            with self.command_state_lock:
                self.command_result = result
                self.command_status = AgentCommandStatus.SUCCEEDED

        except Exception as e:
            if not isinstance(e, errors.RESTError):
                e = errors.CommandExecutionError(str(e))

            with self.command_state_lock:
                self.command_error = e
                self.command_status = AgentCommandStatus.FAILED


class BaseAgentExtension(object):
    def __init__(self):
        super(BaseAgentExtension, self).__init__()
        self.log = log.getLogger(__name__)
        self.command_map = {}

    def execute(self, command_name, **kwargs):
        if command_name not in self.command_map:
            raise errors.InvalidCommandError(
                'Unknown command: {0}'.format(command_name))

        return self.command_map[command_name](command_name, **kwargs)

    def check_cmd_presence(self, ext_obj, ext, cmd):
        if not (hasattr(ext_obj, 'execute') and hasattr(ext_obj, 'command_map')
                and cmd in ext_obj.command_map):
            raise errors.InvalidCommandParamsError(
                "Extension {0} doesn't provide {1} method".format(ext, cmd))


class ExecuteCommandMixin(object):
    def __init__(self):
        self.command_lock = threading.Lock()
        self.command_results = utils.get_ordereddict()
        self.ext_mgr = self.get_extension_manager()

    def get_extension_manager(self):
        raise NotImplementedError(
            'get_extension_manager should be implemented in successor class')

    def split_command(self, command_name):
        command_parts = command_name.split('.', 1)
        if len(command_parts) != 2:
            raise errors.InvalidCommandError(
                'Command name must be of the form <extension>.<name>')

        return (command_parts[0], command_parts[1])

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        with self.command_lock:
            extension_part, command_part = self.split_command(command_name)

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
                result = SyncCommandResult(command_name,
                                           kwargs,
                                           False,
                                           six.text_type(e))

            self.command_results[result.id] = result
            return result


def async_command(validator=None):
    """Will run the command in an AsyncCommandResult in its own thread.
    command_name is set based on the func name and command_params will
    be whatever args/kwargs you pass into the decorated command.
    """
    def async_decorator(func):
        @functools.wraps(func)
        def wrapper(self, command_name, **command_params):
            # Run a validator before passing everything off to async.
            # validators should raise exceptions or return silently.
            if validator:
                validator(self, **command_params)

            # bind self to func so that AsyncCommandResult doesn't need to
            # know about the mode
            bound_func = functools.partial(func, self)

            return AsyncCommandResult(command_name,
                                      command_params,
                                      bound_func).start()
        return wrapper
    return async_decorator


def sync_command(validator=None):
    """Decorate a method in order to wrap up its return value in a
    SyncCommandResult. For consistency with @async_command() can also accept a
    validator which will be used to validate input, although a synchronous
    command can also choose to implement validation inline.
    """
    def sync_decorator(func):
        @functools.wraps(func)
        def wrapper(self, command_name, **command_params):
            # Run a validator before passing everything off to async.
            # validators should raise exceptions or return silently.
            if validator:
                validator(self, **command_params)

            result = func(self, **command_params)
            return SyncCommandResult(command_name,
                                     command_params,
                                     True,
                                     result)

        return wrapper
    return sync_decorator

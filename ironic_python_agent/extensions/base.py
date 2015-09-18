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
import functools
import inspect
import threading
import uuid

from oslo_log import log
import six

from ironic_python_agent import encoding
from ironic_python_agent import errors

LOG = log.getLogger()


class AgentCommandStatus(object):
    """Mapping of agent command statuses."""
    RUNNING = u'RUNNING'
    SUCCEEDED = u'SUCCEEDED'
    FAILED = u'FAILED'
    CLEAN_VERSION_MISMATCH = u'CLEAN_VERSION_MISMATCH'


class BaseCommandResult(encoding.SerializableComparable):
    """Base class for command result."""

    serializable_fields = ('id', 'command_name', 'command_params',
                           'command_status', 'command_error', 'command_result')

    def __init__(self, command_name, command_params):
        """Construct an instance of BaseCommandResult.

        :param command_name: name of command executed
        :param command_params: parameters passed to command
        """

        self.id = six.text_type(uuid.uuid4())
        self.command_name = command_name
        self.command_params = command_params
        self.command_status = AgentCommandStatus.RUNNING
        self.command_error = None
        self.command_result = None

    def is_done(self):
        """Checks to see if command is still RUNNING.

        :returns: True if command is done, False if still RUNNING
        """
        return self.command_status != AgentCommandStatus.RUNNING

    def join(self):
        """:returns: result of completed command."""
        return self


class SyncCommandResult(BaseCommandResult):
    """A result from a command that executes synchronously."""

    def __init__(self, command_name, command_params, success, result_or_error):
        """Construct an instance of SyncCommandResult.

        :param command_name: name of command executed
        :param command_params: parameters passed to command
        :param success: True indicates success, False indicates failure
        :param result_or_error: Contains the result (or error) from the command
        """

        super(SyncCommandResult, self).__init__(command_name,
                                                command_params)

        if isinstance(result_or_error, (bytes, six.text_type)):
            result_key = 'result' if success else 'error'
            result_or_error = {result_key: result_or_error}

        if success:
            self.command_status = AgentCommandStatus.SUCCEEDED
            self.command_result = result_or_error
        else:
            self.command_status = AgentCommandStatus.FAILED
            self.command_error = result_or_error


class AsyncCommandResult(BaseCommandResult):
    """A command that executes asynchronously in the background."""

    def __init__(self, command_name, command_params, execute_method,
                 agent=None):
        """Construct an instance of AsyncCommandResult.

        :param command_name: name of command to execute
        :param command_params: parameters passed to command
        :param execute_method: a callable to be executed asynchronously
        :param agent: Optional: an instance of IronicPythonAgent
        """
        super(AsyncCommandResult, self).__init__(command_name, command_params)
        self.agent = agent
        self.execute_method = execute_method
        self.command_state_lock = threading.Lock()

        thread_name = 'agent-command-{0}'.format(self.id)
        self.execution_thread = threading.Thread(target=self.run,
                                                 name=thread_name)

    def serialize(self):
        """Serializes the AsyncCommandResult into a dict.

        :returns: dict containing serializable fields in AsyncCommandResult
        """
        with self.command_state_lock:
            return super(AsyncCommandResult, self).serialize()

    def start(self):
        """Begin background execution of command."""
        self.execution_thread.start()
        return self

    def join(self, timeout=None):
        """Block until command has completed, and return result.

        :param timeout: float indicating max seconds to wait for command
                        to complete. Defaults to None.
        """
        self.execution_thread.join(timeout)
        return self

    def is_done(self):
        """Checks to see if command is still RUNNING.

        :returns: True if command is done, False if still RUNNING
        """
        with self.command_state_lock:
            return super(AsyncCommandResult, self).is_done()

    def run(self):
        """Run a command."""
        try:
            result = self.execute_method(**self.command_params)

            if isinstance(result, (bytes, six.text_type)):
                result = {'result': '{}: {}'.format(self.command_name, result)}
            LOG.info('Command: %(name)s, result: %(result)s',
                     {'name': self.command_name, 'result': result})
            with self.command_state_lock:
                self.command_result = result
                self.command_status = AgentCommandStatus.SUCCEEDED
        except errors.CleanVersionMismatch as e:
            with self.command_state_lock:
                self.command_error = e
                self.command_status = AgentCommandStatus.CLEAN_VERSION_MISMATCH
                self.command_result = None
            LOG.error('Clean version mismatch for command %s',
                      self.command_name)
        except Exception as e:
            LOG.exception('Command failed: %(name)s, error: %(err)s',
                          {'name': self.command_name, 'err': e})
            if not isinstance(e, errors.RESTError):
                e = errors.CommandExecutionError(str(e))

            with self.command_state_lock:
                self.command_error = e
                self.command_status = AgentCommandStatus.FAILED
        finally:
            if self.agent:
                self.agent.force_heartbeat()


class BaseAgentExtension(object):
    def __init__(self, agent=None):
        super(BaseAgentExtension, self).__init__()
        self.agent = agent
        self.log = log.getLogger(__name__)
        self.command_map = dict(
            (v.command_name, v)
            for k, v in inspect.getmembers(self)
            if hasattr(v, 'command_name')
        )

    def execute(self, command_name, **kwargs):
        cmd = self.command_map.get(command_name)
        if cmd is None:
            raise errors.InvalidCommandError(
                'Unknown command: {0}'.format(command_name))
        return cmd(**kwargs)

    def check_cmd_presence(self, ext_obj, ext, cmd):
        if not (hasattr(ext_obj, 'execute') and hasattr(ext_obj, 'command_map')
                and cmd in ext_obj.command_map):
            raise errors.InvalidCommandParamsError(
                "Extension {0} doesn't provide {1} method".format(ext, cmd))


class ExecuteCommandMixin(object):
    def __init__(self):
        self.command_lock = threading.Lock()
        self.command_results = collections.OrderedDict()
        self.ext_mgr = None

    def get_extension(self, extension_name):
        if self.ext_mgr is None:
            raise errors.ExtensionError('Extension manager is not initialized')
        ext = self.ext_mgr[extension_name].obj
        ext.ext_mgr = self.ext_mgr
        return ext

    def split_command(self, command_name):
        command_parts = command_name.split('.', 1)
        if len(command_parts) != 2:
            raise errors.InvalidCommandError(
                'Command name must be of the form <extension>.<name>')

        return (command_parts[0], command_parts[1])

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        with self.command_lock:
            LOG.debug('Executing command: %(name)s with args: %(args)s',
                      {'name': command_name, 'args': kwargs})
            extension_part, command_part = self.split_command(command_name)

            if len(self.command_results) > 0:
                last_command = list(self.command_results.values())[-1]
                if not last_command.is_done():
                    LOG.error('Tried to execute %(command)s, agent is still '
                              'executing %(last)s', {'command': command_name,
                                                     'last': last_command})
                    raise errors.CommandExecutionError('agent is busy')

            try:
                ext = self.get_extension(extension_part)
                result = ext.execute(command_part, **kwargs)
            except KeyError:
                # Extension Not found
                LOG.exception('Extension %s not found', extension_part)
                raise errors.RequestedObjectNotFoundError('Extension',
                                                          extension_part)
            except errors.InvalidContentError as e:
                # Any command may raise a InvalidContentError which will be
                # returned to the caller directly.
                LOG.exception('Invalid content error: %s', e)
                raise e
            except Exception as e:
                # Other errors are considered command execution errors, and are
                # recorded as a failed SyncCommandResult with an error message
                LOG.exception('Command execution error: %s', e)
                result = SyncCommandResult(command_name, kwargs, False, e)
            LOG.info('Command %(name)s completed: %(result)s',
                     {'name': command_name, 'result': result})
            self.command_results[result.id] = result
            return result


def async_command(command_name, validator=None):
    """Will run the command in an AsyncCommandResult in its own thread.

    command_name is set based on the func name and command_params will
    be whatever args/kwargs you pass into the decorated command.
    Return values of type `str` or `unicode` are prefixed with the
    `command_name` parameter when returned for consistency.
    """
    def async_decorator(func):
        func.command_name = command_name

        @functools.wraps(func)
        def wrapper(self, **command_params):
            # Run a validator before passing everything off to async.
            # validators should raise exceptions or return silently.
            if validator:
                validator(self, **command_params)

            # bind self to func so that AsyncCommandResult doesn't need to
            # know about the mode
            bound_func = functools.partial(func, self)

            return AsyncCommandResult(command_name,
                                      command_params,
                                      bound_func,
                                      agent=self.agent).start()
        return wrapper
    return async_decorator


def sync_command(command_name, validator=None):
    """Decorate a method to wrap its return value in a SyncCommandResult.

    For consistency with @async_command() can also accept a
    validator which will be used to validate input, although a synchronous
    command can also choose to implement validation inline.
    """
    def sync_decorator(func):
        func.command_name = command_name

        @functools.wraps(func)
        def wrapper(self, **command_params):
            # Run a validator before invoking the function.
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

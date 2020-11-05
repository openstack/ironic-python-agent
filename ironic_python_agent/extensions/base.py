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

from oslo_log import log
from oslo_utils import uuidutils
from stevedore import extension

from ironic_python_agent import encoding
from ironic_python_agent import errors
from ironic_python_agent import utils


LOG = log.getLogger()


class AgentCommandStatus(object):
    """Mapping of agent command statuses."""
    RUNNING = u'RUNNING'
    SUCCEEDED = u'SUCCEEDED'
    FAILED = u'FAILED'
    # TODO(dtantsur): keeping the same text for backward compatibility, change
    # to just VERSION_MISMATCH one release after ironic is updated.
    VERSION_MISMATCH = u'CLEAN_VERSION_MISMATCH'


class BaseCommandResult(encoding.SerializableComparable):
    """Base class for command result."""

    serializable_fields = ('id', 'command_name', 'command_params',
                           'command_status', 'command_error', 'command_result')

    def __init__(self, command_name, command_params):
        """Construct an instance of BaseCommandResult.

        :param command_name: name of command executed
        :param command_params: parameters passed to command
        """

        self.id = uuidutils.generate_uuid()
        self.command_name = command_name
        self.command_params = command_params
        self.command_status = AgentCommandStatus.RUNNING
        self.command_error = None
        self.command_result = None

    def __str__(self):
        """
        Returns a string representation of the device.

        Args:
            self: (todo): write your description
        """
        return ("Command name: %(name)s, "
                "params: %(params)s, status: %(status)s, result: "
                "%(result)s." %
                {"name": self.command_name,
                 "params": utils.remove_large_keys(self.command_params),
                 "status": self.command_status,
                 "result": utils.remove_large_keys(self.command_result)})

    def is_done(self):
        """Checks to see if command is still RUNNING.

        :returns: True if command is done, False if still RUNNING
        """
        return self.command_status != AgentCommandStatus.RUNNING

    def join(self):
        """:returns: result of completed command."""
        return self

    def wait(self):
        """Join the result and extract its value.

        Raises if the command failed.
        """
        self.join()
        if self.command_error is not None:
            raise self.command_error
        else:
            return self.command_result


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
        if isinstance(result_or_error, (bytes, str)):
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

        thread_name = 'agent-command-{}'.format(self.id)
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

            if isinstance(result, (bytes, str)):
                result = {'result': '{}: {}'.format(self.command_name, result)}
            LOG.info('Asynchronous command %(name)s completed: %(result)s',
                     {'name': self.command_name,
                      'result': utils.remove_large_keys(result)})
            with self.command_state_lock:
                self.command_result = result
                self.command_status = AgentCommandStatus.SUCCEEDED
        except errors.VersionMismatch as e:
            with self.command_state_lock:
                self.command_error = e
                self.command_status = AgentCommandStatus.VERSION_MISMATCH
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
        """
        Initialize the agent.

        Args:
            self: (todo): write your description
            agent: (str): write your description
        """
        super(BaseAgentExtension, self).__init__()
        self.agent = agent
        self.command_map = dict(
            (v.command_name, v)
            for k, v in inspect.getmembers(self)
            if hasattr(v, 'command_name')
        )

    def execute(self, command_name, **kwargs):
        """
        Execute a command.

        Args:
            self: (todo): write your description
            command_name: (str): write your description
        """
        cmd = self.command_map.get(command_name)
        if cmd is None:
            raise errors.InvalidCommandError(
                'Unknown command: {}'.format(command_name))
        return cmd(**kwargs)

    def check_cmd_presence(self, ext_obj, ext, cmd):
        """
        Check if the presence of the given ext_obj.

        Args:
            self: (todo): write your description
            ext_obj: (todo): write your description
            ext: (str): write your description
            cmd: (str): write your description
        """
        if not (hasattr(ext_obj, 'execute') and hasattr(ext_obj, 'command_map')
                and cmd in ext_obj.command_map):
            raise errors.InvalidCommandParamsError(
                "Extension {} doesn't provide {} method".format(ext, cmd))


class ExecuteCommandMixin(object):
    def __init__(self):
        """
        Initialize the command

        Args:
            self: (todo): write your description
        """
        self.command_lock = threading.Lock()
        self.command_results = collections.OrderedDict()
        self.ext_mgr = None

    def get_extension(self, extension_name):
        """
        Get the extension of the given extension.

        Args:
            self: (todo): write your description
            extension_name: (str): write your description
        """
        if self.ext_mgr is None:
            raise errors.ExtensionError('Extension manager is not initialized')
        ext = self.ext_mgr[extension_name].obj
        ext.ext_mgr = self.ext_mgr
        return ext

    def split_command(self, command_name):
        """
        Splits command name into the given command_name.

        Args:
            self: (todo): write your description
            command_name: (str): write your description
        """
        command_parts = command_name.split('.', 1)
        if len(command_parts) != 2:
            raise errors.InvalidCommandError(
                'Command name must be of the form <extension>.<name>')

        return (command_parts[0], command_parts[1])

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        with self.command_lock:
            LOG.debug('Executing command: %(name)s with args: %(args)s',
                      {'name': command_name,
                       'args': utils.remove_large_keys(kwargs)})
            extension_part, command_part = self.split_command(command_name)

            if len(self.command_results) > 0:
                last_command = list(self.command_results.values())[-1]
                if not last_command.is_done():
                    LOG.error('Tried to execute %(command)s, agent is still '
                              'executing %(last)s', {'command': command_name,
                                                     'last': last_command})
                    raise errors.AgentIsBusy(last_command.command_name)

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
        """
        Decorator that adds a command to a command.

        Args:
            func: (todo): write your description
        """
        func.command_name = command_name

        @functools.wraps(func)
        def wrapper(self, **command_params):
            """
            Execute a command.

            Args:
                self: (todo): write your description
                command_params: (dict): write your description
            """
            # Run a validator before passing everything off to async.
            # validators should raise exceptions or return silently.
            if validator:
                validator(self, **command_params)

            # bind self to func so that AsyncCommandResult doesn't need to
            # know about the mode
            bound_func = functools.partial(func, self)

            ret = AsyncCommandResult(command_name,
                                     command_params,
                                     bound_func,
                                     agent=self.agent).start()
            LOG.info('Asynchronous command %(name)s started execution',
                     {'name': command_name})
            return ret
        return wrapper
    return async_decorator


def sync_command(command_name, validator=None):
    """Decorate a method to wrap its return value in a SyncCommandResult.

    For consistency with @async_command() can also accept a
    validator which will be used to validate input, although a synchronous
    command can also choose to implement validation inline.
    """
    def sync_decorator(func):
        """
        Decorator to add a command to the command.

        Args:
            func: (todo): write your description
        """
        func.command_name = command_name

        @functools.wraps(func)
        def wrapper(self, **command_params):
            """
            Wrapper around a command.

            Args:
                self: (todo): write your description
                command_params: (dict): write your description
            """
            # Run a validator before invoking the function.
            # validators should raise exceptions or return silently.
            if validator:
                validator(self, **command_params)

            result = func(self, **command_params)
            LOG.info('Synchronous command %(name)s completed: %(result)s',
                     {'name': command_name,
                      'result': utils.remove_large_keys(result)})
            return SyncCommandResult(command_name,
                                     command_params,
                                     True,
                                     result)

        return wrapper
    return sync_decorator


_EXT_MANAGER = None


def init_ext_manager(agent):
    """
    Initialize the manager manager.

    Args:
        agent: (str): write your description
    """
    global _EXT_MANAGER
    _EXT_MANAGER = extension.ExtensionManager(
        namespace='ironic_python_agent.extensions',
        invoke_on_load=True,
        propagate_map_exceptions=True,
        invoke_kwds={'agent': agent},
    )
    return _EXT_MANAGER


def get_extension(name):
    """
    Get the extension of the given extension.

    Args:
        name: (str): write your description
    """
    if _EXT_MANAGER is None:
        raise errors.ExtensionError('Extension manager is not initialized')
    ext = _EXT_MANAGER[name].obj
    ext.ext_mgr = _EXT_MANAGER
    return ext

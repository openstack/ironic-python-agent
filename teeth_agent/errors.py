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

from teeth_rest import errors


class CommandExecutionError(errors.RESTError):
    """Error raised when a command fails to execute."""

    message = 'Command execution failed'

    def __init__(self, details):
        super(CommandExecutionError, self).__init__()
        self.details = details


class InvalidCommandError(errors.InvalidContentError):
    """Error which is raised when an unknown command is issued."""

    messsage = 'Unknown command'

    def __init__(self, command_name):
        details = 'Command \'{}\' is unknown.'.format(command_name)
        super(InvalidCommandError, self).__init__(details)


class InvalidCommandParamsError(errors.InvalidContentError):
    """Error which is raised when command parameters are invalid."""

    message = 'Invalid command parameters'

    def __init__(self, details):
        super(InvalidCommandParamsError, self).__init__(details)


class RequestedObjectNotFoundError(errors.NotFound):
    def __init__(self, type_descr, obj_id):
        details = '{} with id {} not found.'.format(type_descr, obj_id)
        super(RequestedObjectNotFoundError, self).__init__(details)
        self.details = details


class HeartbeatError(errors.RESTError):
    """Error raised when a heartbeat to the agent API fails."""

    message = 'Error heartbeating to agent API.'

    def __init__(self, details):
        super(HeartbeatError, self).__init__()
        self.details = details

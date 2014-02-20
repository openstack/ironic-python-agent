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
import functools
import inspect

from teeth_agent import base


def async_command(validator=None):
    """Will run the command in an AsyncCommandResult in its own thread.
    command_name is set based on the func name and command_params will
    be whatever args/kwargs you pass into the decorated command.
    """
    def async_decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Run a validator before passing everything off to async.
            # validators should raise exceptions or return silently.
            if validator:
                validator(*args, **kwargs)
            # Grab the variable names from the func definition.
            command_names = inspect.getargspec(func)[0]
            # Create dict {command_name: arg,...}
            if command_names[0] == "self":
                command_params = dict(zip(command_names[1:len(args)+1], args))
            else:
                command_params = dict(zip(command_names[:len(args)], args))
            # Add all of kwargs
            command_params = dict(command_params.items() + kwargs.items())
            return base.AsyncCommandResult(func.__name__,
                                           command_params,
                                           func).start()
        return wrapper
    return async_decorator

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

from teeth_agent import base


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
                validator(**command_params)

            # bind self to func so that AsyncCommandResult doesn't need to
            # know about the mode
            bound_func = functools.partial(func, self)

            return base.AsyncCommandResult(command_name,
                                           command_params,
                                           bound_func).start()
        return wrapper
    return async_decorator

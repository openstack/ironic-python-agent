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
import time

import pkg_resources
from teeth_rest import encoding
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


class BaseTeethAgent(object):
    def __init__(self, listen_host, listen_port, mode):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.started_at = None
        self.mode = mode
        self.api = api.TeethAgentAPIServer(self)
        self.command_map = {}

    def get_status(self):
        """Retrieve a serializable status."""
        return TeethAgentStatus(
            mode=self.mode,
            started_at=self.started_at,
            version=pkg_resources.get_distribution('teeth-agent').version
        )

    def execute_command(self, command_name, **kwargs):
        """Execute an agent command."""
        if command_name not in self.command_map:
            raise errors.InvalidCommandError(command_name)

        self.command_map[command_name](**kwargs)

        # TODO(russellhaering): allow long-running commands to return a
        # "promise" which can be converted into a watch URL.

    def run(self):
        """Run the Teeth Agent."""
        if self.started_at:
            raise RuntimeError('Agent was already started')

        self.started_at = time.time()
        serving.run_simple(self.listen_host, self.listen_port, self.api)

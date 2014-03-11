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

from teeth_rest import component
from teeth_rest import errors
from teeth_rest import responses


class AgentCommand(object):
    def __init__(self, name, params):
        self.name = name
        self.params = params

    @classmethod
    def deserialize(cls, obj):
        for field in ['name', 'params']:
            if field not in obj:
                msg = 'Missing command \'{0}\' field.'.format(field)
                raise errors.InvalidContentError(msg)

        if type(obj['params']) != dict:
            raise errors.InvalidContentError(
                'Command params must be a dictionary.')

        return cls(obj['name'], obj['params'])


class TeethAgentAPI(component.APIComponent):
    """The primary Teeth Agent API."""

    def __init__(self, agent):
        super(TeethAgentAPI, self).__init__()
        self.agent = agent

    def add_routes(self):
        """Called during initialization. Override to map relative routes to
        methods.
        """
        self.route('GET', '/status', self.get_agent_status)
        self.route('GET', '/commands', self.list_command_results)
        self.route('POST', '/commands', self.execute_command)
        self.route('GET',
                   '/commands/<string:result_id>',
                   self.get_command_result)

    def get_agent_status(self, request):
        """Get the status of the agent."""
        return responses.ItemResponse(self.agent.get_status())

    def list_command_results(self, request):
        # TODO(russellhaering): pagination
        command_results = self.agent.list_command_results()
        return responses.PaginatedResponse(request,
                                           command_results,
                                           self.list_command_results,
                                           None,
                                           None)

    def execute_command(self, request):
        """Execute a command on the agent."""
        command = AgentCommand.deserialize(self.parse_content(request))
        result = self.agent.execute_command(command.name, **command.params)

        wait = request.args.get('wait')
        if wait and wait.lower() == 'true':
            result.join()

        return responses.ItemResponse(result)

    def get_command_result(self, request, result_id):
        """Retrieve the result of a command."""
        result = self.agent.get_command_result(result_id)

        wait = request.args.get('wait')
        if wait and wait.lower() == 'true':
            result.join()

        return responses.ItemResponse(result)


class TeethAgentAPIServer(component.APIServer):
    """Server for the teeth agent API."""

    def __init__(self, agent):
        super(TeethAgentAPIServer, self).__init__()
        self.add_component('/v1.0', TeethAgentAPI(agent))

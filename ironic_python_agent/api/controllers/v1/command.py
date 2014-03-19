# Copyright 2014 Rackspace, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import pecan
from pecan import rest
from wsme import types
from wsmeext import pecan as wsme_pecan

from teeth_agent.api.controllers.v1 import base


class CommandResult(base.APIBase):
    id = types.text
    command_name = types.text
    command_params = types.DictType(types.text, base.json_type)
    command_status = types.text
    command_error = base.exception_type
    command_result = types.DictType(types.text, base.json_type)

    @classmethod
    def from_result(cls, result):
        instance = cls()
        for field in ('id', 'command_name', 'command_params', 'command_status',
                      'command_error', 'command_result'):
            setattr(instance, field, getattr(result, field))
        return instance


class CommandResultList(base.APIBase):
    commands = [CommandResult]

    @classmethod
    def from_results(cls, results):
        instance = cls()
        instance.commands = [CommandResult.from_result(result)
                             for result in results]
        return instance


class Command(base.APIBase):
    """A command representation."""
    name = types.wsattr(types.text, mandatory=True)
    params = types.wsattr(base.MultiType(dict), mandatory=True)


class CommandController(rest.RestController):
    """Controller for issuing commands and polling for command status."""

    @wsme_pecan.wsexpose(CommandResultList)
    def get_all(self):
        agent = pecan.request.agent
        results = agent.list_command_results()
        return CommandResultList.from_results(results)

    @wsme_pecan.wsexpose(CommandResult, types.text, types.text)
    def get_one(self, result_id, wait=False):
        agent = pecan.request.agent
        result = agent.get_command_result(result_id)

        if wait and wait.lower() == 'true':
            result.join()

        return CommandResult.from_result(result)

    @wsme_pecan.wsexpose(CommandResult, body=Command)
    def post(self, wait=False, command=None):
        # the POST body is always the last arg,
        # so command must be a kwarg here
        if command is None:
            command = Command()
        agent = pecan.request.agent
        result = agent.execute_command(command.name, **command.params)

        if wait and wait.lower() == 'true':
            result.join()

        return result

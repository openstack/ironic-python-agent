# Copyright 2014 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent.extensions import base

LOG = log.getLogger(__name__)


def _validate_exts(ext, flow=None):
    for task in flow:
        for method in task:
            ext_name, cmd = ext.split_command(method)
            if ext_name not in ext.ext_mgr.names():
                raise errors.RequestedObjectNotFoundError('Extension',
                                                          ext_name)
            ext_obj = ext.ext_mgr[ext_name].obj
            ext.check_cmd_presence(ext_obj, ext_name, cmd)


class FlowExtension(base.BaseAgentExtension, base.ExecuteCommandMixin):
    @base.async_command('start_flow', _validate_exts)
    def start_flow(self, flow=None):
        for task in flow:
            for method, params in task.items():
                LOG.info("Executing method %s for now" % method)
                result = self.execute_command(method, **params)
                result.join()
                LOG.info("%s method's execution is done" % method)
                if result.command_status == base.AgentCommandStatus.FAILED:
                    raise errors.CommandExecutionError(
                        "%s was failed" % method
                    )

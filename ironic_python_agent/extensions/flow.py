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

from stevedore import enabled

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent.openstack.common import log

LOG = log.getLogger(__name__)


def _load_extension(ext):
    disabled_extension_list = ['flow']
    return ext.name not in disabled_extension_list


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
    def __init__(self):
        super(FlowExtension, self).__init__('FLOW')
        self.command_map['start_flow'] = self.start_flow

    def get_extension_manager(self):
        return enabled.EnabledExtensionManager(
            'ironic_python_agent.extensions',
            _load_extension,
            invoke_on_load=True,
            propagate_map_exceptions=True,
        )

    @base.async_command(_validate_exts)
    def start_flow(self, command_name, flow=None):
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

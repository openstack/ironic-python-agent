# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware

LOG = log.getLogger(__name__)


class PollExtension(base.BaseAgentExtension):

    @base.sync_command('get_hardware_info')
    def get_hardware_info(self):
        """Get the hardware information where IPA is running."""
        hardware_info = hardware.dispatch_to_managers('list_hardware_info')
        return hardware_info

    @base.sync_command('set_node_info')
    def set_node_info(self, node_info=None):
        """Set node lookup data when IPA is running at passive mode.

        :param node_info: A dictionary contains the information of the node
                          where IPA is running.
        """
        if not self.agent.standalone:
            error_msg = ('Node lookup data can only be set when the Ironic '
                         'Python Agent is running in standalone mode.')
            LOG.error(error_msg)
            raise errors.InvalidCommandError(error_msg)
        LOG.debug('Received lookup results: %s', node_info)
        self.agent.process_lookup_data(node_info)

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

from ironic_python_agent.extensions import base

LOG = log.getLogger(__name__)


class SystemExtension(base.BaseAgentExtension):

    # TODO(dtantsur): migrate (with deprecation) other system-wide commands
    # from standby (power_off, run_image renamed into reboot, sync).

    @base.sync_command('lockdown')
    def lockdown(self):
        """Lock the agent down to prevent interactions with it."""
        self.agent.lockdown = True
        self.agent.serve_api = False

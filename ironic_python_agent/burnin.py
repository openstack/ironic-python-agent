# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_log import log

from ironic_python_agent import errors

LOG = log.getLogger(__name__)


def stress_ng_cpu(node):
    """Burn-in the CPU with stress-ng

    Run stress-ng on a configurable number of CPUs for
    a configurable amount of time. Without config use
    all CPUs and stress them for 24 hours.

    :param node: Ironic node object
    :raises: CommandExecutionError if the execution of stress-ng fails.
    """
    info = node.get('driver_info', {})
    cpu = info.get('agent_burnin_cpu_cpu', 0)
    timeout = info.get('agent_burnin_cpu_timeout', 86400)

    args = ('stress-ng', '--cpu', cpu, '--timeout', timeout,
            '--metrics-brief')
    LOG.debug('Burn-in stress_ng_cpu command: %s', args)

    try:
        _, err = utils.execute(*args)
        # stress-ng reports on stderr only
        LOG.info(err)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = ("stress-ng (cpu) failed with error %(err)s",
                     {'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)

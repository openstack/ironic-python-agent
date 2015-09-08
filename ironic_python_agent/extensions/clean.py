# Copyright 2015 Rackspace, Inc.
#
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

LOG = log.getLogger()


class CleanExtension(base.BaseAgentExtension):
    @base.sync_command('get_clean_steps')
    def get_clean_steps(self, node, ports):
        """Get the list of clean steps supported for the node and ports

        :param node: A dict representation of a node
        :param ports: A dict representation of ports attached to node

        :returns: A list of clean steps with keys step, priority, and
            reboot_requested
        """
        LOG.debug('Getting clean steps, called with node: %(node)s, '
                  'ports: %(ports)s', {'node': node, 'ports': ports})
        # Results should be a dict, not a list
        steps = hardware.dispatch_to_all_managers('get_clean_steps',
                                                  node, ports)

        LOG.debug('Returning clean steps: %s', steps)
        return {
            'clean_steps': steps,
            'hardware_manager_version': _get_current_clean_version()
        }

    @base.async_command('execute_clean_step')
    def execute_clean_step(self, step, node, ports, clean_version=None,
                           **kwargs):
        """Execute a clean step.

        :param step: A clean step with 'step', 'priority' and 'interface' keys
        :param node: A dict representation of a node
        :param ports: A dict representation of ports attached to node
        :param clean_version: The clean version as returned by
                              _get_current_clean_version() at the beginning
                              of cleaning/zapping
        :returns: a CommandResult object with command_result set to whatever
            the step returns.
        """
        # Ensure the agent is still the same version, or raise an exception
        LOG.debug('Executing clean step %s', step)
        _check_clean_version(clean_version)

        if 'step' not in step:
            msg = 'Malformed clean_step, no "step" key: %s' % step
            LOG.error(msg)
            raise ValueError(msg)
        try:
            result = hardware.dispatch_to_managers(step['step'], node, ports)
        except Exception as e:
            msg = ('Error performing clean_step %(step)s: %(err)s' %
                   {'step': step['step'], 'err': e})
            LOG.exception(msg)
            raise errors.CleaningError(msg)

        LOG.info('Clean step completed: %(step)s, result: %(result)s',
                 {'step': step, 'result': result})

        # Cast result tuples (like output of utils.execute) as lists, or
        # WSME throws errors
        if isinstance(result, tuple):
            result = list(result)

        # Return the step that was executed so we can dispatch
        # to the appropriate Ironic interface
        return {
            'clean_result': result,
            'clean_step': step
        }


def _check_clean_version(clean_version=None):
    """Ensure the clean version hasn't changed.

    :param clean_version: Hardware manager versions used during this
                          cleaning cycle.
    :raises: errors.CleanVersionMismatch if any hardware manager version on
             the currently running agent doesn't match the one stored in
             clean_version.
    :returns: None
    """
    # If the version is None, assume this is the first run
    if clean_version is None:
        return
    agent_version = _get_current_clean_version()
    if clean_version != agent_version:
        LOG.warning('Mismatched clean versions. Agent version: %(agent), '
                    'node version: %(node)', {'agent': agent_version,
                                              'node': clean_version})
        raise errors.CleanVersionMismatch(agent_version=agent_version,
                                          node_version=clean_version)


def _get_current_clean_version():
    """Fetches versions from all hardware managers.

    :returns: Dict in the format {name: version} containing one entry for
              every hardware manager.
    """
    return {version.get('name'): version.get('version')
            for version in hardware.dispatch_to_all_managers(
                'get_version').values()}

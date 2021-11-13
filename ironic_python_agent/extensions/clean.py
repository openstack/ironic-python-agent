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

from ironic_lib import exception as il_exc
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
        hardware.cache_node(node)
        # Results should be a dict, not a list
        candidate_steps = hardware.dispatch_to_all_managers('get_clean_steps',
                                                            node, ports)

        LOG.debug('Clean steps before deduplication: %s', candidate_steps)
        clean_steps = hardware.deduplicate_steps(candidate_steps)
        LOG.debug('Returning clean steps: %s', clean_steps)

        return {
            'clean_steps': clean_steps,
            'hardware_manager_version': hardware.get_current_versions(),
        }

    @base.async_command('execute_clean_step')
    def execute_clean_step(self, step, node, ports, clean_version=None,
                           **kwargs):
        """Execute a clean step.

        :param step: A clean step with 'step', 'priority' and 'interface' keys
        :param node: A dict representation of a node
        :param ports: A dict representation of ports attached to node
        :param clean_version: The clean version as returned by
                              hardware.get_current_versions() at the beginning
                              of cleaning/zapping
        :returns: a CommandResult object with command_result set to whatever
            the step returns.
        """
        # Ensure the agent is still the same version, or raise an exception
        LOG.debug('Executing clean step %s', step)
        hardware.cache_node(node)
        hardware.check_versions(clean_version)

        if 'step' not in step:
            msg = 'Malformed clean_step, no "step" key: %s' % step
            LOG.error(msg)
            raise ValueError(msg)
        try:
            result = hardware.dispatch_to_managers(step['step'], node, ports)
        except (errors.RESTError, il_exc.IronicException):
            LOG.exception('Error performing clean step %s', step['step'])
            raise
        except Exception as e:
            msg = ('Unexpected exception performing clean step %(step)s. '
                   '%(cls)s: %(err)s' % {'step': step['step'],
                                         'cls': e.__class__.__name__,
                                         'err': e})
            LOG.exception(msg)
            raise errors.CleaningError(msg)

        LOG.info('Clean step completed: %(step)s, result: %(result)s',
                 {'step': step, 'result': result})

        # Cast result tuples (like output of utils.execute) as lists, or
        # API throws errors
        if isinstance(result, tuple):
            result = list(result)

        # Return the step that was executed so we can dispatch
        # to the appropriate Ironic interface
        return {
            'clean_result': result,
            'clean_step': step
        }

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


class DeployExtension(base.BaseAgentExtension):
    @base.sync_command('get_deploy_steps')
    def get_deploy_steps(self, node, ports):
        """Get the list of deploy steps supported for the node and ports

        :param node: A dict representation of a node
        :param ports: A dict representation of ports attached to node

        :returns: A list of deploy steps with keys step, priority, and
            reboot_requested
        """
        LOG.debug('Getting deploy steps, called with node: %(node)s, '
                  'ports: %(ports)s', {'node': node, 'ports': ports})
        hardware.cache_node(node)
        # Results should be a dict, not a list
        candidate_steps = hardware.dispatch_to_all_managers('get_deploy_steps',
                                                            node, ports)

        LOG.debug('Deploy steps before deduplication: %s', candidate_steps)
        deploy_steps = hardware.deduplicate_steps(candidate_steps)
        LOG.debug('Returning deploy steps: %s', deploy_steps)

        return {
            'deploy_steps': deploy_steps,
            'hardware_manager_version': hardware.get_current_versions(),
        }

    @base.async_command('execute_deploy_step')
    def execute_deploy_step(self, step, node, ports, deploy_version=None,
                            **kwargs):
        """Execute a deploy step.

        :param step: A deploy step with 'step', 'priority' and 'interface' keys
        :param node: A dict representation of a node
        :param ports: A dict representation of ports attached to node
        :param deploy_version: The deploy version as returned by
                               hardware.get_current_versions() at the beginning
                               of deploying.
        :param kwargs: The remaining arguments are passed to the step.
        :returns: a CommandResult object with command_result set to whatever
            the step returns.
        """
        # Ensure the agent is still the same version, or raise an exception
        LOG.debug('Executing deploy step %s', step)
        hardware.cache_node(node)
        hardware.check_versions(deploy_version)

        if 'step' not in step:
            msg = 'Malformed deploy_step, no "step" key: %s' % step
            LOG.error(msg)
            raise ValueError(msg)

        kwargs.update(step.get('args') or {})
        try:
            result = hardware.dispatch_to_managers(step['step'], node, ports,
                                                   **kwargs)
        except (errors.RESTError, il_exc.IronicException):
            LOG.exception('Error performing deploy step %s', step['step'])
            raise
        except Exception as e:
            msg = ('Unexpected exception performing deploy step %(step)s. '
                   '%(cls)s: %(err)s' % {'step': step['step'],
                                         'cls': e.__class__.__name__,
                                         'err': e})
            LOG.exception(msg)
            raise errors.DeploymentError(msg)

        LOG.info('Deploy step completed: %(step)s, result: %(result)s',
                 {'step': step, 'result': result})

        # Cast result tuples (like output of utils.execute) as lists, or
        # API throws errors
        if isinstance(result, tuple):
            result = list(result)

        # Return the step that was executed so we can dispatch
        # to the appropriate Ironic interface
        return {
            'deploy_result': result,
            'deploy_step': step
        }

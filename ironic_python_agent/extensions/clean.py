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

import collections

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
        candidate_steps = hardware.dispatch_to_all_managers('get_clean_steps',
                                                            node, ports)

        LOG.debug('Clean steps before deduplication: %s', candidate_steps)
        clean_steps = _deduplicate_steps(candidate_steps)
        LOG.debug('Returning clean steps: %s', clean_steps)

        return {
            'clean_steps': clean_steps,
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


def _deduplicate_steps(candidate_steps):
    """Remove duplicated clean steps

    Deduplicates clean steps returned from HardwareManagers to prevent
    running a given step more than once. Other than individual step
    priority, it doesn't actually impact the cleaning run which specific
    steps are kept and what HardwareManager they are associated with.
    However, in order to make testing easier, this method returns
    deterministic results.

    Uses the following filtering logic to decide which step "wins":
    - Keep the step that belongs to HardwareManager with highest
      HardwareSupport (larger int) value.
    - If equal support level, keep the step with the higher defined priority
      (larger int).
    - If equal support level and priority, keep the step associated with the
      HardwareManager whose name comes earlier in the alphabet.

    :param candidate_steps: A dict containing all possible clean steps from
        all managers, key=manager, value=list of clean steps
    :returns: A deduplicated dictionary of {hardware_manager:
        [clean-steps]}
    """
    support = hardware.dispatch_to_all_managers(
        'evaluate_hardware_support')

    steps = collections.defaultdict(list)
    deduped_steps = collections.defaultdict(list)

    for manager, manager_steps in candidate_steps.items():
        # We cannot deduplicate steps with unknown hardware support
        if manager not in support:
            LOG.warning('Unknown hardware support for %(manager)s, '
                        'dropping clean steps: %(steps)s',
                        {'manager': manager, 'steps': manager_steps})
            continue

        for step in manager_steps:
            # build a new dict of steps that's easier to filter
            step['hwm'] = {'name': manager,
                           'support': support[manager]}
            steps[step['step']].append(step)

    for step_name, step_list in steps.items():
        # determine the max support level among candidate steps
        max_support = max([x['hwm']['support'] for x in step_list])
        # filter out any steps that are not at the max support for this step
        max_support_steps = [x for x in step_list
                             if x['hwm']['support'] == max_support]

        # determine the max priority among remaining steps
        max_priority = max([x['priority'] for x in max_support_steps])
        # filter out any steps that are not at the max priority for this step
        max_priority_steps = [x for x in max_support_steps
                              if x['priority'] == max_priority]

        # if there are still multiple steps, sort by hwm name and take
        # the first result
        winning_step = sorted(max_priority_steps,
                              key=lambda x: x['hwm']['name'])[0]
        # Remove extra metadata we added to the step for filtering
        manager = winning_step.pop('hwm')['name']
        # Add winning step to deduped_steps
        deduped_steps[manager].append(winning_step)

    return deduped_steps


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

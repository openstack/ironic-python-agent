# Copyright 2015 Rackspace, Inc.
#
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

import time

from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent import hardware

LOG = log.getLogger()


class ExampleBusinessLogicHardwareManager(hardware.HardwareManager):
    """Example hardware manager to enforce business logic"""

    # All hardware managers have a name and a version.
    # Version should be bumped anytime a change is introduced. This will
    # signal to Ironic that if automatic node cleaning is in progress to
    # restart it from the beginning, to ensure consistency. The value can
    # be anything; it's checked for equality against previously seen
    # name:manager pairs.
    HARDWARE_MANAGER_NAME = 'ExampleBusinessLogicHardwareManager'
    HARDWARE_MANAGER_VERSION = '1'

    def evaluate_hardware_support(self):
        """Declare level of hardware support provided.

        Since this example is explicitly about enforcing business logic during
        cleaning, we want to return a static value.

        :returns: HardwareSupport level for this manager.
        """
        return hardware.HardwareSupport.SERVICE_PROVIDER

    def get_clean_steps(self, node, ports):
        """Get a list of clean steps with priority.

        Define any clean steps added by this manager here. These will be mixed
        with other loaded managers that support this hardware, and ordered by
        priority. Higher priority steps run earlier.

        Note that out-of-band clean steps may also be provided by Ironic.
        These will follow the same priority ordering even though they are not
        executed by IPA.

        There is *no guarantee whatsoever* that steps defined here will be
        executed by this HardwareManager. When it comes time to run these
        steps, they'll be called using dispatch_to_managers() just like any
        other IPA HardwareManager method. This means if they are unique to
        your hardware, they should be uniquely named. For example,
        upgrade_firmware would be a bad step name. Whereas
        upgrade_foobar_device_firmware would be better.

        :param node: The node object as provided by Ironic.
        :param ports: Port objects as provided by Ironic.
        :returns: A list of cleaning steps, as a list of dicts.
        """
        # While obviously you could actively run code here, generally this
        # should just return a static value, as any initialization and
        # detection should've been done in evaluate_hardware_support().
        return [{
            'step': 'companyx_verify_device_lifecycle',
            'priority': 472,
            # If you need Ironic to coordinate a reboot after this step
            # runs, but before continuing cleaning, this should be true.
            'reboot_requested': False,
            # If it's safe for Ironic to abort cleaning while this step
            # runs, this should be true.
            'abortable': True
        }]

    # Other examples of interesting cleaning steps for this kind of hardware
    # manager would include verifying node.properties matches current state of
    # the node, checking smart stats to ensure the disk is not soon to fail,
    # or enforcing security policies.
    def companyx_verify_device_lifecycle(self, node, ports):
        """Verify node is not beyond useful life of 3 years."""
        create_date = node.get('created_at')
        if create_date is not None:
            server_age = time.time() - time.mktime(time.strptime(create_date))
            if server_age > (60 * 60 * 24 * 365 * 3):
                raise errors.CleaningError(
                    'Server is too old to pass cleaning!')
            else:
                LOG.info('Node is %s seconds old, younger than 3 years, '
                         'cleaning passes.', server_age)

    def get_deploy_steps(self, node, ports):
        """Get a list of deploy steps with priority.

        Returns a list of steps. Each step is represented by a dict::

          {
           'interface': the name of the driver interface that should execute
                        the step.
           'step': the HardwareManager function to call.
           'priority': the order steps will be run in. Ironic will sort all
                       the deploy steps from all the drivers, with the largest
                       priority step being run first. If priority is set to 0,
                       the step will not be run during deployment
                       automatically, but may be requested via deploy
                       templates.
           'reboot_requested': Whether the agent should request Ironic reboots
                               the node via the power driver after the
                               operation completes.
           'argsinfo': arguments specification.
          }


        Deploy steps are executed by similar logic to clean steps, but during
        deploy time. The following priority ranges should be used:

        * 81 to 99 - deploy steps to run before the image is written.
        * 61 to 79 - deploy steps to run after the image is written but before
          the bootloader is installed.
        * 41 to 59 - steps to run after the image is written and the bootloader
          is installed.

        If priority is zero, the step must be explicitly selected via
        an applied deploy template.

        Note that each deploy step makes deployments longer. Try to use clean
        steps for anything that is not required to be run just before an
        instance is ready.

        :param node: Ironic node object
        :param ports: list of Ironic port objects
        :return: a list of deploying steps, where each step is described as a
                 dict as defined above

        """
        return [
            {
                'step': 'companyx_verify_memory',
                'priority': 90,  # always run before the image is written
                'interface': 'deploy',
                'reboot_requested': False,
            },
            {
                'step': 'companyx_apply_something',
                'priority': 0,  # only run explicitly
                'interface': 'deploy',
                'reboot_requested': False,
                'argsinfo': {
                    "required_value": {
                        "description": "An example required argument.",
                        "required": True,
                    },
                    "optional_value": {
                        "description": "An example optional argument.",
                        "required": False,
                    }

                }
            },
        ]

    def companyx_verify_memory(self, node, ports):
        expected = node.get('properties', {}).get('memory_mb')
        if expected is None:
            LOG.warning('The node does not have memory, cannot verify')
            return
        else:
            expected = int(expected)

        # Use dispatch_to_managers to avoid tight coupling between hardware
        # managers. It would make sense even if this hardware manager
        # implemented get_memory, because a more specific hardware managers
        # could do it better.
        current = hardware.dispatch_to_managers('get_memory')
        if current.physical_mb < expected:
            # Raising an exception will fail deployment and set the node's
            # last_error accordingly.
            raise errors.DeploymentError(
                'Memory too low, expected {}, got {}'.format(
                    expected, current.physical_mb))

    # Make sure to provide default values for optional arguments.
    def companyx_apply_something(self, node, ports, required_value,
                                 optional_value=None):
        LOG.info('apply_something called with required_value={} and '
                 'optional_value={}'.format(required_value, optional_value))

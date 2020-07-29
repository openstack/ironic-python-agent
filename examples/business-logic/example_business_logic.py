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

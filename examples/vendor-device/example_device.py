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

from oslo_log import log

from ironic_python_agent import hardware

LOG = log.getLogger()


# All the helper methods should be kept outside of the HardwareManager
# so they'll never get accidentally called by dispatch_to_managers()
def _initialize_hardware():
    """Example method for initializing hardware."""
    # Perform any operations here that are required to initialize your
    # hardware.
    LOG.debug('Loading drivers, settling udevs, and generally initalizing')
    pass


def _detect_hardware():
    """Example method for hardware detection."""
    # For this example, return true if hardware is detected, false if not
    LOG.debug('Looking for example device')
    return True


def _is_latest_firmware():
    """Detect if device is running latest firmware."""
    # Actually detect the firmware version instead of returning here.
    return True


def _upgrade_firmware():
    """Upgrade firmware on device."""
    # Actually perform firmware upgrade instead of returning here.
    return True


class ExampleDeviceHardwareManager(hardware.HardwareManager):
    """Example hardware manager to support a single device"""

    # All hardware managers have a name and a version.
    # Version should be bumped anytime a change is introduced. This will
    # signal to Ironic that if automatic node cleaning is in progress to
    # restart it from the beginning, to ensure consistency. The value can
    # be anything; it's checked for equality against previously seen
    # name:manager pairs.
    HARDWARE_MANAGER_NAME = 'ExampleDeviceHardwareManager'
    HARDWARE_MANAGER_VERSION = '1'

    def evaluate_hardware_support(self):
        """Declare level of hardware support provided.

        Since this example covers a case of supporting a specific device,
        this method is where you would do anything needed to initialize that
        device, including loading drivers, and then detect if one exists.

        In some cases, if you expect the hardware to be available on any node
        running this hardware manager, or it's undetectable, you may want to
        return a static value here.

        Be aware all managers' loaded in IPA will run this method before IPA
        performs a lookup or begins heartbeating, so the time needed to
        execute this method will make cleaning and deploying slower.

        :returns: HardwareSupport level for this manager.
        """
        _initialize_hardware()
        if _detect_hardware():
            # This actually resolves down to an int. Upstream IPA will never
            # return a value higher than 2 (HardwareSupport.MAINLINE). This
            # means your managers should always be SERVICE_PROVIDER or higher.
            LOG.debug('Found example device, returning SERVICE_PROVIDER')
            return hardware.HardwareSupport.SERVICE_PROVIDER
        else:
            # If the hardware isn't supported, return HardwareSupport.NONE (0)
            # in order to prevent IPA from loading its clean steps or
            # attempting to use any methods inside it.
            LOG.debug('No example devices found, returning NONE')
            return hardware.HardwareSupport.NONE

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
            'step': 'upgrade_example_device_model1234_firmware',
            'priority': 37,
            # If you need Ironic to coordinate a reboot after this step
            # runs, but before continuing cleaning, this should be true.
            'reboot_requested': True,
            # If it's safe for Ironic to abort cleaning while this step
            # runs, this should be true.
            'abortable': False
        }]

    def upgrade_example_device_model1234_firmware(self, node, ports):
        """Upgrade firmware on Example Device Model #1234."""
        # Any commands needed to perform the firmware upgrade should go here.
        # If you plan on actually flashing firmware every cleaning cycle, you
        # should ensure your device will not experience flash exhaustion. A
        # good practice in some environments would be to check the firmware
        # version against a constant in the code, and noop the method if an
        # upgrade is not needed.
        if _is_latest_firmware():
            LOG.debug('Latest firmware already flashed, skipping')
            # Return values are ignored here on success
            return True
        else:
            LOG.debug('Firmware version X found, upgrading to Y')
            # Perform firmware upgrade.
            try:
                _upgrade_firmware()
            except Exception as e:
                # Log and pass through the exception so cleaning will fail
                LOG.exception(e)
                raise
            return True

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

from ironic_python_agent import exceptions
from ironic_python_agent import hardware

LOG = log.getLogger()


def _is_supported_disk(block_device):
    # Helper methods are outside the class, to prevent them from being called
    # by dispatch_to_managers.
    #
    # This method would perform checks to see if this is a disk that is
    # supported by this custom hardware manager.
    return True


class ExampleDiskEraserHardwareManager(hardware.HardwareManager):
    """Example hardware manager to support wiping a specific model disk"""

    # All hardware managers have a name and a version.
    # Version should be bumped anytime a change is introduced. This will
    # signal to Ironic that if automatic node cleaning is in progress to
    # restart it from the beginning, to ensure consistency. The value can
    # be anything; it's checked for equality against previously seen
    # name:manager pairs.
    HARDWARE_MANAGER_NAME = 'ExampleDiskEraserHardwareManager'
    HARDWARE_MANAGER_VERSION = '1'

    def evaluate_hardware_support(self):
        """Declare level of hardware support provided.

        Since this example covers a case of supporting a specific device,
        for disk erasure, we're going to return SERVICE_PROVIDER statically,
        and actually do disk detection in erase_device method.

        :returns: HardwareSupport level for this manager.
        """
        return hardware.HardwareSupport.SERVICE_PROVIDER

    def erase_block_device(self, node, block_device):
        """Erases hardware via custom utility if supported."""
        if not _is_supported_disk(block_device):
            raise exceptions.IncompatibleHardwareMethodError(
                  "Not supported by this manager")

        # Put your code here to wipe the disk.

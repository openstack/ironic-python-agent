# Copyright 2013 Rackspace, Inc.
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

from ironic_python_agent import encoding


class RESTError(Exception, encoding.Serializable):
    """Base class for errors generated in ironic-python-client."""
    # NOTE(JoshNang) `message` should not end with a period
    message = 'An error occurred'
    details = 'An unexpected error occurred. Please try back later.'
    status_code = 500
    serializable_fields = ('type', 'code', 'message', 'details')

    def __init__(self, details=None, *args, **kwargs):
        super(RESTError, self).__init__(*args, **kwargs)
        self.type = self.__class__.__name__
        self.code = self.status_code
        if details:
            self.details = details

    def __str__(self):
        return "{}: {}".format(self.message, self.details)

    def __repr__(self):
        """Should look like RESTError('message: details')"""
        return "{}('{}')".format(self.__class__.__name__, self.__str__())


class InvalidContentError(RESTError):
    """Error which occurs when a user supplies invalid content.

    Either because that content cannot be parsed according to the advertised
    `Content-Type`, or due to a content validation error.
    """
    message = 'Invalid request body'
    status_code = 400

    def __init__(self, details):
        super(InvalidContentError, self).__init__(details)


class NotFound(RESTError):
    """Error which occurs if a non-existent API endpoint is called."""
    message = 'Not found'
    status_code = 404
    details = 'The requested URL was not found.'


class CommandExecutionError(RESTError):
    """Error raised when a command fails to execute."""

    message = 'Command execution failed'

    def __init__(self, details):
        super(CommandExecutionError, self).__init__(details)


class InvalidCommandError(InvalidContentError):
    """Error which is raised when an unknown command is issued."""

    message = 'Invalid command'

    def __init__(self, details):
        super(InvalidCommandError, self).__init__(details)


class InvalidCommandParamsError(InvalidContentError):
    """Error which is raised when command parameters are invalid."""

    message = 'Invalid command parameters'

    def __init__(self, details):
        super(InvalidCommandParamsError, self).__init__(details)


class RequestedObjectNotFoundError(NotFound):
    def __init__(self, type_descr, obj_id):
        details = '{} with id {} not found.'.format(type_descr, obj_id)
        super(RequestedObjectNotFoundError, self).__init__(details)


class IronicAPIError(RESTError):
    """Error raised when a call to the agent API fails."""

    message = 'Error in call to ironic-api'

    def __init__(self, details):
        super(IronicAPIError, self).__init__(details)


class HeartbeatError(IronicAPIError):
    """Error raised when a heartbeat to the agent API fails."""

    message = 'Error heartbeating to agent API'

    def __init__(self, details):
        super(HeartbeatError, self).__init__(details)


class HeartbeatConflictError(IronicAPIError):
    """ConflictError raised when a heartbeat to the agent API fails."""

    message = 'ConflictError heartbeating to agent API'

    def __init__(self, details):
        super(HeartbeatConflictError, self).__init__(details)


class LookupNodeError(IronicAPIError):
    """Error raised when the node lookup to the Ironic API fails."""

    message = 'Error getting configuration from Ironic'

    def __init__(self, details):
        super(LookupNodeError, self).__init__(details)


class LookupAgentIPError(IronicAPIError):
    """Error raised when automatic IP lookup fails."""

    message = 'Error finding IP for Ironic Agent'

    def __init__(self, details):
        super(LookupAgentIPError, self).__init__(details)


class ImageDownloadError(RESTError):
    """Error raised when an image cannot be downloaded."""

    message = 'Error downloading image'

    def __init__(self, image_id, msg):
        details = 'Download of image id {} failed: {}'.format(image_id, msg)
        super(ImageDownloadError, self).__init__(details)


class ImageChecksumError(RESTError):
    """Error raised when an image fails to verify against its checksum."""

    message = 'Error verifying image checksum'
    details_str = ('Image failed to verify against checksum. location: {}; '
                   'image ID: {}; image checksum: {}; verification '
                   'checksum: {}')

    def __init__(self, image_id, image_location, checksum,
                 calculated_checksum):
        details = self.details_str.format(image_location, image_id, checksum,
                                          calculated_checksum)
        super(ImageChecksumError, self).__init__(details)


class ImageWriteError(RESTError):
    """Error raised when an image cannot be written to a device."""

    message = 'Error writing image to device'

    def __init__(self, device, exit_code, stdout, stderr):
        details = ('Writing image to device {} failed with exit code '
                   '{}. stdout: {}. stderr: {}')
        details = details.format(device, exit_code, stdout, stderr)
        super(ImageWriteError, self).__init__(details)


class SystemRebootError(RESTError):
    """Error raised when a system cannot reboot."""

    message = 'Error rebooting system'

    def __init__(self, exit_code, stdout, stderr):
        details = ('Reboot script failed with exit code {}. stdout: '
                   '{}. stderr: {}.')
        details = details.format(exit_code, stdout, stderr)
        super(SystemRebootError, self).__init__(details)


class BlockDeviceEraseError(RESTError):
    """Error raised when an error occurs erasing a block device."""

    message = 'Error erasing block device'

    def __init__(self, details):
        super(BlockDeviceEraseError, self).__init__(details)


class BlockDeviceError(RESTError):
    """Error raised when a block devices causes an unknown error."""

    message = 'Block device caused unknown error'

    def __init__(self, details):
        super(BlockDeviceError, self).__init__(details)


class VirtualMediaBootError(RESTError):
    """Error raised when virtual media device cannot be found for config."""

    message = 'Configuring agent from virtual media failed'

    def __init__(self, details):
        super(VirtualMediaBootError, self).__init__(details)


class ExtensionError(RESTError):
    pass


class UnknownNodeError(RESTError):
    """Error raised when the agent is not associated with an Ironic node."""

    message = 'Agent is not associated with an Ironic node'

    def __init__(self, details=None):
        super(UnknownNodeError, self).__init__(details)


class HardwareManagerNotFound(RESTError):
    """Error raised when no valid HardwareManager can be found."""

    message = 'No valid HardwareManager found'

    def __init__(self, details=None):
        super(HardwareManagerNotFound, self).__init__(details)


class HardwareManagerMethodNotFound(RESTError):
    """Error raised when all HardwareManagers fail to handle a method."""

    message = 'No HardwareManager found to handle method'

    def __init__(self, method):
        details = 'Could not find method: {}'.format(method)
        super(HardwareManagerMethodNotFound, self).__init__(details)


class IncompatibleHardwareMethodError(RESTError):
    """Error raised when HardwareManager method incompatible with hardware."""

    message = 'HardwareManager method is not compatible with hardware'

    def __init__(self, details=None):
        super(IncompatibleHardwareMethodError, self).__init__(details)


class CleanVersionMismatch(RESTError):
    """Error raised when Ironic and the Agent have different versions.

    If the agent version has changed since get_clean_steps was called by
    the Ironic conductor, it indicates the agent has been updated (either
    on purpose, or a new agent was deployed and the node was rebooted).
    Since we cannot know if the upgraded IPA will work with cleaning as it
    stands (steps could have different priorities, either in IPA or in
    other Ironic interfaces), we should restart cleaning from the start.

    """
    message = 'Clean version mismatch, reload agent with correct version'

    def __init__(self, agent_version, node_version):
        self.status_code = 409
        details = ('Agent clean version: {}, node clean version: {}'
                   .format(agent_version, node_version))
        super(CleanVersionMismatch, self).__init__(details)


class CleaningError(RESTError):
    """Error raised when a cleaning step fails."""

    message = 'Clean step failed'

    def __init__(self, details=None):
        super(CleaningError, self).__init__(details)


class ISCSIError(RESTError):
    """Error raised when an image cannot be written to a device."""

    message = 'Error starting iSCSI target'

    def __init__(self, error_msg):
        details = 'Error starting iSCSI target: {}'.format(error_msg)
        super(ISCSIError, self).__init__(details)


class ISCSICommandError(ISCSIError):
    """Error executing TGT command."""

    def __init__(self, error_msg, exit_code, stdout, stderr):
        details = ('{}. Failed with exit code {}. stdout: {}. stderr: {}')
        details = details.format(error_msg, exit_code, stdout, stderr)
        super(ISCSICommandError, self).__init__(details)


class DeviceNotFound(NotFound):
    """Error raised when the device to deploy the image onto is not found."""

    message = ('Error finding the disk or partition device to deploy '
               'the image onto')

    def __init__(self, details):
        super(DeviceNotFound, self).__init__(details)


# This is not something we return to a user, so we don't inherit it from
# RESTError.
class InspectionError(Exception):
    """Failure during inspection."""

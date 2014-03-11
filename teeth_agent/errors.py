"""
Copyright 2013 Rackspace, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from teeth_rest import errors


class CommandExecutionError(errors.RESTError):
    """Error raised when a command fails to execute."""

    message = 'Command execution failed'

    def __init__(self, details):
        super(CommandExecutionError, self).__init__()
        self.details = details


class InvalidCommandError(errors.InvalidContentError):
    """Error which is raised when an unknown command is issued."""

    messsage = 'Invalid command'

    def __init__(self, details):
        super(InvalidCommandError, self).__init__(details)


class InvalidCommandParamsError(errors.InvalidContentError):
    """Error which is raised when command parameters are invalid."""

    message = 'Invalid command parameters'

    def __init__(self, details):
        super(InvalidCommandParamsError, self).__init__(details)


class RequestedObjectNotFoundError(errors.NotFound):
    def __init__(self, type_descr, obj_id):
        details = '{0} with id {1} not found.'.format(type_descr, obj_id)
        super(RequestedObjectNotFoundError, self).__init__(details)
        self.details = details


class OverlordAPIError(errors.RESTError):
    """Error raised when a call to the agent API fails."""

    message = 'Error in call to teeth-agent-api.'

    def __init__(self, details):
        super(OverlordAPIError, self).__init__(details)
        self.details = details


class HeartbeatError(OverlordAPIError):
    """Error raised when a heartbeat to the agent API fails."""

    message = 'Error heartbeating to agent API.'

    def __init__(self, details):
        super(HeartbeatError, self).__init__(details)


class ImageDownloadError(errors.RESTError):
    """Error raised when an image cannot be downloaded."""

    message = 'Error downloading image.'

    def __init__(self, image_id):
        super(ImageDownloadError, self).__init__()
        self.details = 'Could not download image with id {0}.'.format(image_id)


class ImageChecksumError(errors.RESTError):
    """Error raised when an image fails to verify against its checksum."""

    message = 'Error verifying image checksum.'

    def __init__(self, image_id):
        super(ImageChecksumError, self).__init__()
        self.details = 'Image with id {0} failed to verify against checksum.'
        self.details = self.details.format(image_id)


class ImageWriteError(errors.RESTError):
    """Error raised when an image cannot be written to a device."""

    message = 'Error writing image to device.'

    def __init__(self, exit_code, device):
        super(ImageWriteError, self).__init__()
        self.details = 'Writing image to device {0} failed with exit code {1}.'
        self.details = self.details.format(device, exit_code)


class ConfigDriveWriteError(errors.RESTError):
    """Error raised when a configdrive directory cannot be written to a
    device.
    """

    message = 'Error writing configdrive to device.'

    def __init__(self, exit_code, device):
        details = 'Writing configdrive to device {0} failed with exit code ' \
                  '{1}.'
        details = details.format(device, exit_code)
        super(ConfigDriveWriteError, self).__init__(details)
        self.details = details


class SystemRebootError(errors.RESTError):
    """Error raised when a system cannot reboot."""

    message = 'Error rebooting system.'

    def __init__(self, exit_code):
        super(SystemRebootError, self).__init__()
        self.details = 'Reboot script failed with exit code {0}.'
        self.details = self.details.format(exit_code)

# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Version 1 of the Ironic Python Agent API
"""

import pecan
from pecan import rest

from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic_python_agent.api.controllers.v1 import base
from ironic_python_agent.api.controllers.v1 import command
from ironic_python_agent.api.controllers.v1 import link
from ironic_python_agent.api.controllers.v1 import status


class MediaType(base.APIBase):
    """A media type representation."""

    base = wtypes.text
    type = wtypes.text

    def __init__(self, base, type):
        self.base = base
        self.type = type


class V1(base.APIBase):
    """The representation of the version 1 of the API."""

    id = wtypes.text
    "The ID of the version, also acts as the release number"

    media_types = [MediaType]
    "An array of supported media types for this version"

    links = [link.Link]
    "Links that point to a specific URL for this version and documentation"

    commands = [link.Link]
    "Links to the command resource"

    status = [link.Link]
    "Links to the status resource"

    @classmethod
    def convert(self):
        v1 = V1()
        v1.id = "v1"
        v1.links = [
            link.Link.make_link('self',
                                pecan.request.host_url,
                                'v1',
                                '',
                                bookmark=True),
            link.Link.make_link('describedby',
                                'http://docs.openstack.org',
                                'developer',
                                'ironic-python-agent',
                                bookmark=True,
                                type='text/html')
        ]
        v1.commands = [
            link.Link.make_link('self',
                                pecan.request.host_url,
                                'commands',
                                ''),
            link.Link.make_link('bookmark',
                                pecan.request.host_url,
                                'commands',
                                '',
                                bookmark=True)
        ]
        v1.status = [
            link.Link.make_link('self',
                                pecan.request.host_url,
                                'status',
                                ''),
            link.Link.make_link('bookmark',
                                pecan.request.host_url,
                                'status',
                                '',
                                bookmark=True)
        ]
        v1.media_types = [MediaType('application/json',
                                    ('application/vnd.openstack.'
                                     'ironic-python-agent.v1+json'))]
        return v1


class Controller(rest.RestController):
    """Version 1 API controller root."""

    commands = command.CommandController()
    status = status.StatusController()

    @wsme_pecan.wsexpose(V1)
    def get(self):
        # NOTE: The reason why convert() it's being called for every
        #       request is because we need to get the host url from
        #       the request object to make the links.
        return V1.convert()

__all__ = (Controller)

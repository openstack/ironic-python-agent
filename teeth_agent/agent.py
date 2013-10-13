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

from teeth_agent.client import TeethClient
from teeth_agent.logging import get_logger
from teeth_agent.protocol import require_parameters, CommandValidationError
from teeth_agent.task import PrepareImageTask
log = get_logger()


class StandbyAgent(TeethClient):
    """
    Agent to perform standbye operations.
    """

    AGENT_MODE = 'STANDBY'

    def __init__(self, addrs):
        super(StandbyAgent, self).__init__(addrs)
        self._add_handler('v1', 'standby.cache_images', self.cache_images)
        self._add_handler('v1', 'standby.prepare_image', self.prepare_image)
        self._add_handler('v1', 'standby.run_image', self.run_image)
        log.msg('Starting agent', addrs=addrs)

    @require_parameters('task_id', 'image_ids')
    def cache_images(self, command):
        """
        Cache a set of images. Ordered in priority, we may only cache a
        subset depending on storage availability.
        """
        if not isinstance(command.params['image_ids'], list):
            raise CommandValidationError('"image_ids" must be a list')
        pass

    @require_parameters('task_id', 'image_id')
    def prepare_image(self, command):
        """Prepare an Image."""
        task_id = command.params['task_id']
        image_id = command.params['image_id']

        t = PrepareImageTask(self, task_id, image_id)
        t.run()

    @require_parameters('task_id', 'image_id')
    def run_image(self, command):
        """
        Run the specified image.
        """

    def update_task_status(self, task):
        """Send an updated task status to the agent endpoint."""
        pass

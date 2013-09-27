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

from twisted.application.service import MultiService
from twisted.application.internet import TimerService
from teeth_agent.logging import get_logger
log = get_logger()


__all__ = ['Task', 'PrepareImageTask']


class Task(MultiService, object):
    """
    Task to execute, reporting status periodically to TeethClient instance.
    """

    task_name = 'task_undefined'

    def __init__(self, client, task_id, task_name, reporting_interval=10):
        super(Task, self).__init__()
        self.setName(self.task_name)
        self._client = client
        self._id = task_id
        self._percent = 0
        self._reporting_interval = reporting_interval
        self._state = 'starting'
        self._timer = TimerService(self._reporting_interval, self._tick)
        self._timer.setServiceParent(self)
        self._error_msg = None

    def run(self):
        """Run the Task."""
        # setServiceParent actually starts the task if it is already running
        # so we run it in start.
        self.setServiceParent(self._client)

    def _tick(self):
        if not self.running:
            # log.debug("_tick called while not running :()")
            return
        return self._client.update_task_status(self)

    def error(self, message):
        """Error out running of the task."""
        self._error_msg = message
        self._state = 'error'
        self.stopService()

    def complete(self):
        """Complete running of the task."""
        self._state = 'complete'
        self.stopService()

    def startService(self):
        """Start the Service."""
        super(Task, self).startService()
        self._state = 'running'

    def stopService(self):
        """Stop the Service."""
        super(Task, self).stopService()

        if not self._client.running:
            return

        if self._state not in ['error', 'complete']:
            log.err("told to shutdown before task could complete, marking as error.")
            self._error_msg = 'service being shutdown'
            self._state = 'error'

        self._client.finish_task(self)


class PrepareImageTask(Task):

    """Prepare an image to be ran on the machine."""

    task_name = 'prepare_image'

    def __init__(self, client, task_id, image_info, reporting_interval=10):
        super(PrepareImageTask, self).__init__(client, task_id)
        self._image_info = image_info

    def run():
        """Run the Prepare Image task."""
        pass

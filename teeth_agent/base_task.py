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
from twisted.internet import defer
from teeth_agent.logging import get_logger

__all__ = ['BaseTask', 'MultiTask']


class BaseTask(MultiService, object):
    """
    Task to execute, reporting status periodically to TeethClient instance.
    """

    task_name = 'task_undefined'

    def __init__(self, client, task_id, reporting_interval=10):
        super(BaseTask, self).__init__()
        self.log = get_logger(task_id=task_id, task_name=self.task_name)
        self.setName(self.task_name)
        self._client = client
        self._id = task_id
        self._percent = 0
        self._reporting_interval = reporting_interval
        self._state = 'starting'
        self._timer = TimerService(self._reporting_interval, self._tick)
        self._timer.setServiceParent(self)
        self._error_msg = None
        self._done = False
        self._d = defer.Deferred()

    def _run(self):
        """Do the actual work here."""

    def run(self):
        """Run the Task."""
        # setServiceParent actually starts the task if it is already running
        # so we run it in start.
        if not self.parent:
            self.setServiceParent(self._client)
        self._run()
        return self._d

    def _tick(self):
        if not self.running:
            # log.debug("_tick called while not running :()")
            return

        if self._state in ['error', 'complete']:
            self.stopService()

        return self._client.update_task_status(self)

    def error(self, message, *args, **kwargs):
        """Error out running of the task."""
        self._error_msg = message
        self._state = 'error'
        self.stopService()

    def complete(self, *args, **kwargs):
        """Complete running of the task."""
        self._state = 'complete'
        self.stopService()

    def startService(self):
        """Start the Service."""
        self._state = 'running'
        super(BaseTask, self).startService()

    def stopService(self):
        """Stop the Service."""
        super(BaseTask, self).stopService()

        if self._state not in ['error', 'complete']:
            self.log.err("told to shutdown before task could complete, marking as error.")
            self._error_msg = 'service being shutdown'
            self._state = 'error'

        if self._done is False:
            self._done = True
            self._d.callback(None)
            self._client.finish_task(self)


class MultiTask(BaseTask):

    """Run multiple tasks in parallel."""

    def __init__(self, client, task_id, reporting_interval=10):
        super(MultiTask, self).__init__(client, task_id, reporting_interval=reporting_interval)
        self._tasks = []

    def _tick(self):
        if len(self._tasks):
            percents = [t._percent for t in self._tasks]
            self._percent = sum(percents)/float(len(percents))
        else:
            self._percent = 0
        super(MultiTask, self)._tick()

    def _run(self):
        ds = []
        for t in self._tasks:
            ds.append(t.run())
        dl = defer.DeferredList(ds)
        dl.addBoth(self.complete, self.error)

    def add_task(self, task):
        """Add a task to be ran."""
        task.setServiceParent(self)
        self._tasks.append(task)

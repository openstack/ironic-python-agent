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

import uuid

from twisted.trial import unittest
from teeth_agent.task import Task
from mock import Mock


class FakeClient(object):
    addService = Mock(return_value=None)
    running = Mock(return_value=0)
    update_task_status = Mock(return_value=None)
    finish_task = Mock(return_value=None)


class TaskTest(unittest.TestCase):
    """Event Emitter tests."""

    def setUp(self):
        self.task_id = str(uuid.uuid4())
        self.client = FakeClient()
        self.task = Task(self.client, self.task_id, 'test_task')

    def tearDown(self):
        del self.task_id
        del self.task
        del self.client

    def test_run(self):
        self.assertEqual(self.task._state, 'starting')
        self.assertEqual(self.task._id, self.task_id)
        self.task.run()
        self.client.addService.assert_called_once_with(self.task)
        self.task.startService()
        self.client.update_task_status.assert_called_once_with(self.task)
        self.task.complete()
        self.assertEqual(self.task._state, 'complete')
        self.client.finish_task.assert_called_once_with(self.task)

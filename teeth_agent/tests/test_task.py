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
from teeth_agent.base_task import BaseTask, MultiTask
from mock import Mock


class FakeClient(object):
    def __init__(self):
        self.addService = Mock(return_value=None)
        self.running = Mock(return_value=0)
        self.update_task_status = Mock(return_value=None)
        self.finish_task = Mock(return_value=None)


class TestTask(BaseTask):
    task_name = 'test_task'


class TaskTest(unittest.TestCase):
    """Basic tests of the Task API."""

    def setUp(self):
        self.task_id = str(uuid.uuid4())
        self.client = FakeClient()
        self.task = TestTask(self.client, self.task_id)

    def tearDown(self):
        del self.task_id
        del self.task
        del self.client

    def test_error(self):
        self.task.run()
        self.client.addService.assert_called_once_with(self.task)
        self.task.startService()
        self.client.update_task_status.assert_called_once_with(self.task)
        self.task.error('chaos monkey attack')
        self.assertEqual(self.task._state, 'error')
        self.client.finish_task.assert_called_once_with(self.task)

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

    def test_fast_shutdown(self):
        self.task.run()
        self.client.addService.assert_called_once_with(self.task)
        self.task.startService()
        self.client.update_task_status.assert_called_once_with(self.task)
        self.task.stopService()
        self.assertEqual(self.task._state, 'error')
        self.client.finish_task.assert_called_once_with(self.task)


class MultiTestTask(MultiTask):
    task_name = 'test_multitask'


class MultiTaskTest(unittest.TestCase):
    """Basic tests of the Multi Task API."""

    def setUp(self):
        self.task_id = str(uuid.uuid4())
        self.client = FakeClient()
        self.task = MultiTestTask(self.client, self.task_id)

    def tearDown(self):
        del self.task_id
        del self.task
        del self.client

    def test_tasks(self):
        t = TestTask(self.client, self.task_id)
        self.task.add_task(t)
        self.assertEqual(self.task._state, 'starting')
        self.assertEqual(self.task._id, self.task_id)
        self.task.run()
        self.client.addService.assert_called_once_with(self.task)
        self.task.startService()
        self.client.update_task_status.assert_any_call(self.task)
        t.complete()
        self.assertEqual(self.task._state, 'complete')
        self.client.finish_task.assert_any_call(t)
        self.client.finish_task.assert_any_call(self.task)

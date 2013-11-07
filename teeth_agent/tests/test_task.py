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
import shutil
import tempfile
import hashlib
import os

from mock import Mock, patch

from twisted.internet import defer
from twisted.trial import unittest
from twisted.web.client import ResponseDone
from twisted.python.failure import Failure

from teeth_agent.protocol import ImageInfo
from teeth_agent.base_task import BaseTask, MultiTask
from teeth_agent.cache_image import ImageDownloaderTask


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


class StubResponse(object):
    def __init__(self, code, headers, body):
        self.version = ('HTTP', 1, 1)
        self.code = code
        self.status = "ima teapot"
        self.headers = headers
        self.body = body
        self.length = reduce(lambda x, y: x + len(y), body, 0)
        self.protocol = None

    def deliverBody(self, protocol):
        self.protocol = protocol

    def run(self):
        self.protocol.connectionMade()

        for data in self.body:
            self.protocol.dataReceived(data)

        self.protocol.connectionLost(Failure(ResponseDone("Response body fully received")))


class ImageDownloaderTaskTest(unittest.TestCase):

    def setUp(self):
        get_patcher = patch('treq.get', autospec=True)
        self.TreqGet = get_patcher.start()
        self.addCleanup(get_patcher.stop)

        self.tmpdir = tempfile.mkdtemp('image_download_test')
        self.task_id = str(uuid.uuid4())
        self.image_data = str(uuid.uuid4())
        self.image_md5 = hashlib.md5(self.image_data).hexdigest()
        self.cache_path = os.path.join(self.tmpdir, 'a1234.img')
        self.client = FakeClient()
        self.image_info = ImageInfo('a1234',
                                    ['http://127.0.0.1/images/a1234.img'], {'md5': self.image_md5})
        self.task = ImageDownloaderTask(self.client,
                                        self.task_id,
                                        self.image_info,
                                        self.cache_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def assertFileHash(self, hash_type, path, value):
        file_hash = hashlib.new(hash_type)
        with open(path, 'r') as fp:
            file_hash.update(fp.read())
        self.assertEqual(value, file_hash.hexdigest())

    def test_download_success(self):
        resp = StubResponse(200, [], [self.image_data])
        d = defer.Deferred()
        self.TreqGet.return_value = d
        self.task.run()
        self.client.addService.assert_called_once_with(self.task)

        self.TreqGet.assert_called_once_with('http://127.0.0.1/images/a1234.img')

        self.task.startService()

        d.callback(resp)

        resp.run()

        self.client.update_task_status.assert_called_once_with(self.task)
        self.assertFileHash('md5', self.cache_path, self.image_md5)

        self.task.stopService()
        self.assertEqual(self.task._state, 'error')
        self.client.finish_task.assert_called_once_with(self.task)

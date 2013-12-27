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

import time
import unittest

import mock
import pkg_resources

from teeth_agent import base
from teeth_agent import errors


class TestBaseTeethAgent(unittest.TestCase):
    def setUp(self):
        self.agent = base.BaseTeethAgent('fake_host', 'fake_port', 'TEST_MODE')

    def test_get_status(self):
        started_at = time.time()
        self.agent.started_at = started_at

        status = self.agent.get_status()
        self.assertIsInstance(status, base.TeethAgentStatus)
        self.assertEqual(status.mode, 'TEST_MODE')
        self.assertEqual(status.started_at, started_at)
        self.assertEqual(status.version,
                         pkg_resources.get_distribution('teeth-agent').version)

    def test_execute_command(self):
        do_something_impl = mock.Mock()
        self.agent.command_map = {
            'do_something': do_something_impl,
        }

        self.agent.execute_command('do_something', foo='bar')
        do_something_impl.assertCalledOnceWith(foo='bar')

    def test_execute_invalid_command(self):
        self.assertRaises(errors.InvalidCommandError,
                          self.agent.execute_command,
                          'do_something',
                          foo='bar')

    @mock.patch('werkzeug.serving.run_simple')
    def test_run(self, mocked_run_simple):
        self.agent.run()
        mocked_run_simple.assert_called_once_with('fake_host',
                                                  'fake_port',
                                                  self.agent.api)

        self.assertRaises(RuntimeError, self.agent.run)

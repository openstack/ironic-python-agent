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

from twisted.trial import unittest
from teeth_agent.events import EventEmitter, EventEmitterUnhandledError


class EventEmitterTest(unittest.TestCase):
    """Event Emitter tests."""

    def setUp(self):
        self.ee = EventEmitter()

    def tearDown(self):
        del self.ee

    def test_empty_emit(self):
        self.ee.emit("nothing.here", "some args")
        self.ee.emit("nothing.here2")

    def test_single_event(self):
        self.count = 0

        def got_it(topic):
            self.assertEqual(topic, "test")
            self.count += 1

        self.ee.on("test", got_it)

        self.ee.emit("test")

        self.ee.emit("other_test")

        self.assertEqual(self.count, 1)

    def test_multicb(self):
        self.count = 0

        def got_it(topic):
            self.assertEqual(topic, "test")
            self.count += 1

        self.ee.on("test", got_it)

        self.ee.on("test", got_it)

        self.ee.emit("test")

        self.assertEqual(self.count, 2)

    def test_once(self):
        self.count = 0

        def got_it(topic):
            self.assertEqual(topic, "test")
            self.count += 1

        self.ee.once("test", got_it)

        self.ee.emit("test")

        self.ee.emit("test")

        self.assertEqual(self.count, 1)

    def test_removeAllListeners(self):
        self.count = 0

        def got_it(topic):
            self.assertEqual(topic, "test")
            self.count += 1

        self.ee.on("test", got_it)

        self.ee.emit("test")

        self.ee.removeAllListeners("test")

        self.ee.emit("test")

        self.assertEqual(self.count, 1)

    def test_error(self):
        self.count = 0

        try:
            self.ee.emit("error")
        except EventEmitterUnhandledError:
            self.count += 1
        self.assertEqual(self.count, 1)

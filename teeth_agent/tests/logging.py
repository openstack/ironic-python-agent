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

import structlog
import unittest

import teeth_agent.logging


def _return_event_processor(logger, method, event):
    return event['event']


class EventLogger(unittest.TestCase):
    def test_format_event_basic(self):
        processors = [teeth_agent.logging._format_event,
                      _return_event_processor]
        structlog.configure(processors=processors)
        log = structlog.wrap_logger(structlog.ReturnLogger())
        logged_msg = log.msg("hello {word}", word='world')
        self.assertEqual(logged_msg, "hello world")

    def test_no_format_keys(self):
        """Check that we get an exception if you don't provide enough keys to
        format a log message requiring format
        """
        processors = [teeth_agent.logging._format_event,
                      _return_event_processor]
        structlog.configure(processors=processors)
        log = structlog.wrap_logger(structlog.ReturnLogger())
        self.assertRaises(KeyError, log.msg, "hello {word}")

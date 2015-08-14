# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import unittest

import mock
from oslo_service import loopingcall

from ironic_python_agent import backoff


class TestBackOffLoopingCall(unittest.TestCase):
    @mock.patch('random.gauss')
    @mock.patch('eventlet.greenthread.sleep')
    def test_exponential_backoff(self, sleep_mock, random_mock):
        def false():
            return False

        random_mock.return_value = .8

        self.assertRaises(backoff.LoopingCallTimeOut,
                          backoff.BackOffLoopingCall(false).start()
                          .wait)

        expected_times = [mock.call(1.6000000000000001),
                          mock.call(2.5600000000000005),
                          mock.call(4.096000000000001),
                          mock.call(6.5536000000000021),
                          mock.call(10.485760000000004),
                          mock.call(16.777216000000006),
                          mock.call(26.843545600000013),
                          mock.call(42.949672960000022),
                          mock.call(68.719476736000033),
                          mock.call(109.95116277760006)]
        self.assertEqual(expected_times, sleep_mock.call_args_list)

    @mock.patch('random.gauss')
    @mock.patch('eventlet.greenthread.sleep')
    def test_no_backoff(self, sleep_mock, random_mock):
        random_mock.return_value = 1
        func = mock.Mock()
        # func.side_effect
        func.side_effect = [True, True, True, loopingcall.LoopingCallDone(
            retvalue='return value')]

        retvalue = backoff.BackOffLoopingCall(func).start().wait()

        expected_times = [mock.call(1), mock.call(1), mock.call(1)]
        self.assertEqual(expected_times, sleep_mock.call_args_list)
        self.assertTrue(retvalue, 'return value')

    @mock.patch('random.gauss')
    @mock.patch('eventlet.greenthread.sleep')
    def test_no_sleep(self, sleep_mock, random_mock):
        # Any call that executes properly the first time shouldn't sleep
        random_mock.return_value = 1
        func = mock.Mock()
        # func.side_effect
        func.side_effect = loopingcall.LoopingCallDone(retvalue='return value')

        retvalue = backoff.BackOffLoopingCall(func).start().wait()
        self.assertFalse(sleep_mock.called)
        self.assertTrue(retvalue, 'return value')

    @mock.patch('random.gauss')
    @mock.patch('eventlet.greenthread.sleep')
    def test_max_interval(self, sleep_mock, random_mock):
        def false():
            return False

        random_mock.return_value = .8

        self.assertRaises(backoff.LoopingCallTimeOut,
                          backoff.BackOffLoopingCall(false).start(
                              max_interval=60)
                          .wait)

        expected_times = [mock.call(1.6000000000000001),
                          mock.call(2.5600000000000005),
                          mock.call(4.096000000000001),
                          mock.call(6.5536000000000021),
                          mock.call(10.485760000000004),
                          mock.call(16.777216000000006),
                          mock.call(26.843545600000013),
                          mock.call(42.949672960000022),
                          mock.call(60),
                          mock.call(60),
                          mock.call(60)]
        self.assertEqual(expected_times, sleep_mock.call_args_list)

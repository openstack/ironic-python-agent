# Copyright 2014 Mirantis, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time

import mock
from oslotest import base as test_base
from stevedore import enabled
from stevedore import extension

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent.extensions import flow


FLOW_INFO = [
    {"fake.sleep": {"sleep_info": {"time": 1}}},
    {"fake.sleep": {"sleep_info": {"time": 2}}},
    {"fake.sync_sleep": {"sleep_info": {"time": 3}}},
    {"fake.sleep": {"sleep_info": {"time": 4}}},
    {"fake.sync_sleep": {"sleep_info": {"time": 5}}},
    {"fake.sleep": {"sleep_info": {"time": 6}}},
    {"fake.sleep": {"sleep_info": {"time": 7}}},
]


class FakeExtension(base.BaseAgentExtension):
    @base.async_command('sleep')
    def sleep(self, sleep_info=None):
        time.sleep(sleep_info['time'])

    @base.sync_command('sync_sleep')
    def sync_sleep(self, sleep_info=None):
        time.sleep(sleep_info['time'])


class TestFlowExtension(test_base.BaseTestCase):
    def setUp(self):
        super(TestFlowExtension, self).setUp()
        self.agent_extension = flow.FlowExtension()
        self.agent_extension.ext_mgr = enabled.EnabledExtensionManager.\
            make_test_instance([extension.Extension('fake', None,
                                                    FakeExtension,
                                                    FakeExtension())])

    @mock.patch('time.sleep', autospec=True)
    def test_sleep_flow_success(self, sleep_mock):
        result = self.agent_extension.start_flow(flow=FLOW_INFO)
        result.join()
        sleep_calls = [mock.call(i) for i in range(1, 8)]
        sleep_mock.assert_has_calls(sleep_calls)

    @mock.patch('time.sleep', autospec=True)
    def test_sleep_flow_failed(self, sleep_mock):
        sleep_mock.side_effect = errors.RESTError()
        result = self.agent_extension.start_flow(flow=FLOW_INFO)
        result.join()
        self.assertEqual(base.AgentCommandStatus.FAILED, result.command_status)
        self.assertIsInstance(result.command_error,
                              errors.CommandExecutionError)

    @mock.patch('time.sleep', autospec=True)
    def test_sleep_flow_failed_on_second_command(self, sleep_mock):
        sleep_mock.side_effect = [None, Exception('foo'), None, None]
        result = self.agent_extension.start_flow(flow=FLOW_INFO[:4])
        result.join()
        self.assertEqual(base.AgentCommandStatus.FAILED, result.command_status)
        self.assertIsInstance(result.command_error,
                              errors.CommandExecutionError)
        self.assertEqual(2, sleep_mock.call_count)

    def test_validate_exts_success(self):
        flow._validate_exts(self.agent_extension, flow=FLOW_INFO)

    def test_validate_exts_failed_to_find_extension(self):
        self.agent_extension.ext_mgr.names = mock.Mock()
        self.agent_extension.ext_mgr.names.return_value = ['fake_fake']
        self.assertRaises(errors.RequestedObjectNotFoundError,
                          flow._validate_exts, self.agent_extension,
                          flow=FLOW_INFO)

    def test_validate_exts_failed_empty_command_map(self):
        fake_ext = self.agent_extension.ext_mgr['fake'].obj
        delattr(fake_ext, 'command_map')
        self.assertRaises(errors.InvalidCommandParamsError,
                          flow._validate_exts, self.agent_extension,
                          flow=FLOW_INFO)

    def test_validate_exts_failed_missing_command(self):
        fake_ext = self.agent_extension.ext_mgr['fake'].obj
        fake_ext.command_map = {'not_exist': 'fake'}
        self.assertRaises(errors.InvalidCommandParamsError,
                          flow._validate_exts, self.agent_extension,
                          flow=FLOW_INFO)

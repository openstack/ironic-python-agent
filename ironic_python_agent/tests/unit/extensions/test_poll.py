# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest import mock

from ironic_python_agent import agent
from ironic_python_agent import errors
from ironic_python_agent.extensions import poll
from ironic_python_agent import hardware
from ironic_python_agent.tests.unit import base


class TestPollExtension(base.IronicAgentTest):
    def setUp(self):
        super(TestPollExtension, self).setUp()
        self.mock_agent = mock.Mock(spec=agent.IronicPythonAgent)
        self.agent_extension = poll.PollExtension(agent=self.mock_agent)
        self.fake_cpu = hardware.CPU(model_name='fuzzypickles',
                                     frequency=1024,
                                     count=1,
                                     architecture='generic',
                                     flags='')

    @mock.patch.object(hardware, 'dispatch_to_managers',
                       autospec=True)
    def test_get_hardware_info_success(self, mock_dispatch):
        mock_dispatch.return_value = {'foo': 'bar'}
        result = self.agent_extension.get_hardware_info()
        mock_dispatch.assert_called_once_with('list_hardware_info')
        self.assertEqual({'foo': 'bar'}, result.command_result)
        self.assertEqual('SUCCEEDED', result.command_status)

    def test_set_node_info_success(self):
        self.mock_agent.standalone = True
        node_info = {'node': {'uuid': 'fake-node', 'properties': {}},
                     'config': {'agent_token_required': True,
                                'agent_token': 'blah' * 8}}
        result = self.agent_extension.set_node_info(node_info=node_info)
        self.mock_agent.process_lookup_data.assert_called_once_with(node_info)
        self.assertEqual('SUCCEEDED', result.command_status)

    def test_set_node_info_not_standalone(self):
        self.mock_agent.standalone = False
        node_info = {'node': {'uuid': 'fake-node', 'properties': {}},
                     'config': {'agent_token_required': True,
                                'agent_token': 'blah' * 8}}
        self.assertRaises(errors.InvalidCommandError,
                          self.agent_extension.set_node_info,
                          node_info=node_info)
        self.assertFalse(self.mock_agent.process_lookup_data.called)

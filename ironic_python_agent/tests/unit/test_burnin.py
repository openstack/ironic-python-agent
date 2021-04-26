#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from unittest import mock

from ironic_lib import utils
from oslo_concurrency import processutils

from ironic_python_agent import burnin
from ironic_python_agent import errors
from ironic_python_agent.tests.unit import base


@mock.patch.object(utils, 'execute', autospec=True)
class TestBurnin(base.IronicAgentTest):

    def test_stress_ng_cpu_default(self, mock_execute):

        node = {'driver_info': {}}
        mock_execute.return_value = (['out', 'err'])

        burnin.stress_ng_cpu(node)

        mock_execute.assert_called_once_with(
            'stress-ng', '--cpu', 0, '--timeout', 86400, '--metrics-brief')

    def test_stress_ng_cpu_non_default(self, mock_execute):

        node = {'driver_info': {'agent_burnin_cpu_cpu': 3,
                                'agent_burnin_cpu_timeout': 2911}}
        mock_execute.return_value = (['out', 'err'])

        burnin.stress_ng_cpu(node)

        mock_execute.assert_called_once_with(
            'stress-ng', '--cpu', 3, '--timeout', 2911, '--metrics-brief')

    def test_stress_ng_cpu_no_stress_ng(self, mock_execute):

        node = {'driver_info': {}}
        mock_execute.side_effect = (['out', 'err'],
                                    processutils.ProcessExecutionError())

        burnin.stress_ng_cpu(node)

        self.assertRaises(errors.CommandExecutionError,
                          burnin.stress_ng_cpu, node)

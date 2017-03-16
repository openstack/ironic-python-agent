# Copyright 2016 Red Hat, Inc.
# All Rights Reserved.
#
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

import mock
from oslotest import base as test_base

from ironic_python_agent.extensions import log
from ironic_python_agent import utils


class TestLogExtension(test_base.BaseTestCase):

    def setUp(self):
        super(TestLogExtension, self).setUp()
        self.agent_extension = log.LogExtension()

    @mock.patch.object(utils, 'collect_system_logs', autospec=True)
    def test_collect_system_logs(self, mock_collect):
        ret = 'Squidward Tentacles'
        mock_collect.return_value = ret

        cmd_result = self.agent_extension.collect_system_logs()
        serialized_cmd_result = cmd_result.serialize()
        expected_ret = {'system_logs': ret}
        self.assertEqual(expected_ret, serialized_cmd_result['command_result'])

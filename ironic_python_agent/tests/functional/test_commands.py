# Copyright 2015 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import requests

from ironic_python_agent.tests.functional import base


class TestCommands(base.FunctionalBase):
    def test_empty_commands(self):
        commands = requests.get('http://localhost:%s/v1/commands' %
                os.environ.get('TEST_PORT', '9999'))
        self.assertEqual(200, commands.status_code)
        self.assertEqual({'commands': []}, commands.json())

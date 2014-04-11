# Copyright 2013 Rackspace, Inc.
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

from oslotest import base as test_base

from ironic_python_agent.extensions import decom


class TestDecomExtension(test_base.BaseTestCase):
    def setUp(self):
        super(TestDecomExtension, self).setUp()
        self.agent_extension = decom.DecomExtension()

    def test_decom_extension(self):
        self.assertEqual(self.agent_extension.name, 'DECOM')

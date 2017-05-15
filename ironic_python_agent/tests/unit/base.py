# Copyright 2017 Cisco Systems, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Common utilities and classes across all unit tests."""

import mock

from oslotest import base as test_base

from ironic_python_agent import utils


class IronicAgentTest(test_base.BaseTestCase):
    """Extends the base test to provide common features across agent tests."""

    def setUp(self):
        super(IronicAgentTest, self).setUp()
        """Add a blanket ban on running external processes via utils.execute().

        `self` will grow a property  called _exec_patch which is the Mock
        that replaces utils.execute.

        If the mock is called, an exception is raised to warn the tester.
        """
        # NOTE(bigjools): Not using a decorator on tests because I don't
        # want to force every test method to accept a new arg. Instead, they
        # can override or examine this self._exec_patch Mock as needed.
        self._exec_patch = mock.Mock()
        self._exec_patch.side_effect = Exception(
            "Don't call utils.execute in tests!")
        self.patch(utils, 'execute', self._exec_patch)

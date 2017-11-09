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

import subprocess

import ironic_lib
import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslotest import base as test_base

from ironic_python_agent import utils

CONF = cfg.CONF


class IronicAgentTest(test_base.BaseTestCase):
    """Extends the base test to provide common features across agent tests."""

    # By default block execution of utils.execute() and related functions.
    block_execute = True

    def setUp(self):
        super(IronicAgentTest, self).setUp()
        """Ban running external processes via 'execute' like functions

        `self` will grow a property  called _exec_patch which is the Mock
        that replaces all the 'execute' related functions.

        If the mock is called, an exception is raised to warn the tester.
        """
        self._set_config()
        # NOTE(bigjools): Not using a decorator on tests because I don't
        # want to force every test method to accept a new arg. Instead, they
        # can override or examine this self._exec_patch Mock as needed.
        if self.block_execute:
            self._exec_patch = mock.Mock()
            self._exec_patch.side_effect = Exception(
                "Don't call ironic_lib.utils.execute() / "
                "processutils.execute() or similar functions in tests!")

            # NOTE(jlvillal): pyudev.Context() calls ctypes.find_library()
            # which calls subprocess.Popen(). So not blocking
            # subprocess.Popen()
            self.patch(ironic_lib.utils, 'execute', self._exec_patch)
            self.patch(processutils, 'execute', self._exec_patch)
            self.patch(subprocess, 'call', self._exec_patch)
            self.patch(subprocess, 'check_call', self._exec_patch)
            self.patch(subprocess, 'check_output', self._exec_patch)
            self.patch(utils, 'execute', self._exec_patch)

    def _set_config(self):
        self.cfg_fixture = self.useFixture(config_fixture.Config(CONF))

    def config(self, **kw):
        """Override config options for a test."""
        self.cfg_fixture.config(**kw)

    def set_defaults(self, **kw):
        """Set default values of config options."""
        group = kw.pop('group', None)
        for o, v in kw.items():
            self.cfg_fixture.set_default(o, v, group=group)

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
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslotest import base as test_base

from ironic_python_agent.extensions import base as ext_base
from ironic_python_agent import hardware
from ironic_python_agent import utils

CONF = cfg.CONF


class IronicAgentTest(test_base.BaseTestCase):
    """Extends the base test to provide common features across agent tests."""

    # By default block execution of utils.execute() and related functions.
    block_execute = True

    def setUp(self):
        super(IronicAgentTest, self).setUp()

        self._set_config()

        # Ban running external processes via 'execute' like functions. If the
        # patched function is called, an exception is raised to warn the
        # tester.
        if self.block_execute:
            # NOTE(jlvillal): pyudev.Context() calls ctypes.find_library()
            # which calls subprocess.Popen(). So not blocking
            # subprocess.Popen()

            # NOTE(jlvillal): Intentionally not using mock as if you mock a
            # mock it causes things to not work correctly. As doing an
            # autospec=True causes strangeness. By using a simple function we
            # can then mock it without issue.
            self.patch(ironic_lib.utils, 'execute', do_not_call)
            self.patch(processutils, 'execute', do_not_call)
            self.patch(subprocess, 'call', do_not_call)
            self.patch(subprocess, 'check_call', do_not_call)
            self.patch(subprocess, 'check_output', do_not_call)
            self.patch(utils, 'execute', do_not_call)

        ext_base._EXT_MANAGER = None
        hardware._CACHED_HW_INFO = None

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


def do_not_call(*args, **kwargs):
    """Helper function to raise an exception if it is called"""
    raise Exception(
        "Don't call ironic_lib.utils.execute() / "
        "processutils.execute() or similar functions in tests!")

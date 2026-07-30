# Copyright 2026 Red Hat, Inc.
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

from unittest import mock

from oslo_config import cfg

from ironic_python_agent import inspect as inspection
from ironic_python_agent.tests.unit import base


CONF = cfg.CONF


class TestIronicInspectionRun(base.IronicAgentTest):
    def setUp(self):
        super(TestIronicInspectionRun, self).setUp()
        CONF.set_override('inspection_callback_url', '')
        self.inspection = inspection.IronicInspection()

    @mock.patch.object(inspection.IronicInspection, '_run', autospec=True)
    def test_mdns_disabled_by_default(self, mock_run):
        # use_mdns defaults to False, so an unset callback URL must not
        # be implicitly turned into a live mDNS lookup.
        self.assertFalse(CONF.mdns.use_mdns)

        self.inspection.run()

        self.assertEqual('', CONF.inspection_callback_url)
        mock_run.assert_called_once_with(self.inspection)

    @mock.patch.object(inspection.IronicInspection, '_run', autospec=True)
    def test_mdns_used_when_enabled(self, mock_run):
        CONF.set_override('use_mdns', True, group='mdns')

        self.inspection.run()

        self.assertEqual('mdns', CONF.inspection_callback_url)
        mock_run.assert_called_once_with(self.inspection)

    @mock.patch.object(inspection.IronicInspection, '_run', autospec=True)
    def test_explicit_callback_url_untouched(self, mock_run):
        CONF.set_override('inspection_callback_url', 'http://example/foo')

        self.inspection.run()

        self.assertEqual('http://example/foo',
                         CONF.inspection_callback_url)
        mock_run.assert_called_once_with(self.inspection)

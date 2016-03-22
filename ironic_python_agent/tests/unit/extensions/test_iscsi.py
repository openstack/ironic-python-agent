# -*- coding: utf-8 -*-
#
# Copyright 2015 Red Hat, Inc.
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
import time

from oslo_concurrency import processutils
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent.extensions import iscsi
from ironic_python_agent import hardware
from ironic_python_agent import utils


@mock.patch.object(hardware, 'dispatch_to_managers')
@mock.patch.object(utils, 'execute')
@mock.patch.object(time, 'sleep', lambda *_: None)
class TestISCSIExtension(test_base.BaseTestCase):

    def setUp(self):
        super(TestISCSIExtension, self).setUp()
        self.agent_extension = iscsi.ISCSIExtension()
        self.fake_dev = '/dev/fake'
        self.fake_iqn = 'iqn-fake'

    def test_start_iscsi_target(self, mock_execute, mock_dispatch):
        mock_dispatch.return_value = self.fake_dev
        mock_execute.return_value = ('', '')
        result = self.agent_extension.start_iscsi_target(iqn=self.fake_iqn)

        expected = [mock.call('tgtd'),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode',
                              'target', '--op', 'show', attempts=10),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode',
                              'target', '--op', 'new', '--tid', '1',
                              '--targetname', self.fake_iqn),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode',
                              'logicalunit', '--op', 'new', '--tid', '1',
                              '--lun', '1', '--backing-store', self.fake_dev),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode', 'target',
                              '--op', 'bind', '--tid', '1',
                              '--initiator-address', 'ALL')]
        mock_execute.assert_has_calls(expected)
        mock_dispatch.assert_called_once_with('get_os_install_device')
        self.assertEqual({'iscsi_target_iqn': self.fake_iqn},
                          result.command_result)

    def test_start_iscsi_target_fail_wait_daemon(self, mock_execute,
                                                 mock_dispatch):
        mock_dispatch.return_value = self.fake_dev
        # side effects here:
        # - execute tgtd: stdout=='', stderr==''
        # - induce tgtadm failure while in _wait_for_scsi_daemon
        mock_execute.side_effect = [('', ''),
                                    processutils.ProcessExecutionError('blah')]
        self.assertRaises(errors.ISCSIError,
                          self.agent_extension.start_iscsi_target,
                          iqn=self.fake_iqn)
        expected = [mock.call('tgtd'),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode', 'target',
                              '--op', 'show', attempts=10)]

        mock_execute.assert_has_calls(expected)
        mock_dispatch.assert_called_once_with('get_os_install_device')

    @mock.patch.object(iscsi, '_wait_for_iscsi_daemon')
    def test_start_iscsi_target_fail_command(self, mock_wait_iscsi,
                                             mock_execute, mock_dispatch):
        mock_dispatch.return_value = self.fake_dev
        mock_execute.side_effect = [('', ''),
                                    processutils.ProcessExecutionError('blah')]
        self.assertRaises(errors.ISCSIError,
                          self.agent_extension.start_iscsi_target,
                          iqn=self.fake_iqn)

        expected = [mock.call('tgtd'),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode',
                              'target', '--op', 'new', '--tid', '1',
                              '--targetname', self.fake_iqn)]
        mock_execute.assert_has_calls(expected)
        mock_dispatch.assert_called_once_with('get_os_install_device')

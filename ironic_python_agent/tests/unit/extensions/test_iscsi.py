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

from oslo_concurrency import processutils
from oslotest import base as test_base

from ironic_lib import disk_utils
from ironic_python_agent import errors
from ironic_python_agent.extensions import iscsi
from ironic_python_agent import hardware
from ironic_python_agent import utils


class FakeAgent(object):
    def get_node_uuid(self):
        return 'my_node_uuid'


@mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
@mock.patch.object(hardware, 'dispatch_to_managers')
@mock.patch.object(utils, 'execute')
@mock.patch.object(iscsi.rtslib_fb, 'RTSRoot',
                   mock.Mock(side_effect=iscsi.rtslib_fb.RTSLibError()))
class TestISCSIExtensionTgt(test_base.BaseTestCase):

    def setUp(self):
        super(TestISCSIExtensionTgt, self).setUp()
        self.agent_extension = iscsi.ISCSIExtension(FakeAgent())
        self.fake_dev = '/dev/fake'
        self.fake_iqn = 'iqn-fake'

    def test_start_iscsi_target(self, mock_execute,
                                mock_dispatch,
                                mock_destroy):
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
        self.assertFalse(mock_destroy.called)

    def test_start_iscsi_target_with_special_port(self, mock_execute,
                                                  mock_dispatch,
                                                  mock_destroy):
        mock_dispatch.return_value = self.fake_dev
        mock_execute.return_value = ('', '')
        result = self.agent_extension.start_iscsi_target(iqn=self.fake_iqn,
                                                         portal_port=3268)

        expected = [mock.call('tgtd'),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode',
                              'target', '--op', 'show', attempts=10),
                    mock.call('tgtadm', '--lld', 'iscsi', '--mode',
                              'portal', '--op', 'new', '--param',
                              'portal=0.0.0.0:3268'),
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
                                                 mock_dispatch,
                                                 mock_destroy):
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
        self.assertFalse(mock_destroy.called)

    @mock.patch.object(iscsi, '_wait_for_tgtd')
    def test_start_iscsi_target_fail_command(self, mock_wait_iscsi,
                                             mock_execute, mock_dispatch,
                                             mock_destroy):
        mock_dispatch.return_value = self.fake_dev
        mock_execute.side_effect = [('', ''), ('', ''),
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


_ORIG_UTILS = iscsi.rtslib_fb.utils


@mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
@mock.patch.object(hardware, 'dispatch_to_managers')
# Don't mock the utils module, as it contains exceptions
@mock.patch.object(iscsi, 'rtslib_fb', utils=_ORIG_UTILS)
class TestISCSIExtensionLIO(test_base.BaseTestCase):

    def setUp(self):
        super(TestISCSIExtensionLIO, self).setUp()
        self.agent_extension = iscsi.ISCSIExtension(FakeAgent())
        self.fake_dev = '/dev/fake'
        self.fake_iqn = 'iqn-fake'

    @mock.patch('ironic_python_agent.netutils.get_wildcard_address')
    def test_start_iscsi_target(self, mock_get_wildcard_address,
                                mock_rtslib, mock_dispatch,
                                mock_destroy):
        mock_get_wildcard_address.return_value = '::'
        mock_dispatch.return_value = self.fake_dev
        result = self.agent_extension.start_iscsi_target(iqn=self.fake_iqn)

        self.assertEqual({'iscsi_target_iqn': self.fake_iqn},
                         result.command_result)
        mock_rtslib.BlockStorageObject.assert_called_once_with(
            name=self.fake_iqn, dev=self.fake_dev)
        mock_rtslib.Target.assert_called_once_with(mock.ANY, self.fake_iqn,
                                                   mode='create')
        mock_rtslib.TPG.assert_called_once_with(
            mock_rtslib.Target.return_value, mode='create')
        mock_rtslib.LUN.assert_called_once_with(
            mock_rtslib.TPG.return_value,
            storage_object=mock_rtslib.BlockStorageObject.return_value,
            lun=1)
        mock_rtslib.NetworkPortal.assert_called_once_with(
            mock_rtslib.TPG.return_value, '[::]', 3260)
        self.assertFalse(mock_destroy.called)

    @mock.patch('ironic_python_agent.netutils.get_wildcard_address')
    def test_start_iscsi_target_noipv6(self, mock_get_wildcard_address,
                                       mock_rtslib, mock_dispatch,
                                       mock_destroy):
        mock_get_wildcard_address.return_value = '0.0.0.0'
        mock_dispatch.return_value = self.fake_dev
        result = self.agent_extension.start_iscsi_target(iqn=self.fake_iqn)

        self.assertEqual({'iscsi_target_iqn': self.fake_iqn},
                         result.command_result)
        mock_rtslib.BlockStorageObject.assert_called_once_with(
            name=self.fake_iqn, dev=self.fake_dev)
        mock_rtslib.Target.assert_called_once_with(mock.ANY, self.fake_iqn,
                                                   mode='create')
        mock_rtslib.TPG.assert_called_once_with(
            mock_rtslib.Target.return_value, mode='create')
        mock_rtslib.LUN.assert_called_once_with(
            mock_rtslib.TPG.return_value,
            storage_object=mock_rtslib.BlockStorageObject.return_value,
            lun=1)
        mock_rtslib.NetworkPortal.assert_called_once_with(
            mock_rtslib.TPG.return_value, '0.0.0.0', 3260)
        self.assertFalse(mock_destroy.called)

    @mock.patch('ironic_python_agent.netutils.get_wildcard_address')
    def test_start_iscsi_target_with_special_port(self,
                                                  mock_get_wildcard_address,
                                                  mock_rtslib, mock_dispatch,
                                                  mock_destroy):
        mock_get_wildcard_address.return_value = '::'
        mock_dispatch.return_value = self.fake_dev
        result = self.agent_extension.start_iscsi_target(iqn=self.fake_iqn,
                                                         portal_port=3266)

        self.assertEqual({'iscsi_target_iqn': self.fake_iqn},
                         result.command_result)
        mock_rtslib.BlockStorageObject.assert_called_once_with(
            name=self.fake_iqn, dev=self.fake_dev)
        mock_rtslib.Target.assert_called_once_with(mock.ANY, self.fake_iqn,
                                                   mode='create')
        mock_rtslib.TPG.assert_called_once_with(
            mock_rtslib.Target.return_value, mode='create')
        mock_rtslib.LUN.assert_called_once_with(
            mock_rtslib.TPG.return_value,
            storage_object=mock_rtslib.BlockStorageObject.return_value,
            lun=1)
        mock_rtslib.NetworkPortal.assert_called_once_with(
            mock_rtslib.TPG.return_value, '[::]', 3266)

    def test_failed_to_start_iscsi(self, mock_rtslib, mock_dispatch,
                                   mock_destroy):
        mock_dispatch.return_value = self.fake_dev
        mock_rtslib.Target.side_effect = _ORIG_UTILS.RTSLibError()
        self.assertRaisesRegex(
            errors.ISCSIError, 'Failed to create a target',
            self.agent_extension.start_iscsi_target, iqn=self.fake_iqn)

    @mock.patch('ironic_python_agent.netutils.get_wildcard_address')
    def test_failed_to_bind_iscsi(self, mock_get_wildcard_address,
                                  mock_rtslib, mock_dispatch, mock_destroy):
        mock_get_wildcard_address.return_value = '::'
        mock_dispatch.return_value = self.fake_dev
        mock_rtslib.NetworkPortal.side_effect = _ORIG_UTILS.RTSLibError()
        self.assertRaisesRegex(
            errors.ISCSIError, 'Failed to publish a target',
            self.agent_extension.start_iscsi_target, iqn=self.fake_iqn,
            portal_port=None)

        mock_rtslib.BlockStorageObject.assert_called_once_with(
            name=self.fake_iqn, dev=self.fake_dev)
        mock_rtslib.Target.assert_called_once_with(mock.ANY, self.fake_iqn,
                                                   mode='create')
        mock_rtslib.TPG.assert_called_once_with(
            mock_rtslib.Target.return_value, mode='create')
        mock_rtslib.LUN.assert_called_once_with(
            mock_rtslib.TPG.return_value,
            storage_object=mock_rtslib.BlockStorageObject.return_value,
            lun=1)
        mock_rtslib.NetworkPortal.assert_called_once_with(
            mock_rtslib.TPG.return_value, '[::]', 3260)
        self.assertFalse(mock_destroy.called)

    def test_failed_to_start_iscsi_wipe_disk_metadata(self, mock_rtslib,
                                                      mock_dispatch,
                                                      mock_destroy):
        mock_dispatch.return_value = self.fake_dev
        mock_rtslib.Target.side_effect = _ORIG_UTILS.RTSLibError()
        self.assertRaisesRegex(
            errors.ISCSIError, 'Failed to create a target',
            self.agent_extension.start_iscsi_target,
            iqn=self.fake_iqn,
            wipe_disk_metadata=True)
        mock_destroy.assert_called_once_with('/dev/fake', 'my_node_uuid')


@mock.patch.object(iscsi.rtslib_fb, 'RTSRoot')
class TestISCSIExtensionCleanUp(test_base.BaseTestCase):

    def setUp(self):
        super(TestISCSIExtensionCleanUp, self).setUp()
        self.agent_extension = iscsi.ISCSIExtension()
        self.fake_dev = '/dev/fake'
        self.fake_iqn = 'iqn-fake'

    def test_lio_not_available(self, mock_rtslib):
        mock_rtslib.side_effect = IOError()
        iscsi.clean_up(self.fake_dev)

    def test_device_not_found(self, mock_rtslib):
        mock_rtslib.return_value.storage_objects = []
        iscsi.clean_up(self.fake_dev)

    def test_ok(self, mock_rtslib):
        mock_rtslib.return_value.storage_objects = [
            mock.Mock(udev_path='wrong path'),
            mock.Mock(udev_path=self.fake_dev),
            mock.Mock(udev_path='wrong path'),
        ]
        # mocks don't play well with name attribute
        for i, fake_storage in enumerate(
                mock_rtslib.return_value.storage_objects):
            fake_storage.name = 'iqn%d' % i

        mock_rtslib.return_value.targets = [
            mock.Mock(wwn='iqn0'),
            mock.Mock(wwn='iqn1'),
        ]

        iscsi.clean_up(self.fake_dev)

        for fake_storage in mock_rtslib.return_value.storage_objects:
            self.assertEqual(fake_storage.udev_path == self.fake_dev,
                             fake_storage.delete.called)
        for fake_target in mock_rtslib.return_value.targets:
            self.assertEqual(fake_target.wwn == 'iqn1',
                             fake_target.delete.called)

    def test_delete_fails(self, mock_rtslib):
        mock_rtslib.return_value.storage_objects = [
            mock.Mock(udev_path='wrong path'),
            mock.Mock(udev_path=self.fake_dev),
            mock.Mock(udev_path='wrong path'),
        ]
        # mocks don't play well with name attribute
        for i, fake_storage in enumerate(
                mock_rtslib.return_value.storage_objects):
            fake_storage.name = 'iqn%d' % i

        mock_rtslib.return_value.targets = [
            mock.Mock(wwn='iqn0'),
            mock.Mock(wwn='iqn1'),
        ]
        mock_rtslib.return_value.targets[1].delete.side_effect = (
            _ORIG_UTILS.RTSLibError())

        self.assertRaises(errors.ISCSIError, iscsi.clean_up, self.fake_dev)

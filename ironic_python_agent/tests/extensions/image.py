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
import shutil
import tempfile

from oslo_concurrency import processutils
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent.extensions import image
from ironic_python_agent import hardware
from ironic_python_agent import utils


@mock.patch.object(hardware, 'dispatch_to_managers')
@mock.patch.object(utils, 'execute')
@mock.patch.object(tempfile, 'mkdtemp', lambda *_: '/tmp/fake-dir')
@mock.patch.object(shutil, 'rmtree', lambda *_: None)
class TestImageExtension(test_base.BaseTestCase):

    def setUp(self):
        super(TestImageExtension, self).setUp()
        self.agent_extension = image.ImageExtension()
        self.fake_dev = '/dev/fake'
        self.fake_root_part = '/dev/fake2'
        self.fake_root_uuid = '11111111-2222-3333-4444-555555555555'
        self.fake_dir = '/tmp/fake-dir'

    @mock.patch.object(image, '_install_grub2')
    def test_install_bootloader(self, mock_grub2, mock_execute, mock_dispatch):
        mock_dispatch.return_value = self.fake_dev
        self.agent_extension.install_bootloader(root_uuid=self.fake_root_uuid)
        mock_dispatch.assert_called_once_with('get_os_install_device')
        mock_grub2.assert_called_once_with(self.fake_dev, self.fake_root_uuid)

    @mock.patch.object(image, '_get_root_partition')
    def test__install_grub2(self, mock_get_root, mock_execute, mock_dispatch):
        mock_get_root.return_value = self.fake_root_part
        image._install_grub2(self.fake_dev, self.fake_root_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/sys',
                              self.fake_dir + '/sys'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call(('chroot %s /bin/bash -c '
                              '"/usr/sbin/grub-install %s"' %
                              (self.fake_dir, self.fake_dev)), shell=True),
                    mock.call(('chroot %s /bin/bash -c '
                               '"/usr/sbin/grub-mkconfig -o '
                               '/boot/grub/grub.cfg"' % self.fake_dir),
                              shell=True),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mock_execute.assert_has_calls(expected)
        mock_get_root.assert_called_once_with(self.fake_dev,
                                              self.fake_root_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(image, '_get_root_partition')
    def test__install_grub2_command_fail(self, mock_get_root, mock_execute,
                                         mock_dispatch):
        mock_get_root.return_value = self.fake_root_part
        mock_execute.side_effect = processutils.ProcessExecutionError('boom')

        self.assertRaises(errors.CommandExecutionError, image._install_grub2,
                          self.fake_dev, self.fake_root_uuid)

        mock_get_root.assert_called_once_with(self.fake_dev,
                                              self.fake_root_uuid)
        self.assertFalse(mock_dispatch.called)

    def test__get_root_partition(self, mock_execute, mock_dispatch):
        lsblk_output = ('''KNAME="test" UUID="" TYPE="disk"
        KNAME="test1" UUID="256a39e3-ca3c-4fb8-9cc2-b32eec441f47" TYPE="part"
        KNAME="test2" UUID="%s" TYPE="part"''' % self.fake_root_uuid)
        mock_execute.side_effect = (None, [lsblk_output])

        root_part = image._get_root_partition(self.fake_dev,
                                              self.fake_root_uuid)
        self.assertEqual('/dev/test2', root_part)
        expected = [mock.call('partx', '-u', self.fake_dev, attempts=3,
                              delay_on_retry=True),
                    mock.call('lsblk', '-PbioKNAME,UUID,TYPE', self.fake_dev)]
        mock_execute.assert_has_calls(expected)
        self.assertFalse(mock_dispatch.called)

    def test__get_root_partition_no_device_found(self, mock_execute,
                                                 mock_dispatch):
        lsblk_output = ('''KNAME="test" UUID="" TYPE="disk"
        KNAME="test1" UUID="256a39e3-ca3c-4fb8-9cc2-b32eec441f47" TYPE="part"
        KNAME="test2" UUID="" TYPE="part"''')
        mock_execute.side_effect = (None, [lsblk_output])

        self.assertRaises(errors.DeviceNotFound,
                          image._get_root_partition, self.fake_dev,
                          self.fake_root_uuid)
        expected = [mock.call('partx', '-u', self.fake_dev, attempts=3,
                              delay_on_retry=True),
                    mock.call('lsblk', '-PbioKNAME,UUID,TYPE', self.fake_dev)]
        mock_execute.assert_has_calls(expected)
        self.assertFalse(mock_dispatch.called)

    def test__get_root_partition_command_fail(self, mock_execute,
                                              mock_dispatch):
        mock_execute.side_effect = (None,
                                    processutils.ProcessExecutionError('boom'))
        self.assertRaises(errors.CommandExecutionError,
                          image._get_root_partition, self.fake_dev,
                          self.fake_root_uuid)

        expected = [mock.call('partx', '-u', self.fake_dev, attempts=3,
                              delay_on_retry=True),
                    mock.call('lsblk', '-PbioKNAME,UUID,TYPE', self.fake_dev)]
        mock_execute.assert_has_calls(expected)
        self.assertFalse(mock_dispatch.called)

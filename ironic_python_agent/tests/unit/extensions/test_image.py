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
import os
import shutil
import tempfile

from oslo_concurrency import processutils
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent.extensions import image
from ironic_python_agent.extensions import iscsi
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
        self.fake_efi_system_part = '/dev/fake1'
        self.fake_root_part = '/dev/fake2'
        self.fake_root_uuid = '11111111-2222-3333-4444-555555555555'
        self.fake_efi_system_part_uuid = '45AB-2312'
        self.fake_dir = '/tmp/fake-dir'

    @mock.patch.object(iscsi, 'clean_up')
    @mock.patch.object(image, '_install_grub2')
    def test_install_bootloader_bios(self, mock_grub2, mock_iscsi_clean,
                                     mock_execute, mock_dispatch):
        mock_dispatch.return_value = self.fake_dev
        self.agent_extension.install_bootloader(root_uuid=self.fake_root_uuid)
        mock_dispatch.assert_called_once_with('get_os_install_device')
        mock_grub2.assert_called_once_with(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=None)
        mock_iscsi_clean.assert_called_once_with(self.fake_dev)

    @mock.patch.object(iscsi, 'clean_up')
    @mock.patch.object(image, '_install_grub2')
    def test_install_bootloader_uefi(self, mock_grub2, mock_iscsi_clean,
                                     mock_execute, mock_dispatch):
        mock_dispatch.return_value = self.fake_dev
        self.agent_extension.install_bootloader(
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid)
        mock_dispatch.assert_called_once_with('get_os_install_device')
        mock_grub2.assert_called_once_with(
            self.fake_dev,
            root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid)
        mock_iscsi_clean.assert_called_once_with(self.fake_dev)

    @mock.patch.object(os, 'environ')
    @mock.patch.object(image, '_get_partition')
    def test__install_grub2(self, mock_get_part_uuid, environ_mock,
                            mock_execute, mock_dispatch):
        mock_get_part_uuid.return_value = self.fake_root_part
        environ_mock.get.return_value = '/sbin'
        image._install_grub2(self.fake_dev, self.fake_root_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call(('chroot %s /bin/bash -c '
                              '"/usr/sbin/grub-install %s"' %
                               (self.fake_dir, self.fake_dev)), shell=True,
                              env_variables={'PATH': '/sbin:/bin'}),
                    mock.call(('chroot %s /bin/bash -c '
                               '"/usr/sbin/grub-mkconfig -o '
                               '/boot/grub/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={'PATH': '/sbin:/bin'}),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_called_once_with(self.fake_dev,
                                                   uuid=self.fake_root_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(os, 'environ')
    @mock.patch.object(os, 'makedirs')
    @mock.patch.object(image, '_get_partition')
    def test__install_grub2_uefi(self, mock_get_part_uuid, mkdir_mock,
                                 environ_mock, mock_execute,
                                 mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]
        environ_mock.get.return_value = '/sbin'

        image._install_grub2(
            self.fake_dev, root_uuid=self.fake_root_uuid,
            efi_system_part_uuid=self.fake_efi_system_part_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/bash -c '
                              '"/usr/sbin/grub-install %s"' %
                               (self.fake_dir, self.fake_dev)), shell=True,
                              env_variables={'PATH': '/sbin:/bin'}),
                    mock.call(('chroot %s /bin/bash -c '
                               '"/usr/sbin/grub-mkconfig -o '
                               '/boot/grub/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={'PATH': '/sbin:/bin'}),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/dev',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/proc',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir + '/sys',
                              attempts=3, delay_on_retry=True),
                    mock.call('umount', self.fake_dir, attempts=3,
                              delay_on_retry=True)]
        mkdir_mock.assert_called_once_with(self.fake_dir + '/boot/efi')
        mock_execute.assert_has_calls(expected)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_root_uuid)
        mock_get_part_uuid.assert_any_call(self.fake_dev,
                                           uuid=self.fake_efi_system_part_uuid)
        self.assertFalse(mock_dispatch.called)

    @mock.patch.object(os, 'environ')
    @mock.patch.object(os, 'makedirs')
    @mock.patch.object(image, '_get_partition')
    def test__install_grub2_uefi_umount_fails(
            self, mock_get_part_uuid, mkdir_mock, environ_mock, mock_execute,
            mock_dispatch):
        mock_get_part_uuid.side_effect = [self.fake_root_part,
                                          self.fake_efi_system_part]

        def umount_raise_func(*args, **kwargs):
            if args[0] == 'umount':
                raise processutils.ProcessExecutionError('error')

        mock_execute.side_effect = umount_raise_func
        environ_mock.get.return_value = '/sbin'
        self.assertRaises(errors.CommandExecutionError,
                          image._install_grub2,
                          self.fake_dev, root_uuid=self.fake_root_uuid,
                          efi_system_part_uuid=self.fake_efi_system_part_uuid)

        expected = [mock.call('mount', '/dev/fake2', self.fake_dir),
                    mock.call('mount', '-o', 'bind', '/dev',
                              self.fake_dir + '/dev'),
                    mock.call('mount', '-o', 'bind', '/proc',
                              self.fake_dir + '/proc'),
                    mock.call('mount', '-t', 'sysfs', 'none',
                              self.fake_dir + '/sys'),
                    mock.call('mount', self.fake_efi_system_part,
                              self.fake_dir + '/boot/efi'),
                    mock.call(('chroot %s /bin/bash -c '
                              '"/usr/sbin/grub-install %s"' %
                               (self.fake_dir, self.fake_dev)), shell=True,
                              env_variables={'PATH': '/sbin:/bin'}),
                    mock.call(('chroot %s /bin/bash -c '
                               '"/usr/sbin/grub-mkconfig -o '
                               '/boot/grub/grub.cfg"' % self.fake_dir),
                              shell=True,
                              env_variables={'PATH': '/sbin:/bin'}),
                    mock.call('umount', self.fake_dir + '/boot/efi',
                              attempts=3, delay_on_retry=True)]
        mock_execute.assert_has_calls(expected)

    @mock.patch.object(image, '_get_partition')
    def test__install_grub2_command_fail(self, mock_get_part_uuid,
                                         mock_execute,
                                         mock_dispatch):
        mock_get_part_uuid.return_value = self.fake_root_part
        mock_execute.side_effect = processutils.ProcessExecutionError('boom')

        self.assertRaises(errors.CommandExecutionError, image._install_grub2,
                          self.fake_dev, self.fake_root_uuid)

        mock_get_part_uuid.assert_called_once_with(self.fake_dev,
                                                   uuid=self.fake_root_uuid)
        self.assertFalse(mock_dispatch.called)

    def test__get_partition(self, mock_execute, mock_dispatch):
        lsblk_output = ('''KNAME="test" UUID="" TYPE="disk"
        KNAME="test1" UUID="256a39e3-ca3c-4fb8-9cc2-b32eec441f47" TYPE="part"
        KNAME="test2" UUID="%s" TYPE="part"''' % self.fake_root_uuid)
        mock_execute.side_effect = (None, None, [lsblk_output])

        root_part = image._get_partition(self.fake_dev, self.fake_root_uuid)
        self.assertEqual('/dev/test2', root_part)
        expected = [mock.call('partx', '-u', self.fake_dev, attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('lsblk', '-PbioKNAME,UUID,TYPE', self.fake_dev)]
        mock_execute.assert_has_calls(expected)
        self.assertFalse(mock_dispatch.called)

    def test__get_partition_no_device_found(self, mock_execute,
                                            mock_dispatch):
        lsblk_output = ('''KNAME="test" UUID="" TYPE="disk"
        KNAME="test1" UUID="256a39e3-ca3c-4fb8-9cc2-b32eec441f47" TYPE="part"
        KNAME="test2" UUID="" TYPE="part"''')
        mock_execute.side_effect = (None, None, [lsblk_output])

        self.assertRaises(errors.DeviceNotFound,
                          image._get_partition, self.fake_dev,
                          self.fake_root_uuid)
        expected = [mock.call('partx', '-u', self.fake_dev, attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('lsblk', '-PbioKNAME,UUID,TYPE', self.fake_dev)]
        mock_execute.assert_has_calls(expected)
        self.assertFalse(mock_dispatch.called)

    def test__get_partition_command_fail(self, mock_execute,
                                         mock_dispatch):
        mock_execute.side_effect = (None, None,
                                    processutils.ProcessExecutionError('boom'))
        self.assertRaises(errors.CommandExecutionError,
                          image._get_partition, self.fake_dev,
                          self.fake_root_uuid)

        expected = [mock.call('partx', '-u', self.fake_dev, attempts=3,
                              delay_on_retry=True),
                    mock.call('udevadm', 'settle'),
                    mock.call('lsblk', '-PbioKNAME,UUID,TYPE', self.fake_dev)]
        mock_execute.assert_has_calls(expected)
        self.assertFalse(mock_dispatch.called)

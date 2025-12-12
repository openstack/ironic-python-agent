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

import binascii
from collections import namedtuple
import glob
import json
import logging
import os
import re
import shutil
import socket
import stat
import time
from unittest import mock

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import units
import pyudev
from stevedore import extension

from ironic_python_agent import disk_utils
from ironic_python_agent import efi_utils
from ironic_python_agent import errors
from ironic_python_agent.extensions import base as ext_base
from ironic_python_agent import hardware
from ironic_python_agent import netutils
from ironic_python_agent import raid_utils
from ironic_python_agent.tests.unit import base
from ironic_python_agent.tests.unit.samples import hardware_samples as hws
from ironic_python_agent import utils

CONF = cfg.CONF

CONF.import_opt('disk_wait_attempts', 'ironic_python_agent.config')
CONF.import_opt('disk_wait_delay', 'ironic_python_agent.config')


BLK_DEVICE_TEMPLATE_SMALL_DEVICES = [
    hardware.BlockDevice(name='/dev/sda', model='TinyUSB Drive',
                         size=3116853504, rotational=False,
                         vendor="FooTastic", uuid="F531-BDC3",
                         serial="123", wwn="wwn0",
                         logical_sectors=512, physical_sectors=512,
                         tran='sas'),
    hardware.BlockDevice(name='/dev/sdb', model='AlmostBigEnough Drive',
                         size=4294967295, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial="456", wwn="wwn1",
                         logical_sectors=512, physical_sectors=512,
                         tran='sas'),
]

RAID_BLK_DEVICE_TEMPLATE_DEVICES = [
    hardware.BlockDevice(name='/dev/sda', model='DRIVE 0',
                         size=1765517033472, rotational=True,
                         vendor="FooTastic", uuid="",
                         serial="sda123", wwn="wwn1234",
                         logical_sectors=512, physical_sectors=512,
                         tran='sas'),
    hardware.BlockDevice(name='/dev/sdb', model='DRIVE 1',
                         size=1765517033472, rotational=True,
                         vendor="FooTastic", uuid="",
                         serial="sdb123", wwn="wwn333",
                         logical_sectors=512, physical_sectors=512,
                         tran='sas'),
    hardware.BlockDevice(name='/dev/md0', model='RAID',
                         size=1765517033470, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn="12",
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
    hardware.BlockDevice(name='/dev/md1', model='RAID',
                         size=0, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn=None,
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
]

RAID_BLK_DEVICE_TEMPLATE_DEVICES_WITH_PARTITIONS = [
    hardware.BlockDevice(name='/dev/sda', model='DRIVE 0',
                         size=1765517033472, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial="sda123", wwn="wwn_1",
                         logical_sectors=512, physical_sectors=512,
                         tran='sas'),
    hardware.BlockDevice(name='/dev/sdb', model='DRIVE 1',
                         size=1765517033472, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial="sdb123", wwn="wwn_2",
                         logical_sectors=512, physical_sectors=512,
                         tran='sas'),
    hardware.BlockDevice(name='/dev/sda1', model='DRIVE 0 - PART 0',
                         size=107479040000, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn="wwn_1",
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
    hardware.BlockDevice(name='/dev/sdb1', model='DRIVE 1 - PART 0',
                         size=107479040000, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn="wwn_2",
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
    hardware.BlockDevice(name='/dev/sda2', model='DRIVE 0 - PART 1',
                         size=1658247708670, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn="wwn_1",
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
    hardware.BlockDevice(name='/dev/sdb2', model='DRIVE 1 - PART 1',
                         size=1658247708670, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn="wwn_2",
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
    hardware.BlockDevice(name='/dev/md0', model='RAID',
                         size=107374182400, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn=None,
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
    hardware.BlockDevice(name='/dev/md1', model='RAID',
                         size=1658142851070, rotational=False,
                         vendor="FooTastic", uuid="",
                         serial=None, wwn=None,
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
]

BLK_DEVICE_TEMPLATE_PARTUUID_DEVICE = [
    hardware.BlockDevice(name='/dev/sda1', model='DRIVE 0',
                         size=107373133824, rotational=True,
                         vendor="FooTastic", uuid="987654-3210",
                         partuuid="1234-5678", serial="sda1123", wwn="k4k1",
                         logical_sectors=512, physical_sectors=512,
                         tran=None),
]


class FakeHardwareManager(hardware.HardwareManager):
    def evaluate_hardware_support(self):
        return self.support


def _create_mock_hwm(name, support):
    def set_support(self, x):
        self.support = x

    # note(JayF): This code creates a subclass of FakeHardwareManager with
    #             a unique name. Since we actually use the class name in IPA
    #             code as an identifier, we need to have a new class for each
    #             mock.
    hwm = type(name, (FakeHardwareManager,), {'_set_support': set_support})()
    hwm._set_support(support)
    return hwm


class TestHardwareManagerLoading(base.IronicAgentTest):
    def setUp(self):
        super(TestHardwareManagerLoading, self).setUp()
        # In order to use ExtensionManager.make_test_instance() without
        # creating a new only-for-test codepath, we instantiate the test
        # instance outside of the test case in setUp, where we can access
        # make_test_instance() before it gets mocked. Inside of the test case
        # we set this as the return value of the mocked constructor, so we can
        # verify that the constructor is called correctly while still using a
        # more realistic ExtensionManager
        fake_ep = mock.Mock()
        fake_ep.module_name = 'fake'
        fake_ep.attrs = ['fake attrs']
        ext1 = extension.Extension(
            'fake_generic0', fake_ep, None,
            _create_mock_hwm("fake_generic0",
                             hardware.HardwareSupport.GENERIC))
        ext2 = extension.Extension(
            'fake_mainline0', fake_ep, None,
            _create_mock_hwm("fake_mainline0",
                             hardware.HardwareSupport.MAINLINE))
        ext3 = extension.Extension(
            'fake_serviceprovider0', fake_ep, None,
            _create_mock_hwm("fake_serviceprovider0",
                             hardware.HardwareSupport.SERVICE_PROVIDER))
        # Note(JayF): Ensure these are added in an order other than priority
        #             order or else you may invalidate the entire test :)
        self.fake_ext_mgr = extension.ExtensionManager.make_test_instance([
            ext1, ext2, ext3
        ])
        self.expected_detail_response = [
            {'name': 'fake_serviceprovider0',
             'support': hardware.HardwareSupport.SERVICE_PROVIDER,
             'manager': ext3.obj},
            {'name': 'fake_mainline0',
             'support': hardware.HardwareSupport.MAINLINE,
             'manager': ext2.obj},
            {'name': 'fake_generic0',
             'support': hardware.HardwareSupport.GENERIC,
             'manager': ext1.obj},
        ]
        self.expected_get_managers_response = [ext3.obj, ext2.obj, ext1.obj]

    @mock.patch.object(hardware, '_get_extensions', autospec=True)
    def test_get_managers(self, mock_extensions):
        """Test to ensure get_managers sorts and returns a list of HWMs.

        The most meaningful part of this test is ensuring HWMs are in priority
        order, with the highest hardware support value coming earlier in the
        list of classes.
        """
        mock_extensions.return_value = self.fake_ext_mgr
        expected_names = [x.__class__.__name__
                          for x in self.expected_get_managers_response]
        actual_names = [x.__class__.__name__
                        for x in hardware.get_managers()]
        self.assertEqual(actual_names, expected_names)

    @mock.patch.object(hardware, '_get_extensions', autospec=True)
    def test_get_managers_detail(self, mock_extensions):
        """ensure get_manager_details returns a list of HWMs + metadata

        These also need to be sorted in priority order
        """
        mock_extensions.return_value = self.fake_ext_mgr
        self.assertEqual(hardware.get_managers_detail(),
                         self.expected_detail_response)


@mock.patch.object(disk_utils, 'udev_settle', lambda *_: None)
class TestGenericHardwareManager(base.IronicAgentTest):
    def setUp(self):
        super(TestGenericHardwareManager, self).setUp()
        self.hardware = hardware.GenericHardwareManager()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244',
                     'driver_internal_info': {}}
        CONF.clear_override('disk_wait_attempts')
        CONF.clear_override('disk_wait_delay')

        self.mock_get_managers = mock.patch.object(
            hardware, 'get_managers', autospec=True)
        self.get_managers = self.mock_get_managers.start()
        self.get_managers.return_value = [self.hardware]

    def test_get_clean_steps(self):
        expected_clean_steps = [
            {
                'step': 'erase_devices',
                'priority': 10,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_devices_metadata',
                'priority': 99,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_devices_express',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'erase_pstore',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'clean_uefi_nvram',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True,
                'argsinfo': mock.ANY
            },
            {
                'step': 'delete_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'create_configuration',
                'priority': 0,
                'interface': 'raid',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_cpu',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_gpu',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_disk',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_memory',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            },
            {
                'step': 'burnin_network',
                'priority': 0,
                'interface': 'deploy',
                'reboot_requested': False,
                'abortable': True
            }
        ]
        clean_steps = self.hardware.get_clean_steps(self.node, [])
        self.assertEqual(expected_clean_steps, clean_steps)

    def test_clean_steps_exist(self):
        for step in self.hardware.get_clean_steps(self.node, []):
            getattr(self.hardware, step['step'])

    def test_deploy_steps_exist(self):
        for step in self.hardware.get_deploy_steps(self.node, []):
            getattr(self.hardware, step['step'])

    def test_service_steps_exist(self):
        for step in self.hardware.get_service_steps(self.node, []):
            getattr(self.hardware, step['step'])

    @mock.patch('binascii.hexlify', autospec=True)
    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    def test_collect_lldp_data(self, mock_lldp_info, mock_hexlify):
        if_names = ['eth0', 'lo']
        mock_lldp_info.return_value = {if_names[0]: [
            (0, b''),
            (1, b'foo\x01'),
            (2, b'\x02bar')],
        }
        mock_hexlify.side_effect = [
            b'',
            b'666f6f01',
            b'02626172'
        ]
        expected_lldp_data = {
            'eth0': [
                (0, ''),
                (1, '666f6f01'),
                (2, '02626172')],
        }
        result = self.hardware.collect_lldp_data(if_names)
        self.assertIn(if_names[0], result)
        self.assertEqual(expected_lldp_data, result)

    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    def test_collect_lldp_data_netutils_exception(self, mock_lldp_info):
        if_names = ['eth0', 'lo']
        mock_lldp_info.side_effect = Exception('fake error')
        result = self.hardware.collect_lldp_data(if_names)
        expected_lldp_data = {}
        self.assertEqual(expected_lldp_data, result)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    @mock.patch('binascii.hexlify', autospec=True)
    @mock.patch('ironic_python_agent.netutils.get_lldp_info', autospec=True)
    def test_collect_lldp_data_decode_exception(self, mock_lldp_info,
                                                mock_hexlify, mock_log):
        if_names = ['eth0', 'lo']
        mock_lldp_info.return_value = {if_names[0]: [
            (0, b''),
            (1, b'foo\x01'),
            (2, b'\x02bar')],
        }
        mock_hexlify.side_effect = [
            b'',
            b'666f6f01',
            binascii.Error('fake_error')
        ]
        expected_lldp_data = {
            'eth0': [
                (0, ''),
                (1, '666f6f01')],
        }
        result = self.hardware.collect_lldp_data(if_names)
        mock_log.warning.assert_called_once()
        self.assertIn(if_names[0], result)
        self.assertEqual(expected_lldp_data, result)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bios_given_nic_name_ok(self, mock_execute):
        interface_name = 'eth0'
        mock_execute.return_value = ('em0\n', '')
        result = self.hardware.get_bios_given_nic_name(interface_name)
        self.assertEqual('em0', result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bios_given_nic_name_oserror(self, mock_execute):
        interface_name = 'eth0'
        mock_execute.side_effect = OSError()
        result = self.hardware.get_bios_given_nic_name(interface_name)
        self.assertIsNone(result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(hardware, 'LOG', autospec=True)
    def test_get_bios_given_nic_name_process_exec_err4(self, mock_log,
                                                       mock_execute):
        interface_name = 'eth0'
        mock_execute.side_effect = [
            processutils.ProcessExecutionError(exit_code=4)]

        result = self.hardware.get_bios_given_nic_name(interface_name)

        mock_log.info.assert_called_once_with(
            'The system is a virtual machine, so biosdevname utility does '
            'not provide names for virtual NICs.')
        self.assertIsNone(result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(hardware, 'LOG', autospec=True)
    def test_get_bios_given_nic_name_process_exec_err3(self, mock_log,
                                                       mock_execute):
        interface_name = 'eth0'
        mock_execute.side_effect = [
            processutils.ProcessExecutionError(exit_code=3)]

        result = self.hardware.get_bios_given_nic_name(interface_name)

        mock_log.warning.assert_called_once_with(
            'Biosdevname returned exit code %s', 3)
        self.assertIsNone(result)
        mock_execute.assert_called_once_with('biosdevname', '-i',
                                             interface_name)

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device(self, mocked_execute, mock_cached_node,
                                   mocked_listdir, mocked_readlink,
                                   mocked_mpath):
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mock_cached_node.return_value = None
        mocked_mpath.return_value = False
        mocked_execute.side_effect = [
            (hws.BLK_DEVICE_TEMPLATE, ''),
        ]
        self.assertEqual('/dev/sdb', self.hardware.get_os_install_device())
        mock_cached_node.assert_called_once_with()
        self.assertEqual(1, mocked_mpath.call_count)

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device_multipath(
            self, mocked_execute, mock_cached_node,
            mocked_listdir, mocked_readlink,
            mocked_mpath):
        mocked_mpath.return_value = True
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mock_cached_node.return_value = None
        mocked_execute.side_effect = [
            (hws.MULTIPATH_BLK_DEVICE_TEMPLATE, ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda2', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda3', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda1', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-4
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-2
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-3
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb2', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb3', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb1', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdc'),  # sdc
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdc1'),  # sdc1
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-1
        ]
        expected = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
            mock.call('multipath', '-c', '/dev/sda'),
            mock.call('multipath', '-ll', '/dev/sda'),
            mock.call('multipath', '-c', '/dev/sda2'),
            mock.call('multipath', '-ll', '/dev/sda2'),
            mock.call('multipath', '-c', '/dev/sda3'),
            mock.call('multipath', '-ll', '/dev/sda3'),
            mock.call('multipath', '-c', '/dev/sda1'),
            mock.call('multipath', '-ll', '/dev/sda1'),
            mock.call('multipath', '-c', '/dev/dm-0'),
            mock.call('multipath', '-c', '/dev/dm-4'),
            mock.call('multipath', '-c', '/dev/dm-2'),
            mock.call('multipath', '-c', '/dev/dm-3'),
            mock.call('multipath', '-c', '/dev/sdb'),
            mock.call('multipath', '-ll', '/dev/sdb'),
            mock.call('multipath', '-c', '/dev/sdb2'),
            mock.call('multipath', '-ll', '/dev/sdb2'),
            mock.call('multipath', '-c', '/dev/sdb3'),
            mock.call('multipath', '-ll', '/dev/sdb3'),
            mock.call('multipath', '-c', '/dev/sdb1'),
            mock.call('multipath', '-ll', '/dev/sdb1'),
            mock.call('multipath', '-c', '/dev/sdc'),
            mock.call('multipath', '-c', '/dev/sdc1'),
            mock.call('multipath', '-c', '/dev/dm-1'),
        ]
        self.assertEqual('/dev/dm-0', self.hardware.get_os_install_device())
        mocked_execute.assert_has_calls(expected)
        mock_cached_node.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device_not_multipath(
            self, mocked_execute, mock_cached_node,
            mocked_listdir, mocked_readlink, mocked_mpath):
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mocked_mpath.return_value = True
        hint = {'size': '>900'}
        mock_cached_node.return_value = {'properties': {'root_device': hint},
                                         'uuid': 'node1',
                                         'instance_info': {}}
        mocked_execute.side_effect = [
            (hws.MULTIPATH_BLK_DEVICE_TEMPLATE, ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda2', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda3', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sda1', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-4
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-2
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-3
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb2', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb3', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            (hws.MULTIPATH_VALID_PATH % '/dev/sdb1', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdc'),  # sdc
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdc1'),  # sdc1
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-1
        ]
        expected = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
            mock.call('multipath', '-c', '/dev/sda'),
            mock.call('multipath', '-ll', '/dev/sda'),
            mock.call('multipath', '-c', '/dev/sda2'),
            mock.call('multipath', '-ll', '/dev/sda2'),
            mock.call('multipath', '-c', '/dev/sda3'),
            mock.call('multipath', '-ll', '/dev/sda3'),
            mock.call('multipath', '-c', '/dev/sda1'),
            mock.call('multipath', '-ll', '/dev/sda1'),
            mock.call('multipath', '-c', '/dev/dm-0'),
            mock.call('multipath', '-c', '/dev/dm-4'),
            mock.call('multipath', '-c', '/dev/dm-2'),
            mock.call('multipath', '-c', '/dev/dm-3'),
            mock.call('multipath', '-c', '/dev/sdb'),
            mock.call('multipath', '-ll', '/dev/sdb'),
            mock.call('multipath', '-c', '/dev/sdb2'),
            mock.call('multipath', '-ll', '/dev/sdb2'),
            mock.call('multipath', '-c', '/dev/sdb3'),
            mock.call('multipath', '-ll', '/dev/sdb3'),
            mock.call('multipath', '-c', '/dev/sdb1'),
            mock.call('multipath', '-ll', '/dev/sdb1'),
            mock.call('multipath', '-c', '/dev/sdc'),
            mock.call('multipath', '-c', '/dev/sdc1'),
            mock.call('multipath', '-c', '/dev/dm-1'),
        ]
        self.assertEqual('/dev/sdc', self.hardware.get_os_install_device())
        mocked_execute.assert_has_calls(expected)
        mock_cached_node.assert_called_once_with()
        mocked_mpath.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device_raid(self, mocked_execute,
                                        mock_cached_node, mocked_listdir,
                                        mocked_readlink, mocked_mpath):
        # NOTE(TheJulia): The readlink and listdir mocks are just to satisfy
        # what is functionally an available path check and that information
        # is stored in the returned result for use by root device hints.
        mocked_readlink.side_effect = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mock_cached_node.return_value = None
        mocked_mpath.return_value = False
        mocked_execute.side_effect = [
            (hws.RAID_BLK_DEVICE_TEMPLATE, ''),
        ]

        # This should ideally select the smallest device and in theory raid
        # should always be smaller
        self.assertEqual('/dev/md0', self.hardware.get_os_install_device())
        expected = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
        ]

        mocked_execute.assert_has_calls(expected)
        mock_cached_node.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device_root_in_raid_config(self, mocked_execute,
                                                       mock_cached_node,
                                                       mocked_listdir,
                                                       mocked_readlink,
                                                       mocked_mpath):
        # NOTE(TheJulia): The readlink and listdir mocks are just to satisfy
        # what is functionally an available path check and that information
        # is stored in the returned result for use by root device hints.
        mocked_readlink.side_effect = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mock_cached_node.return_value = None
        mocked_mpath.return_value = False
        mocked_execute.side_effect = [
            (hws.RAID_BLK_DEVICE_TEMPLATE, ''),
        ]
        # Simulate that a raid config has "is_root_volume" set to True
        self.hardware._raid_root_device_mapping = {'/dev/md1': True}

        # This should select the raid volume with is_root_volume set to true
        self.assertEqual('/dev/md1', self.hardware.get_os_install_device())
        expected = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
        ]

        mocked_execute.assert_has_calls(expected)
        mock_cached_node.assert_called_once_with()

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_exclude_root_in_raid_config(
            self,
            mock_cached_node,
            mock_get_holder_disks,
            mock_get_component_devices,
            mock_dev):
        """Exclude RAID volume from being used as mountpoint for rootfs."""
        mock_cached_node.return_value = None
        mock_dev.return_value = \
            RAID_BLK_DEVICE_TEMPLATE_DEVICES_WITH_PARTITIONS

        # Simulate that a raid config has "is_root_volume" set to False
        self.hardware._raid_root_device_mapping = {'/dev/md0': False}

        mock_get_holder_disks.side_effect = [
            ["/dev/sda", "/dev/sdb"]
        ]
        mock_get_component_devices.side_effect = [
            ['/dev/sda1', '/dev/sdb1']
        ]

        # This should select the next smallest device (excluding md0)
        self.assertEqual('/dev/md1', self.hardware.get_os_install_device())

        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_exclude_everything_in_raid_config_spare(
            self,
            mock_cached_node,
            mock_get_holder_disks,
            mock_get_component_devices,
            mock_dev):
        """All RAID related volumes are excluded - select only remaining disk.

        All RAID volumes and related disks/partitions are excluded. So the
        only unaffected disk should be selected.
        """
        mock_cached_node.return_value = None
        mock_dev.return_value = \
            RAID_BLK_DEVICE_TEMPLATE_DEVICES_WITH_PARTITIONS + \
            [hardware.BlockDevice(name='/dev/sdc', model='Spare Disk',
             size=1765517033472, rotational=False,
             vendor="FooTastic", uuid="",
             serial="sdc123", wwn="wwn_3",
             logical_sectors=512, physical_sectors=512,
             tran='sas')]

        # Simulate that all raid volumes has "is_root_volume" set to False.
        self.hardware._raid_root_device_mapping = {'/dev/md0': False,
                                                   '/dev/md1': False}

        mock_get_holder_disks.side_effect = [
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"]
        ]
        mock_get_component_devices.side_effect = [
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sda2', '/dev/sdb2']
        ]

        expected_calls = [
            mock.call('/dev/md0'),
            mock.call('/dev/md1')
        ]

        # This should select the only unaffected disk /dev/sdc
        self.assertEqual('/dev/sdc', self.hardware.get_os_install_device())

        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)
        mock_get_holder_disks.assert_has_calls(expected_calls)
        mock_get_component_devices.assert_has_calls(expected_calls)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_exclude_everything_in_raid_config_invalid(
            self,
            mock_cached_node,
            mock_get_holder_disks,
            mock_get_component_devices,
            mock_dev):
        """Fail to find a device when all raid volumes are excluded.

           This should fail as the RAID volumes and related holder disks
           and partitions (= all devices) are excluded.
        """
        mock_cached_node.return_value = None
        mock_dev.return_value = \
            RAID_BLK_DEVICE_TEMPLATE_DEVICES_WITH_PARTITIONS

        # Simulate that all raid volumes has "is_root_volume" set to False.
        self.hardware._raid_root_device_mapping = {'/dev/md0': False,
                                                   '/dev/md1': False}

        mock_get_holder_disks.side_effect = [
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"]
        ]
        mock_get_component_devices.side_effect = [
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sda2', '/dev/sdb2']
        ]

        expected_calls = [
            mock.call('/dev/md0'),
            mock.call('/dev/md1')
        ]

        # This should fail as all devices are excluded.
        self.assertRaises(errors.DeviceNotFound,
                          self.hardware.get_os_install_device)

        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)
        mock_get_holder_disks.assert_has_calls(expected_calls)
        mock_get_component_devices.assert_has_calls(expected_calls)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_excluded_raids_with_multiple_wwns_invalid(
            self,
            mock_cached_node,
            mock_get_holder_disks,
            mock_get_component_devices,
            mock_dev):
        """All RAID related volumes are excluded - free disk is on skip list.

        All RAID volumes and related disks/partitions are excluded. There is
        a remaining disk, but it is on the skip list, so it cannot be used.
        This also tests that WWN hints can handle a list of WWNs for a device.
        """
        mock_cached_node.return_value = {
            'instance_info': {},
            'properties': {
                'skip_block_devices': [
                    {'wwn': 'wwn_3'}
                ]
            },
            'uuid': 'node1'
        }
        mock_dev.return_value = \
            RAID_BLK_DEVICE_TEMPLATE_DEVICES_WITH_PARTITIONS + \
            [hardware.BlockDevice(name='/dev/sdc', model='Spare Disk',
             size=1765517033472, rotational=False,
             vendor="FooTastic", uuid="",
             serial="sdc123", wwn=["wwn_3", "wwn_3_ext"],
             logical_sectors=512, physical_sectors=512,
             tran='sas')]

        # Simulate that all raid volumes had is_root_volume set to False.
        self.hardware._raid_root_device_mapping = {'/dev/md0': False,
                                                   '/dev/md1': False}

        mock_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb']
        ]
        mock_get_component_devices.side_effect = [
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sda2', '/dev/sdb2']
        ]

        # This should fail as all devices are excluded or in skip list.
        self.assertRaises(errors.DeviceNotFound,
                          self.hardware.get_os_install_device)

        mock_cached_node.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_os_install_device_fails(self, mocked_execute,
                                         mock_cached_node,
                                         mocked_listdir, mocked_readlink,
                                         mocked_mpath):
        """Fail to find device >=4GB w/o root device hints"""
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mocked_mpath.return_value = False
        mock_cached_node.return_value = None
        mocked_execute.return_value = (hws.BLK_DEVICE_TEMPLATE_SMALL, '')
        ex = self.assertRaises(errors.DeviceNotFound,
                               self.hardware.get_os_install_device)
        expected = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
        ]

        mocked_execute.assert_has_calls(expected)
        mocked_execute.assert_called_once_with(
            'lsblk', '-bia', '--json',
            '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
            'LOG-SEC,PHY-SEC,TRAN',
            check_exit_code=[0])
        self.assertIn(str(4 * units.Gi), ex.details)
        mock_cached_node.assert_called_once_with()
        self.assertEqual(1, mocked_mpath.call_count)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def _get_os_install_device_root_device_hints(self, hints, expected_device,
                                                 mock_cached_node, mock_dev):
        mock_cached_node.return_value = {'properties': {'root_device': hints},
                                         'uuid': 'node1',
                                         'instance_info': {}}
        model = 'fastable sd131 7'
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn=['strangewwn', 'wwn0'],
                                 wwn_with_extension='wwn0ven0',
                                 wwn_vendor_extension='ven0',
                                 serial=['wongserial', 'wrng0', 'serial0'],
                                 tran='sas'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model=model,
                                 size=10737418240,
                                 rotational=True,
                                 vendor='fake-vendor',
                                 wwn=['fake-wwn'],
                                 wwn_with_extension='fake-wwnven0',
                                 wwn_vendor_extension='ven0',
                                 serial=['fake-serial', 'serial1'],
                                 by_path='/dev/disk/by-path/1:0:0:0',
                                 tran='sas'),
            hardware.BlockDevice(name='/dev/nvme0n1',
                                 model=model,
                                 size=10737418240,
                                 rotational=False,
                                 vendor='fake-vendor',
                                 wwn=['fake-wwn'],
                                 wwn_with_extension='fake-wwnven0',
                                 wwn_vendor_extension='ven0',
                                 serial=['fake-serial', 'serial1'],
                                 by_path='',
                                 tran='nvme'),
        ]

        self.assertEqual(expected_device,
                         self.hardware.get_os_install_device())
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    def test_get_os_install_device_root_device_hints_model(self):
        self._get_os_install_device_root_device_hints(
            {'model': 'fastable sd131 7'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_wwn(self):
        self._get_os_install_device_root_device_hints(
            {'wwn': 'wwn0'}, '/dev/sda')

    def test_get_os_install_device_root_device_hints_serial(self):
        self._get_os_install_device_root_device_hints(
            {'serial': 'serial0'}, '/dev/sda')

    def test_get_os_install_device_root_device_hints_size(self):
        self._get_os_install_device_root_device_hints(
            {'size': 10}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_size_str(self):
        self._get_os_install_device_root_device_hints(
            {'size': '10'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_size_not_int(self):
        self.assertRaises(errors.DeviceNotFound,
                          self._get_os_install_device_root_device_hints,
                          {'size': 'not-int'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_vendor(self):
        self._get_os_install_device_root_device_hints(
            {'vendor': 'fake-vendor'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_name(self):
        self._get_os_install_device_root_device_hints(
            {'name': '/dev/sdb'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_rotational(self):
        for value in (True, 'true', 'on', 'y', 'yes'):
            self._get_os_install_device_root_device_hints(
                {'rotational': value}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_by_path(self):
        self._get_os_install_device_root_device_hints(
            {'by_path': '/dev/disk/by-path/1:0:0:0'}, '/dev/sdb')

    def test_get_os_install_device_root_device_hints_by_tran_sas(self):
        self._get_os_install_device_root_device_hints(
            {'tran': 'sas'}, '/dev/sda')

    def test_get_os_install_device_root_device_hints_by_tran_nvme(self):
        self._get_os_install_device_root_device_hints(
            {'tran': 'nvme'}, '/dev/nvme0n1')

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_root_device_hints_no_device_found(
            self, mock_cached_node, mock_dev):
        model = 'fastable sd131 7'
        mock_cached_node.return_value = {
            'instance_info': {},
            'properties': {
                'root_device': {
                    'model': model,
                    'wwn': 'fake-wwn',
                    'serial': 'fake-serial',
                    'vendor': 'fake-vendor',
                    'size': 10}}}
        # Model is different here
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Another Model',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='fake-vendor',
                                 wwn='fake-wwn',
                                 serial='fake-serial'),
        ]
        self.assertRaises(errors.DeviceNotFound,
                          self.hardware.get_os_install_device)
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_root_device_hints_iinfo(self,
                                                           mock_cached_node,
                                                           mock_dev):
        model = 'fastable sd131 7'
        mock_cached_node.return_value = {
            'instance_info': {'root_device': {'model': model}},
            'uuid': 'node1'
        }
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 wwn_with_extension='wwn0ven0',
                                 wwn_vendor_extension='ven0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model=model,
                                 size=10737418240,
                                 rotational=True,
                                 vendor='fake-vendor',
                                 wwn='fake-wwn',
                                 wwn_with_extension='fake-wwnven0',
                                 wwn_vendor_extension='ven0',
                                 serial='fake-serial',
                                 by_path='/dev/disk/by-path/1:0:0:0'),
        ]

        self.assertEqual('/dev/sdb', self.hardware.get_os_install_device())
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    @mock.patch.object(hardware, 'update_cached_node', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_no_root_device(self, mock_cached_node,
                                                  mock_dev,
                                                  mock_update):
        mock_cached_node.return_value = {'properties': {},
                                         'uuid': 'node1',
                                         'instance_info': {}}
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 wwn_with_extension='wwn0ven0',
                                 wwn_vendor_extension='ven0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='magical disk',
                                 size=10737418240,
                                 rotational=True,
                                 vendor='fake-vendor',
                                 wwn='fake-wwn',
                                 wwn_with_extension='fake-wwnven0',
                                 wwn_vendor_extension='ven0',
                                 serial='fake-serial',
                                 by_path='/dev/disk/by-path/1:0:0:0'),
        ]
        mock_update.return_value = {'properties': {'root_device':
                                                   {'name': '/dev/sda'}},
                                    'uuid': 'node1',
                                    'instance_info': {'magic': 'value'}}
        self.assertEqual('/dev/sda',
                         self.hardware.get_os_install_device(
                             permit_refresh=True))
        self.assertEqual(1, mock_cached_node.call_count)
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_skip_list_non_exist(
            self, mock_cached_node, mock_dev):
        mock_cached_node.return_value = {
            'instance_info': {},
            'properties': {
                'skip_block_devices': [
                    {'vendor': 'vendor that does not exist'}
                ]
            },
            'uuid': 'node1'
        }
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='vendor0',
                                 wwn='wwn0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Another Model',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='vendor1',
                                 wwn='fake-wwn',
                                 serial='fake-serial'),
        ]
        self.assertEqual('/dev/sdb',
                         self.hardware.get_os_install_device())
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_complete_skip_list(
            self, mock_cached_node, mock_dev):
        mock_cached_node.return_value = {
            'instance_info': {},
            'properties': {
                'skip_block_devices': [{'vendor': 'basic vendor'}]
            }
        }
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='basic vendor',
                                 wwn='wwn0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Another Model',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='basic vendor',
                                 wwn='fake-wwn',
                                 serial='fake-serial'),
        ]
        self.assertRaises(errors.DeviceNotFound,
                          self.hardware.get_os_install_device)
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_get_os_install_device_root_device_hints_skip_list(
            self, mock_cached_node, mock_dev):
        mock_cached_node.return_value = {
            'instance_info': {},
            'properties': {
                'root_device': {'wwn': 'fake-wwn'},
                'skip_block_devices': [{'vendor': 'fake-vendor'}]
            }
        }
        mock_dev.return_value = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 serial='serial0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Another Model',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='fake-vendor',
                                 wwn='fake-wwn',
                                 serial='fake-serial'),
        ]
        self.assertRaises(errors.DeviceNotFound,
                          self.hardware.get_os_install_device)
        mock_cached_node.assert_called_once_with()
        mock_dev.assert_called_once_with(all_serial_and_wwn=True)

    def test__get_device_info(self):
        fileobj = mock.mock_open(read_data='fake-vendor')
        with mock.patch(
                'builtins.open', fileobj, create=True) as mock_open:
            vendor = hardware._get_device_info(
                '/dev/sdfake', 'block', 'vendor')
            mock_open.assert_called_once_with(
                '/sys/class/block/sdfake/device/vendor', 'r')
            self.assertEqual('fake-vendor', vendor)

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus_max_mhz_flag_fallback(self, mocked_execute, mocked_open):
        mocked_execute.side_effect = [(hws.LSCPU_OUTPUT, '')]

        mocked_open.side_effect = [
            mock.mock_open(read_data=hws.PROC_CPUINFO_OUTPUT).return_value,
        ]

        with self.assertLogs(level='WARNING') as cm:
            cpus = self.hardware.get_cpus()
            logging.getLogger("root").warning("Test Placeholder")

        self.assertEqual('AMD EPYC 7282 16-Core Processor',
                         cpus.model_name)
        self.assertEqual('2794.748', cpus.frequency)
        self.assertEqual(8, cpus.count)
        self.assertEqual(1, cpus.socket_count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual(['fpu', 'vme', 'de', 'pse', 'tsc'], cpus.flags)

        self.assertEqual(["WARNING:root:Test Placeholder"], cm.output)

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus_max_mhz_and_flag_fallback(
        self, mocked_execute, mocked_open
    ):
        mocked_execute.side_effect = [(hws.LSCPU_OUTPUT_WITH_MAX_MHZ, '')]

        mocked_open.side_effect = [
            mock.mock_open(read_data=hws.PROC_CPUINFO_OUTPUT).return_value,
            mock.mock_open(read_data=hws.PROC_CPUINFO_OUTPUT).return_value,
        ]

        with self.assertLogs(level='WARNING') as cm:
            cpus = self.hardware.get_cpus()
            logging.getLogger("root").warning("Test Placeholder")

        self.assertEqual('Intel(R) Xeon(R) CPU E5-2609 0 @ 2.40GHz',
                         cpus.model_name)
        self.assertEqual('2400.0000', cpus.frequency)
        self.assertEqual(4, cpus.count)
        self.assertEqual(1, cpus.socket_count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual(['fpu', 'vme', 'de', 'pse'], cpus.flags)

        self.assertEqual(["WARNING:root:Test Placeholder"], cm.output)

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus_multi(self, mocked_execute, mocked_open):
        mocked_execute.side_effect = [(hws.LSCPU_OUTPUT, '')]
        mocked_open.side_effect = [
            mock.mock_open(read_data=hws.PROC_CPUINFO_OUTPUT).return_value,
        ]

        with self.assertLogs(level='WARNING') as cm:
            cpus = self.hardware.get_cpus()
            logging.getLogger("root").warning("Test Placeholder")

        clock_speeds = ["2794.748", "2794.748"]
        core_ids = [0, 1, 2, 3, 4, 5, 6, 7]

        self.assertGreater(len(cpus.cpus), 0)

        for i, cpu in enumerate(cpus.cpus):
            self.assertEqual('AMD EPYC 7282 16-Core Processor',
                             cpu.model_name)

            self.assertEqual(clock_speeds[i], cpu.frequency)
            self.assertEqual(str(core_ids[i]), cpu.core_id)

        self.assertEqual(8, cpus.count)
        self.assertEqual(1, cpus.socket_count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual(['fpu', 'vme', 'de', 'pse', 'tsc'], cpus.flags)

        self.assertEqual(["WARNING:root:Test Placeholder"], cm.output)

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus_no_flags(self, mocked_execute, mocked_open):
        mocked_execute.side_effect = [(hws.LSCPU_OUTPUT_NO_FLAGS, '')]

        mocked_open.side_effect = [
            mock.mock_open(read_data=hws.NO_PROC_FLAGS).return_value,
            mock.mock_open(read_data=hws.PROC_CPUINFO_OUTPUT).return_value,
        ]

        with self.assertLogs(level='WARNING') as cm:
            cpus = self.hardware.get_cpus()

        self.assertEqual('Intel(R) Xeon(R) CPU E5-1650 v3 @ 3.50GHz',
                         cpus.model_name)
        self.assertEqual('1794.433', cpus.frequency)
        self.assertEqual(12, cpus.count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual([], cpus.flags)

        self.assertEqual(
            ["WARNING:ironic_python_agent.hardware:No CPU flags found"],
            cm.output)

    @mock.patch("builtins.open", new_callable=mock.mock_open)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_cpus_illegal_flags(self, mocked_execute, mocked_open):
        mocked_execute.side_effect = [(hws.LSCPU_OUTPUT_NO_FLAGS, '')]
        mocked_open.side_effect = [
            mock.mock_open(read_data=hws.ILLEGAL_PROC_FLAGS).return_value,
            mock.mock_open(read_data=hws.PROC_CPUINFO_OUTPUT).return_value,
        ]

        with self.assertLogs(level='WARNING') as cm:
            cpus = self.hardware.get_cpus()

        self.assertEqual('Intel(R) Xeon(R) CPU E5-1650 v3 @ 3.50GHz',
                         cpus.model_name)
        self.assertEqual('1794.433', cpus.frequency)
        self.assertEqual(12, cpus.count)
        self.assertEqual('x86_64', cpus.architecture)
        self.assertEqual([], cpus.flags)

        # Check if the warning was logged
        self.assertEqual([
            "WARNING:ironic_python_agent.hardware:"
            "Malformed CPU flags information: I am not a flag",
            "WARNING:ironic_python_agent.hardware:No CPU flags found"],
            cm.output)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_psutil_v1(self, mocked_execute, mocked_psutil):
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_V1
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertEqual(4096, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_psutil_v2(self, mocked_execute, mocked_psutil):
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_V2
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertEqual(65536, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_psutil_bank_size(self, mocked_execute, mocked_psutil):
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_NO_MEMORY_BANK_SIZE
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertEqual(65536, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_psutil_exception_v1(self, mocked_execute,
                                            mocked_psutil):
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_V1
        mocked_psutil.side_effect = AttributeError()
        mem = self.hardware.get_memory()

        self.assertIsNone(mem.total)
        self.assertEqual(4096, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_psutil_exception_v2(self, mocked_execute,
                                            mocked_psutil):
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_V2
        mocked_psutil.side_effect = AttributeError()
        mem = self.hardware.get_memory()

        self.assertIsNone(mem.total)
        self.assertEqual(65536, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_lshw_exception(self, mocked_execute, mocked_psutil):
        mocked_execute.side_effect = OSError()
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertIsNone(mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_arm64_lshw(self, mocked_execute, mocked_psutil):
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_ARM64
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertEqual(3952, mem.physical_mb)

    @mock.patch('psutil.virtual_memory', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_memory_lshw_list(self, mocked_execute, mocked_psutil):
        mocked_psutil.return_value.total = 3952 * 1024 * 1024
        mocked_execute.return_value = (f"[{hws.LSHW_JSON_OUTPUT_V2[0]}]", "")
        mem = self.hardware.get_memory()

        self.assertEqual(3952 * 1024 * 1024, mem.total)
        self.assertEqual(65536, mem.physical_mb)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_get_system_lshw_dict', autospec=True,
                       return_value={'id': 'host'})
    @mock.patch.object(netutils, 'get_hostname', autospec=True)
    def test_list_hardware_info(self, mocked_get_hostname, mocked_lshw):
        self.hardware.list_network_interfaces = mock.Mock()
        self.hardware.list_network_interfaces.return_value = [
            hardware.NetworkInterface('eth0', '00:0c:29:8c:11:b1'),
            hardware.NetworkInterface('eth1', '00:0c:29:8c:11:b2'),
        ]

        self.hardware.get_cpus = mock.Mock()
        self.hardware.get_cpus.return_value = hardware.CPU(
            'Awesome CPU x14 9001',
            9001,
            14,
            'x86_64')

        self.hardware.get_memory = mock.Mock()
        self.hardware.get_memory.return_value = hardware.Memory(1017012)

        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        self.hardware.get_boot_info = mock.Mock()
        self.hardware.get_boot_info.return_value = hardware.BootInfo(
            current_boot_mode='bios', pxe_interface='boot:if')

        self.hardware.get_bmc_address = mock.Mock()
        self.hardware.get_bmc_mac = mock.Mock()
        self.hardware.get_bmc_v6address = mock.Mock()
        self.hardware.get_system_vendor_info = mock.Mock()

        mocked_get_hostname.return_value = 'mock_hostname'

        hardware_info = self.hardware.list_hardware_info()
        self.assertEqual(self.hardware.get_memory(), hardware_info['memory'])
        self.assertEqual(self.hardware.get_cpus(), hardware_info['cpu'])
        self.assertEqual(self.hardware.list_block_devices(),
                         hardware_info['disks'])
        self.assertEqual(self.hardware.list_network_interfaces(),
                         hardware_info['interfaces'])
        self.assertEqual(self.hardware.get_boot_info(),
                         hardware_info['boot'])
        self.assertEqual('mock_hostname', hardware_info['hostname'])
        mocked_lshw.assert_called_once_with(self.hardware)

    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_get_system_lshw_dict', autospec=True,
                       return_value={'id': 'host'})
    @mock.patch.object(netutils, 'get_hostname', autospec=True)
    def test_list_hardware_info_with_bmc_caching(
            self, mocked_get_hostname, mocked_lshw, mocked_get_node):
        """Test that BMC information is cached after first detection."""
        mocked_get_node.return_value = None  # No skip_bmc_detect flag

        # Mock all the hardware info methods
        self.hardware.list_network_interfaces = mock.Mock(return_value=[])
        self.hardware.get_cpus = mock.Mock()
        self.hardware.get_memory = mock.Mock()
        self.hardware.list_block_devices = mock.Mock(return_value=[])
        self.hardware.get_boot_info = mock.Mock()
        self.hardware.get_system_vendor_info = mock.Mock()
        mocked_get_hostname.return_value = 'mock_hostname'

        # Mock BMC methods
        self.hardware.get_bmc_address = mock.Mock(return_value='192.168.1.1')
        self.hardware.get_bmc_v6address = mock.Mock(return_value='fe80::1')
        self.hardware.get_bmc_mac = mock.Mock(return_value='aa:bb:cc:dd:ee:ff')

        # First call - should call BMC detection methods
        hardware_info1 = self.hardware.list_hardware_info()
        self.assertEqual('192.168.1.1', hardware_info1['bmc_address'])
        self.assertEqual('fe80::1', hardware_info1['bmc_v6address'])
        self.assertEqual('aa:bb:cc:dd:ee:ff', hardware_info1['bmc_mac'])

        # Verify BMC methods were called
        self.hardware.get_bmc_address.assert_called_once()
        self.hardware.get_bmc_v6address.assert_called_once()
        self.hardware.get_bmc_mac.assert_called_once()

        # Second call - should use cached values
        hardware_info2 = self.hardware.list_hardware_info()
        self.assertEqual('192.168.1.1', hardware_info2['bmc_address'])
        self.assertEqual('fe80::1', hardware_info2['bmc_v6address'])
        self.assertEqual('aa:bb:cc:dd:ee:ff', hardware_info2['bmc_mac'])

        # BMC methods should NOT be called again (still only once)
        self.hardware.get_bmc_address.assert_called_once()
        self.hardware.get_bmc_v6address.assert_called_once()
        self.hardware.get_bmc_mac.assert_called_once()

    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_get_system_lshw_dict', autospec=True,
                       return_value={'id': 'host'})
    @mock.patch.object(netutils, 'get_hostname', autospec=True)
    def test_list_hardware_info_skip_bmc_detect(
            self, mocked_get_hostname, mocked_lshw, mocked_get_node):
        """Test that BMC detection is skipped when flag is set."""
        mocked_get_node.return_value = {'skip_bmc_detect': True}

        # Mock all the hardware info methods
        self.hardware.list_network_interfaces = mock.Mock(return_value=[])
        self.hardware.get_cpus = mock.Mock()
        self.hardware.get_memory = mock.Mock()
        self.hardware.list_block_devices = mock.Mock(return_value=[])
        self.hardware.get_boot_info = mock.Mock()
        self.hardware.get_system_vendor_info = mock.Mock()
        mocked_get_hostname.return_value = 'mock_hostname'

        # Mock BMC methods - these should NOT be called
        self.hardware.get_bmc_address = mock.Mock()
        self.hardware.get_bmc_v6address = mock.Mock()
        self.hardware.get_bmc_mac = mock.Mock()

        # Call list_hardware_info
        hardware_info = self.hardware.list_hardware_info()

        # BMC info should be None
        self.assertIsNone(hardware_info['bmc_address'])
        self.assertIsNone(hardware_info['bmc_v6address'])
        self.assertNotIn('bmc_mac', hardware_info)

        # BMC detection methods should NOT have been called
        self.hardware.get_bmc_address.assert_not_called()
        self.hardware.get_bmc_v6address.assert_not_called()
        self.hardware.get_bmc_mac.assert_not_called()

    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_get_system_lshw_dict', autospec=True,
                       return_value={'id': 'host'})
    @mock.patch.object(netutils, 'get_hostname', autospec=True)
    def test_list_hardware_info_bmc_mac_unavailable(
            self, mocked_get_hostname, mocked_lshw, mocked_get_node):
        """Test BMC MAC marked unavailable when not supported."""
        mocked_get_node.return_value = None

        # Mock all the hardware info methods
        self.hardware.list_network_interfaces = mock.Mock(return_value=[])
        self.hardware.get_cpus = mock.Mock()
        self.hardware.get_memory = mock.Mock()
        self.hardware.list_block_devices = mock.Mock(return_value=[])
        self.hardware.get_boot_info = mock.Mock()
        self.hardware.get_system_vendor_info = mock.Mock()
        mocked_get_hostname.return_value = 'mock_hostname'

        # Mock BMC methods
        self.hardware.get_bmc_address = mock.Mock(return_value='192.168.1.1')
        self.hardware.get_bmc_v6address = mock.Mock(return_value='fe80::1')
        # BMC MAC raises IncompatibleHardwareMethodError
        self.hardware.get_bmc_mac = mock.Mock(
            side_effect=errors.IncompatibleHardwareMethodError)

        # First call
        hardware_info1 = self.hardware.list_hardware_info()
        self.assertEqual('192.168.1.1', hardware_info1['bmc_address'])
        self.assertEqual('fe80::1', hardware_info1['bmc_v6address'])
        self.assertNotIn('bmc_mac', hardware_info1)  # Not in output

        # Verify get_bmc_mac was called once
        self.hardware.get_bmc_mac.assert_called_once()

        # Second call - get_bmc_mac should NOT be called again
        hardware_info2 = self.hardware.list_hardware_info()
        self.assertEqual('192.168.1.1', hardware_info2['bmc_address'])
        self.assertEqual('fe80::1', hardware_info2['bmc_v6address'])
        self.assertNotIn('bmc_mac', hardware_info2)

        # Still only one call (cached as 'unavailable')
        self.hardware.get_bmc_mac.assert_called_once()

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_list_block_devices(self, list_mock):
        device = hardware.BlockDevice('/dev/hdaa', 'small', 65535, False)
        list_mock.return_value = [device]
        devices = self.hardware.list_block_devices()

        self.assertEqual([device], devices)

        list_mock.assert_called_once_with(all_serial_and_wwn=False)

    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_list_block_devices_including_partitions(self, list_mock):
        device = hardware.BlockDevice('/dev/hdaa', 'small', 65535, False)
        partition = hardware.BlockDevice('/dev/hdaa1', '', 32767, False)
        list_mock.side_effect = [[device], [partition]]
        devices = self.hardware.list_block_devices(include_partitions=True)

        self.assertEqual([device, partition], devices)

        self.assertEqual([mock.call(all_serial_and_wwn=False),
                          mock.call(block_type='part', ignore_raid=True)],
                         list_mock.call_args_list)

    @mock.patch.object(hardware.GenericHardwareManager, 'filter_device',
                       autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    def test_list_block_devices_with_filter_device(self, list_mock,
                                                   filter_mock):
        device = hardware.BlockDevice('/dev/hdaa', 'small', 65535, False)
        list_mock.return_value = [
            device,
            hardware.BlockDevice('/dev/rogue', 'fake', 42, True),
        ]
        seen_devices = set()

        def _filter(hwmgr, device_to_filter):
            self.assertIsInstance(device_to_filter, hardware.BlockDevice)
            seen_devices.add(device_to_filter.name)
            if 'rogue' in device_to_filter.name:
                return None
            self.assertEqual(device, device_to_filter)
            return device_to_filter

        filter_mock.side_effect = _filter

        devices = self.hardware.list_block_devices()

        self.assertEqual([device], devices)
        self.assertEqual({'/dev/hdaa', '/dev/rogue'}, seen_devices)

        list_mock.assert_called_once_with(all_serial_and_wwn=False)

    def test_get_skip_list_from_node_for_disks_block_devices_with_skip_list(
            self):
        block_devices = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]
        expected_skip_list = {'/dev/sdj'}
        node = self.node

        node['properties'] = {
            'skip_block_devices': [{
                'name': '/dev/sdj'
            }]
        }

        skip_list = self.hardware.get_skip_list_from_node_for_disks(
            node, block_devices)

        self.assertEqual(expected_skip_list, skip_list)

    def test_get_skip_list_from_node_for_raids_block_devices(self):
        expected_skip_list = {'large'}
        node = self.node

        node['properties'] = {
            'skip_block_devices': [{
                'name': '/dev/sdj'
            }, {
                'volume_name': 'large'
            }]
        }

        skip_list = self.hardware.get_skip_list_from_node_for_raids(node)

        self.assertEqual(expected_skip_list, skip_list)

    def test_get_skip_list_from_node_for_disks_block_devices_no_skip_list(
            self):
        block_devices = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]
        node = self.node

        skip_list = self.hardware.get_skip_list_from_node_for_disks(
            node, block_devices)

        self.assertIsNone(skip_list)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    def test_list_block_devices_check_skip_list_with_skip_list(self,
                                                               mock_list_devs):
        mock_list_devs.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]
        device = hardware.BlockDevice('/dev/hdaa', 'small', 65535, False)
        node = self.node

        node['properties'] = {
            'skip_block_devices': [{
                'name': '/dev/sdj'
            }]
        }

        returned_devices = self.hardware.list_block_devices_check_skip_list(
            node)

        self.assertEqual([device], returned_devices)

        mock_list_devs.assert_called_once_with(self.hardware,
                                               include_partitions=False,
                                               all_serial_and_wwn=False)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    def test_list_block_devices_check_skip_list_no_skip_list(self,
                                                             mock_list_devs):
        devices = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        mock_list_devs.return_value = devices

        returned_devices = self.hardware.list_block_devices_check_skip_list(
            self.node)

        self.assertEqual(devices, returned_devices)

        mock_list_devs.assert_called_once_with(self.hardware,
                                               include_partitions=False,
                                               all_serial_and_wwn=False)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    def test_list_block_devices_check_skip_list_with_skip_list_non_exist(
            self, mock_list_devs):
        devices = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        node = self.node

        node['properties'] = {
            'skip_block_devices': [{
                'name': '/this/device/does/not/exist'
            }]
        }

        mock_list_devs.return_value = devices

        returned_devices = self.hardware.list_block_devices_check_skip_list(
            self.node)

        self.assertEqual(devices, returned_devices)

        mock_list_devs.assert_called_once_with(self.hardware,
                                               include_partitions=False,
                                               all_serial_and_wwn=False)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    def test_list_block_devices_check_skip_list_with_complete_skip_list(
            self, mock_list_devs):
        mock_list_devs.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        node = self.node

        node['properties'] = {
            'skip_block_devices': [{
                'name': '/dev/sdj'
            }, {
                'name': '/dev/hdaa'
            }]
        }

        returned_devices = self.hardware.list_block_devices_check_skip_list(
            self.node)

        self.assertEqual([], returned_devices)

        mock_list_devs.assert_called_once_with(self.hardware,
                                               include_partitions=False,
                                               all_serial_and_wwn=False)

    @mock.patch.object(hardware, 'get_multipath_status', lambda *_: True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Devices, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device(self, mocked_execute, mocked_udev,
                                   mocked_dev_vendor, mock_listdir,
                                   mock_readlink):
        by_path_map = {
            '/dev/disk/by-path/1:0:0:0': '../../dev/sda',
            '/dev/disk/by-path/1:0:0:1': '../../dev/sdb',
            '/dev/disk/by-path/1:0:0:2': '../../dev/sdc',
            # pretend that the by-path link to ../../dev/sdd is missing
        }
        mock_readlink.side_effect = lambda x, m=by_path_map: m[x]
        mock_listdir.return_value = [os.path.basename(x)
                                     for x in sorted(by_path_map)]
        mocked_execute.side_effect = [
            (hws.BLK_DEVICE_TEMPLATE, ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdc'),
            # Pretend sdd is a multipath device... because why not.
            (hws.MULTIPATH_VALID_PATH % '/dev/sdd', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # loop0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # zram0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram1
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram2
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram3
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdf'),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-0
        ]
        mocked_udev.side_effect = [pyudev.DeviceNotFoundByFileError(),
                                   pyudev.DeviceNotFoundByNumberError('block',
                                                                      1234),
                                   pyudev.DeviceNotFoundByFileError(),
                                   pyudev.DeviceNotFoundByFileError()]
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:0',
                                 serial='sda123',
                                 wwn='wwn0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:1',
                                 serial='sdb123',
                                 wwn='wwn1'),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:2',
                                 serial='sdc123',
                                 wwn='wwn2'),
            hardware.BlockDevice(name='/dev/dm-0',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 wwn=None),
        ]

        self.assertEqual(4, len(devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'vendor', 'serial', 'hctl']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))
        expected_calls = [mock.call('/sys/block/%s/device/scsi_device' % dev)
                          for dev in ('sda', 'sdb', 'sdc', 'dm-0')]
        mock_listdir.assert_has_calls(expected_calls)

        expected_calls = [mock.call('/dev/disk/by-path/1:0:0:%d' % dev)
                          for dev in range(3)]
        mock_readlink.assert_has_calls(expected_calls)
        expected_calls = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
            mock.call('multipath', '-c', '/dev/sda'),
            mock.call('multipath', '-c', '/dev/sdb'),
            mock.call('multipath', '-c', '/dev/sdc'),
            mock.call('multipath', '-c', '/dev/sdd'),
            mock.call('multipath', '-ll', '/dev/sdd'),
            mock.call('multipath', '-c', '/dev/loop0'),
            mock.call('multipath', '-c', '/dev/zram0'),
            mock.call('multipath', '-c', '/dev/ram0'),
            mock.call('multipath', '-c', '/dev/ram1'),
            mock.call('multipath', '-c', '/dev/ram2'),
            mock.call('multipath', '-c', '/dev/ram3'),
            mock.call('multipath', '-c', '/dev/sdf'),
            mock.call('multipath', '-c', '/dev/dm-0')
        ]
        mocked_execute.assert_has_calls(expected_calls)

    @mock.patch.object(hardware, 'get_multipath_status', lambda *_: True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Devices, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device_all_serial(self, mocked_execute,
                                              mocked_udev, mocked_dev_vendor,
                                              mock_listdir, mock_readlink):
        by_path_map = {
            '/dev/disk/by-path/1:0:0:0': '../../dev/sda',
            '/dev/disk/by-path/1:0:0:1': '../../dev/sdb',
            '/dev/disk/by-path/1:0:0:2': '../../dev/sdc',
            # pretend that the by-path link to ../../dev/sdd is missing
        }
        mock_readlink.side_effect = lambda x, m=by_path_map: m[x]
        mock_listdir.return_value = [os.path.basename(x)
                                     for x in sorted(by_path_map)]
        mocked_execute.side_effect = [
            (hws.BLK_DEVICE_TEMPLATE, ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdc'),
            # Pretend sdd is a multipath device... because why not.
            (hws.MULTIPATH_VALID_PATH % '/dev/sdd', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # loop0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # zram0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram1
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram2
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram3
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdf'),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-0
        ]
        mocked_udev.side_effect = [
            {'ID_WWN': 'badwwn%d' % i, 'ID_SERIAL_SHORT': 'badserial%d' % i,
             'ID_SERIAL': 'longserial%d' % i,
             'ID_WWN_WITH_EXTENSION': 'wwn-ext%d' % i,
             'ID_WWN_VENDOR_EXTENSION': 'wwn-vendor-ext%d' % i}
            for i in range(3)
        ] + [
            {'DM_WWN': 'wwn3', 'DM_SERIAL': 'serial3'}
        ]
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices(all_serial_and_wwn=True)
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:0',
                                 serial=['sda123', 'badserial0',
                                         'longserial0'],
                                 wwn=['wwn0', 'badwwn0']),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:1',
                                 serial=['sdb123', 'badserial1',
                                         'longserial1'],
                                 wwn=['wwn1', 'badwwn1']),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 by_path='/dev/disk/by-path/1:0:0:2',
                                 serial=['sdc123', 'badserial2',
                                         'longserial2'],
                                 wwn=['wwn2', 'badwwn2']),
            hardware.BlockDevice(name='/dev/dm-0',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 hctl='1:0:0:0',
                                 wwn=[None, 'wwn3'],
                                 serial=[None, None, 'serial3']),
        ]

        self.assertEqual(4, len(devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'vendor', 'serial', 'hctl']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))
        expected_calls = [mock.call('/sys/block/%s/device/scsi_device' % dev)
                          for dev in ('sda', 'sdb', 'sdc', 'dm-0')]
        mock_listdir.assert_has_calls(expected_calls)

        expected_calls = [mock.call('/dev/disk/by-path/1:0:0:%d' % dev)
                          for dev in range(3)]
        mock_readlink.assert_has_calls(expected_calls)
        expected_calls = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
            mock.call('multipath', '-c', '/dev/sda'),
            mock.call('multipath', '-c', '/dev/sdb'),
            mock.call('multipath', '-c', '/dev/sdc'),
            mock.call('multipath', '-c', '/dev/sdd'),
            mock.call('multipath', '-ll', '/dev/sdd'),
            mock.call('multipath', '-c', '/dev/loop0'),
            mock.call('multipath', '-c', '/dev/zram0'),
            mock.call('multipath', '-c', '/dev/ram0'),
            mock.call('multipath', '-c', '/dev/ram1'),
            mock.call('multipath', '-c', '/dev/ram2'),
            mock.call('multipath', '-c', '/dev/ram3'),
            mock.call('multipath', '-c', '/dev/sdf'),
            mock.call('multipath', '-c', '/dev/dm-0')
        ]
        mocked_execute.assert_has_calls(expected_calls)

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Devices, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device_hctl_fail(self, mocked_execute, mocked_udev,
                                             mocked_dev_vendor,
                                             mocked_listdir,
                                             mocked_mpath):
        mocked_listdir.side_effect = (OSError, OSError, IndexError)
        mocked_mpath.return_value = False
        mocked_execute.return_value = (hws.BLK_DEVICE_TEMPLATE_SMALL, '')
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        self.assertEqual(2, len(devices))
        expected_calls = [
            mock.call('/dev/disk/by-path'),
            mock.call('/sys/block/sda/device/scsi_device'),
            mock.call('/sys/block/sdb/device/scsi_device')
        ]
        self.assertEqual(expected_calls, mocked_listdir.call_args_list)

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Devices, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device_with_udev(self, mocked_execute, mocked_udev,
                                             mocked_dev_vendor, mocked_listdir,
                                             mocked_readlink, mocked_mpath):
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mocked_execute.side_effect = [
            (hws.BLK_DEVICE_TEMPLATE, ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdc'),
            # Pretend sdd is a multipath device... because why not.
            (hws.MULTIPATH_VALID_PATH % '/dev/sdd', ''),
            (hws.MULTIPATH_LINKS_DM % 'dm-0', ''),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # loop0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # zram0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram1
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram2
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # ram3
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdf'),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # dm-0
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
        ]

        mocked_mpath.return_value = True
        mocked_udev.side_effect = [
            {'ID_WWN': 'wwn%d' % i, 'ID_SERIAL_SHORT': 'serial%d' % i,
             'ID_SERIAL': 'do not use me',
             'ID_WWN_WITH_EXTENSION': 'wwn-ext%d' % i,
             'ID_WWN_VENDOR_EXTENSION': 'wwn-vendor-ext%d' % i}
            for i in range(3)
        ] + [
            {'DM_WWN': 'wwn3', 'DM_SERIAL': 'serial3'}
        ]
        mocked_dev_vendor.return_value = 'Super Vendor'
        devices = hardware.list_all_block_devices()
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn0',
                                 wwn_with_extension='wwn-ext0',
                                 wwn_vendor_extension='wwn-vendor-ext0',
                                 serial='sda123',
                                 hctl='1:0:0:0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='Fastable SD131 7',
                                 size=10737418240,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn1',
                                 wwn_with_extension='wwn-ext1',
                                 wwn_vendor_extension='wwn-vendor-ext1',
                                 serial='sdb123',
                                 hctl='1:0:0:0'),
            hardware.BlockDevice(name='/dev/sdc',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn2',
                                 wwn_with_extension='wwn-ext2',
                                 wwn_vendor_extension='wwn-vendor-ext2',
                                 serial='sdc123',
                                 hctl='1:0:0:0'),
            hardware.BlockDevice(name='/dev/dm-0',
                                 model='NWD-BLP4-1600',
                                 size=1765517033472,
                                 rotational=False,
                                 vendor='Super Vendor',
                                 wwn='wwn3',
                                 wwn_with_extension=None,
                                 wwn_vendor_extension=None,
                                 serial='serial3',
                                 hctl='1:0:0:0')
        ]

        self.assertEqual(4, len(devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'vendor', 'serial', 'wwn_with_extension',
                         'wwn_vendor_extension', 'hctl']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))
        expected_calls = [mock.call('/sys/block/%s/device/scsi_device' % dev)
                          for dev in ('sda', 'sdb', 'sdc', 'dm-0')]
        mocked_listdir.assert_has_calls(expected_calls)
        mocked_mpath.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(hardware, '_get_device_info', autospec=True)
    @mock.patch.object(pyudev.Devices, 'from_device_file', autospec=False)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_list_all_block_device_with_only_udev(self,
                                                  mocked_execute,
                                                  mocked_udev,
                                                  mocked_dev_vendor,
                                                  mocked_listdir,
                                                  mocked_readlink,
                                                  mocked_mpath):
        mocked_readlink.return_value = '../../sda'
        mocked_listdir.return_value = ['1:0:0:0']
        mocked_execute.side_effect = [
            (hws.BLK_INCOMPLETE_DEVICE_TEMPLATE_SMALL, ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb'),
        ]

        mocked_mpath.return_value = True
        mocked_udev.side_effect = [
            {'ID_WWN': 'wwn%d' % i, 'ID_SERIAL_SHORT': 'serial%d' % i,
             'ID_SERIAL': 'do not use me',
             'ID_WWN_WITH_EXTENSION': 'wwn-ext%d' % i,
             'ID_WWN_VENDOR_EXTENSION': 'wwn-vendor-ext%d' % i}
            for i in range(2)
        ]
        devices = hardware.list_all_block_devices()
        expected_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='TinyUSB Drive',
                                 size=3116853504,
                                 rotational=False,
                                 wwn='wwn0',
                                 wwn_with_extension='wwn-ext0',
                                 wwn_vendor_extension='wwn-vendor-ext0',
                                 serial='serial0',
                                 hctl='1:0:0:0'),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='AlmostBigEnough Drive',
                                 size=4294967295,
                                 rotational=False,
                                 wwn='wwn1',
                                 wwn_with_extension='wwn-ext1',
                                 wwn_vendor_extension='wwn-vendor-ext1',
                                 serial='serial1',
                                 hctl='1:0:0:0')
        ]

        self.assertEqual(2, len(devices))
        for expected, device in zip(expected_devices, devices):
            # Compare all attrs of the objects
            for attr in ['name', 'model', 'size', 'rotational',
                         'wwn', 'serial', 'wwn_with_extension',
                         'wwn_vendor_extension', 'hctl']:
                self.assertEqual(getattr(expected, attr),
                                 getattr(device, attr))
        expected_calls = [mock.call('/sys/block/%s/device/scsi_device' % dev)
                          for dev in ('sda', 'sdb')]
        mocked_listdir.assert_has_calls(expected_calls)
        mocked_mpath.assert_called_once_with()

    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(hardware, 'ThreadPool', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test_erase_devices_no_parallel_by_default(self, mocked_dispatch,
                                                  mock_threadpool,
                                                  mock_safety_check):

        # NOTE(TheJulia): This test was previously more elaborate and
        # had a high failure rate on py37 and py38. So instead, lets just
        # test that the threadpool is defaulted to 1 value to ensure
        # that parallel erasures are not initiated. If the code is ever
        # modified, differently, hopefully the person editing sees this
        # message and understands the purpose is single process execution
        # by default.
        self.hardware.list_block_devices = mock.Mock()

        self.hardware.list_block_devices.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        calls = [mock.call(1)]
        self.hardware.erase_devices({}, [])
        mock_threadpool.assert_has_calls(calls)
        mock_safety_check.assert_has_calls([
            mock.call({}, '/dev/sdj'),
            mock.call({}, '/dev/hdaa')
        ])

    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(hardware, 'ThreadPool', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test_erase_devices_no_parallel_by_default_protected_device(
            self, mocked_dispatch,
            mock_threadpool,
            mock_safety_check):
        mock_safety_check.side_effect = errors.ProtectedDeviceError(
            device='foo',
            what='bar')

        self.hardware.list_block_devices = mock.Mock()

        self.hardware.list_block_devices.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        calls = [mock.call(1)]
        self.assertRaises(errors.ProtectedDeviceError,
                          self.hardware.erase_devices, {}, [])
        mock_threadpool.assert_has_calls(calls)
        mock_safety_check.assert_has_calls([
            mock.call({}, '/dev/sdj'),
        ])
        mock_threadpool.apply_async.assert_not_called()

    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch('multiprocessing.pool.ThreadPool.apply_async', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test_erase_devices_concurrency(self, mocked_dispatch, mocked_async,
                                       mock_safety_check):
        internal_info = self.node['driver_internal_info']
        internal_info['disk_erasure_concurrency'] = 10
        mocked_dispatch.return_value = 'erased device'

        apply_result = mock.Mock()
        apply_result._success = True
        apply_result._ready = True
        apply_result.get.return_value = 'erased device'
        mocked_async.return_value = apply_result

        blkdev1 = hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True)
        blkdev2 = hardware.BlockDevice('/dev/hdaa', 'small', 65535, False)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [blkdev1, blkdev2]

        expected = {'/dev/hdaa': 'erased device', '/dev/sdj': 'erased device'}

        result = self.hardware.erase_devices(self.node, [])

        calls = [mock.call(mock.ANY, mocked_dispatch, ('erase_block_device',),
                           {'node': self.node, 'block_device': dev})
                 for dev in (blkdev1, blkdev2)]
        mocked_async.assert_has_calls(calls)
        self.assertEqual(expected, result)
        mock_safety_check.assert_has_calls([
            mock.call(self.node, '/dev/sdj'),
            mock.call(self.node, '/dev/hdaa'),
        ])

    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(hardware, 'ThreadPool', autospec=True)
    def test_erase_devices_concurrency_pool_size(self, mocked_pool,
                                                 mock_safety_check):
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            hardware.BlockDevice('/dev/sdj', 'big', 1073741824, True),
            hardware.BlockDevice('/dev/hdaa', 'small', 65535, False),
        ]

        # Test pool size 10 with 2 disks
        internal_info = self.node['driver_internal_info']
        internal_info['disk_erasure_concurrency'] = 10

        self.hardware.erase_devices(self.node, [])
        mocked_pool.assert_called_with(2)

        # Test default pool size with 2 disks
        internal_info = self.node['driver_internal_info']
        del internal_info['disk_erasure_concurrency']

        self.hardware.erase_devices(self.node, [])
        mocked_pool.assert_called_with(1)
        mock_safety_check.assert_has_calls([
            mock.call(self.node, '/dev/sdj'),
            mock.call(self.node, '/dev/hdaa'),
        ])

    @mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
    def test_erase_devices_without_disk(self, mocked_dispatch):
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = []

        expected = {}
        result = self.hardware.erase_devices({}, [])
        self.assertEqual(expected, result)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_success(self, mocked_execute,
                                            mocked_ro_device,
                                            mocked_raid_member
                                            ):
        mocked_execute.side_effect = [
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            ('', ''),
            ('', ''),
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('hdparm', '--user-master', 'u', '--security-set-pass',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '--user-master', 'u', '--security-erase',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '-I', '/dev/sda'),
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_success_no_smartctl(self, mocked_execute,
                                                        mocked_ro_device,
                                                        mocked_raid_member):
        mocked_execute.side_effect = [
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
            OSError('boom'),
            ('', ''),
            ('', ''),
            (create_hdparm_info(
                supported=True, enabled=False, frozen=False,
                enhanced_erase=False), ''),
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('hdparm', '--user-master', 'u', '--security-set-pass',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '--user-master', 'u', '--security-erase',
                      'NULL', '/dev/sda'),
            mock.call('hdparm', '-I', '/dev/sda'),
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_nosecurity_shred(self, mocked_execute,
                                                 mocked_ro_device,
                                                 mocked_raid_member
                                                 ):
        hdparm_output = hws.HDPARM_INFO_TEMPLATE.split('\nSecurity:')[0]

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (hws.SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_notsupported_shred(self, mocked_execute,
                                                   mocked_ro_device,
                                                   mocked_raid_member
                                                   ):
        hdparm_output = create_hdparm_info(
            supported=False, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (hws.SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_smartctl_unsupported_shred(self,
                                                           mocked_execute,
                                                           mocked_vm_member,
                                                           mocked_ro_device,
                                                           mocked_raid_member
                                                           ):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (hws.SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_smartctl_fails_security_fallback_to_shred(
            self, mocked_execute, mocked_vm_member,
            mock_ro_device, mocked_raid_member):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            processutils.ProcessExecutionError(),
            (hws.SHRED_OUTPUT_1_ITERATION_ZERO_TRUE, '')
        ]
        mocked_raid_member.return_value = False
        mocked_vm_member.return_value = False
        mock_ro_device.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--zero', '--verbose',
                      '--iterations', '1', '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_uses_internal_info(self, mocked_execute,
                                                         mocked_ro_device,
                                                         mocked_raid_member
                                                         ):
        hdparm_output = create_hdparm_info(
            supported=False, enabled=False, frozen=False, enhanced_erase=False)

        info = self.node['driver_internal_info']
        info['agent_erase_devices_iterations'] = 2
        info['agent_erase_devices_zeroize'] = False

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            (hws.SHRED_OUTPUT_2_ITERATIONS_ZERO_FALSE, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--verbose',
                      '--iterations', '2', '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_0_pass_no_zeroize(self, mocked_execute,
                                                        mock_read_only_member,
                                                        mocked_raid_member):
        hdparm_output = create_hdparm_info(
            supported=False, enabled=False, frozen=False, enhanced_erase=False)

        info = self.node['driver_internal_info']
        info['agent_erase_devices_iterations'] = 0
        info['agent_erase_devices_zeroize'] = False

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_UNAVAILABLE_OUTPUT, ''),
            (hws.SHRED_OUTPUT_0_ITERATIONS_ZERO_FALSE, '')
        ]
        mocked_raid_member.return_value = False
        mock_read_only_member.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        mocked_execute.assert_has_calls([
            mock.call('hdparm', '-I', '/dev/sda'),
            mock.call('smartctl', '-d', 'ata', '/dev/sda', '-g', 'security',
                      check_exit_code=[0, 127]),
            mock.call('shred', '--force', '--verbose',
                      '--iterations', '0', '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    def test_erase_block_device_virtual_media(self, vm_mock):
        vm_mock.return_value = True
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.hardware.erase_block_device(self.node, block_device)
        vm_mock.assert_called_once_with(self.hardware, block_device)

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__is_virtual_media_device_exists(self, mocked_exists,
                                             mocked_link):
        mocked_exists.return_value = True
        mocked_link.return_value = '../../sda'
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._is_virtual_media_device(block_device)
        self.assertTrue(res)
        mocked_exists.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')
        mocked_link.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__is_virtual_media_device_exists_no_match(self, mocked_exists,
                                                      mocked_link):
        mocked_exists.return_value = True
        mocked_link.return_value = '../../sdb'
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._is_virtual_media_device(block_device)
        self.assertFalse(res)
        mocked_exists.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')
        mocked_link.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')

    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__is_virtual_media_device_path_doesnt_exist(self, mocked_exists,
                                                        mocked_link):
        mocked_exists.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._is_virtual_media_device(block_device)
        self.assertFalse(res)
        mocked_exists.assert_called_once_with('/dev/disk/by-label/ir-vfd-dev')
        self.assertFalse(mocked_link.called)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_fail_oserror(self, mocked_execute):
        mocked_execute.side_effect = OSError
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._shred_block_device(self.node, block_device)
        self.assertFalse(res)
        mocked_execute.assert_called_once_with(
            'shred', '--force', '--zero', '--verbose', '--iterations', '1',
            '/dev/sda')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_shred_fail_processerror(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        res = self.hardware._shred_block_device(self.node, block_device)
        self.assertFalse(res)
        mocked_execute.assert_called_once_with(
            'shred', '--force', '--zero', '--verbose', '--iterations', '1',
            '/dev/sda')

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_security_unlock_fallback_pass(
            self, mocked_execute, mocked_raid_member, mocked_vm_member,
            mocked_ro_device):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True
        )
        hdparm_output_unlocked = create_hdparm_info(
            supported=True, enabled=True, frozen=False, enhanced_erase=False)
        hdparm_output_not_enabled = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)
        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            processutils.ProcessExecutionError(),  # NULL fails to unlock
            (hdparm_output, ''),  # recheck security lines
            None,  # security unlock with ""
            (hdparm_output_unlocked, ''),
            '',
            (hdparm_output_not_enabled, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)

        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', '', '/dev/sda')

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_security_enabled(
            self, mocked_execute, mock_shred, mocked_raid_member,
            mocked_ro_device, mocked_vm_member):
        # Tests that an exception is thrown if all of the recovery passwords
        # fail to unlock the device without throwing exception
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            None,
            (hdparm_output, ''),
            None,
            (hdparm_output, ''),
            None,
            (hdparm_output, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.erase_block_device,
            self.node,
            block_device)
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', '', '/dev/sda')
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', 'NULL', '/dev/sda')
        self.assertFalse(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_security_enabled_unlock_attempt(
            self, mocked_execute, mock_shred, mocked_raid_member,
            mocked_ro_device, mocked_vm_member):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True)
        hdparm_output_not_enabled = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            '',
            (hdparm_output_not_enabled, ''),
            '',
            '',
            (hdparm_output_not_enabled, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)
        self.assertFalse(mock_shred.called)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__ata_erase_security_enabled_unlock_exception(
            self, mocked_execute):
        # test that an exception is thrown when security unlock fails with
        # ProcessExecutionError
        hdparm_output = create_hdparm_info(
            supported=True, enabled=True, locked=True)
        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            processutils.ProcessExecutionError(),
            (hdparm_output, ''),
            processutils.ProcessExecutionError(),
            (hdparm_output, ''),
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._ata_erase,
                          block_device)
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', '', '/dev/sda')
        mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                       '--security-unlock', 'NULL', '/dev/sda')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__ata_erase_security_enabled_set_password_exception(
            self, mocked_execute):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            processutils.ProcessExecutionError()
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._ata_erase,
                          block_device)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__ata_erase_security_erase_exec_exception(
            self, mocked_execute):
        # Exception on security erase
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)
        hdparm_unlocked_output = create_hdparm_info(
            supported=True, locked=True, frozen=False, enhanced_erase=False)
        mocked_execute.side_effect = [
            (hdparm_output, '', '-1'),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            '',  # security-set-pass
            processutils.ProcessExecutionError(),  # security-erase
            (hdparm_unlocked_output, '', '-1'),
            '',  # attempt security unlock
            (hdparm_output, '', '-1')
        ]

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._ata_erase,
                          block_device)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_frozen(self, mocked_execute, mock_shred,
                                           mocked_raid_member,
                                           mocked_ro_device,
                                           mocked_vm_member
                                           ):
        hdparm_output = create_hdparm_info(
            supported=True, enabled=False, frozen=True, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, '')
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)
        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.erase_block_device,
            self.node,
            block_device)
        self.assertFalse(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_failed(self, mocked_execute, mock_shred,
                                           mocked_raid_member,
                                           mocked_ro_device,
                                           mocked_vm_member
                                           ):
        hdparm_output_before = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        # If security mode remains enabled after the erase, it is indicative
        # of a failed erase.
        hdparm_output_after = create_hdparm_info(
            supported=True, enabled=True, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output_before, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            ('', ''),
            ('', ''),
            (hdparm_output_after, ''),
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.assertRaises(
            errors.IncompatibleHardwareMethodError,
            self.hardware.erase_block_device,
            self.node,
            block_device)
        self.assertFalse(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_failed_continued(
            self, mocked_execute, mock_shred, mocked_raid_member,
            mocked_ro_device, mocked_vm_member):

        info = self.node['driver_internal_info']
        info['agent_continue_if_ata_erase_failed'] = True

        hdparm_output_before = create_hdparm_info(
            supported=True, enabled=False, frozen=False, enhanced_erase=False)

        # If security mode remains enabled after the erase, it is indicative
        # of a failed erase.
        hdparm_output_after = create_hdparm_info(
            supported=True, enabled=True, frozen=False, enhanced_erase=False)

        mocked_execute.side_effect = [
            (hdparm_output_before, ''),
            (hws.SMARTCTL_NORMAL_OUTPUT, ''),
            ('', ''),
            ('', ''),
            (hdparm_output_after, ''),
        ]
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False
        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)
        self.assertTrue(mock_shred.called)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager, '_shred_block_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_ata_erase_disabled(
            self, mocked_execute, mock_shred,
            mocked_raid_member,
            mocked_ro_device, mocked_vm_member):

        info = self.node['driver_internal_info']
        info['agent_enable_ata_secure_erase'] = False
        mocked_raid_member.return_value = False
        mocked_ro_device.return_value = False
        mocked_vm_member.return_value = False

        block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                            True)

        self.hardware.erase_block_device(self.node, block_device)
        self.assertTrue(mock_shred.called)
        self.assertFalse(mocked_execute.called)

    def test_normal_vs_enhanced_security_erase(self):
        @mock.patch.object(hardware.GenericHardwareManager,
                           '_is_read_only_device', autospec=True)
        @mock.patch.object(hardware.GenericHardwareManager,
                           '_is_linux_raid_member', autospec=True)
        @mock.patch.object(utils, 'execute', autospec=True)
        def test_security_erase_option(test_case,
                                       enhanced_erase,
                                       expected_option,
                                       mocked_execute,
                                       mocked_raid_member,
                                       mocked_ro_device
                                       ):
            mocked_execute.side_effect = [
                (create_hdparm_info(
                    supported=True, enabled=False, frozen=False,
                    enhanced_erase=enhanced_erase), ''),
                (hws.SMARTCTL_NORMAL_OUTPUT, ''),
                ('', ''),
                ('', ''),
                (create_hdparm_info(
                    supported=True, enabled=False, frozen=False,
                    enhanced_erase=enhanced_erase), ''),
            ]
            mocked_raid_member.return_value = False
            mocked_ro_device.return_value = False

            block_device = hardware.BlockDevice('/dev/sda', 'big', 1073741824,
                                                True)
            test_case.hardware.erase_block_device(self.node, block_device)
            mocked_execute.assert_any_call('hdparm', '--user-master', 'u',
                                           expected_option,
                                           'NULL', '/dev/sda')

        test_security_erase_option(
            self, True, '--security-erase-enhanced')
        test_security_erase_option(
            self, False, '--security-erase')

    def test__find_pstore_mount_point(self):
        with mock.patch('builtins.open',
                        mock.mock_open(),
                        create=True) as mocked_open:
            mocked_open.return_value.__iter__ = \
                lambda self: iter(hws.PROC_MOUNTS_OUTPUT.splitlines())

            self.assertEqual(self.hardware._find_pstore_mount_point(),
                             "/sys/fs/pstore")
            mocked_open.assert_called_once_with('/proc/mounts', 'r')

    def test__find_pstore_mount_point_no_pstore(self):
        with mock.patch('builtins.open',
                        mock.mock_open(),
                        create=True) as mocked_open:
            mocked_open.return_value.__iter__.return_value = \
                hws.PROC_MOUNTS_OUTPUT_NO_PSTORE.splitlines()
            self.assertIsNone(self.hardware._find_pstore_mount_point())
            mocked_open.assert_called_once_with('/proc/mounts', 'r')

    @mock.patch('os.listdir', autospec=True)
    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_find_pstore_mount_point', autospec=True)
    def test_erase_pstore(self, mocked_find_pstore, mocked_rmtree,
                          mocked_listdir):
        mocked_find_pstore.return_value = '/sys/fs/pstore'
        pstore_entries = ['dmesg-erst-663482778',
                          'dmesg-erst-663482779']
        mocked_listdir.return_value = pstore_entries
        self.hardware.erase_pstore(self.node, [])
        mocked_listdir.assert_called_once()
        self.assertEqual(mocked_rmtree.call_count,
                         len(pstore_entries))
        mocked_rmtree.assert_has_calls([
            mock.call('/sys/fs/pstore/' + arg) for arg in pstore_entries
        ])

    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_nvme_erase', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_list_erasable_devices', autospec=True)
    def test_erase_devices_express(
            self, mock_list_erasable_devices, mock_nvme_erase,
            mock_destroy_disk_metadata, mock_execute, mock_safety_check):
        block_devices = [
            hardware.BlockDevice('/dev/sda', 'sata', 65535, False),
            hardware.BlockDevice('/dev/md0', 'raid-device', 32767, False),
            hardware.BlockDevice('/dev/nvme0n1', 'nvme', 32767, False),
            hardware.BlockDevice('/dev/nvme1n1', 'nvme', 32767, False)
        ]
        mock_list_erasable_devices.return_value = list(block_devices)

        self.hardware.erase_devices_express(self.node, [])
        self.assertEqual([mock.call(self.hardware, block_devices[2]),
                         mock.call(self.hardware, block_devices[3])],
                         mock_nvme_erase.call_args_list)
        self.assertEqual([mock.call('/dev/sda', self.node['uuid']),
                         mock.call('/dev/md0', self.node['uuid'])],
                         mock_destroy_disk_metadata.call_args_list)
        mock_list_erasable_devices.assert_called_with(self.hardware,
                                                      self.node)
        mock_safety_check.assert_has_calls([
            mock.call(self.node, '/dev/sda'),
            mock.call(self.node, '/dev/md0'),
            mock.call(self.node, '/dev/nvme0n1'),
            mock.call(self.node, '/dev/nvme1n1')
        ])

    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_nvme_erase', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_list_erasable_devices', autospec=True)
    def test_erase_devices_express_stops_on_safety_failure(
            self, mock_list_erasable_devices, mock_nvme_erase,
            mock_destroy_disk_metadata, mock_execute, mock_safety_check):
        mock_safety_check.side_effect = errors.ProtectedDeviceError(
            device='foo',
            what='bar')
        block_devices = [
            hardware.BlockDevice('/dev/sda', 'sata', 65535, False),
            hardware.BlockDevice('/dev/md0', 'raid-device', 32767, False),
            hardware.BlockDevice('/dev/nvme0n1', 'nvme', 32767, False),
            hardware.BlockDevice('/dev/nvme1n1', 'nvme', 32767, False)
        ]
        mock_list_erasable_devices.return_value = list(block_devices)

        self.assertRaises(errors.ProtectedDeviceError,
                          self.hardware.erase_devices_express, self.node, [])
        mock_nvme_erase.assert_not_called()
        mock_destroy_disk_metadata.assert_not_called()
        mock_list_erasable_devices.assert_called_with(self.hardware,
                                                      self.node)
        mock_safety_check.assert_has_calls([
            mock.call(self.node, '/dev/sda')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
    def test_erase_devices_metadata(
            self, mock_metadata, mock_list_devs, mock_execute,
            mock_safety_check, mock__is_vmedia, mocked_ro_device):

        mocked_ro_device.return_value = False
        mock__is_vmedia.return_value = False

        block_devices = [
            hardware.BlockDevice('/dev/sr0', 'vmedia', 12345, True),
            hardware.BlockDevice('/dev/sdb2', 'raid-member', 32767, False),
            hardware.BlockDevice('/dev/sda', 'small', 65535, False),
            hardware.BlockDevice('/dev/sda1', '', 32767, False),
            hardware.BlockDevice('/dev/sda2', 'raid-member', 32767, False),
            hardware.BlockDevice('/dev/md0', 'raid-device', 32767, False)
        ]

        # NOTE(coreywright): Don't return the list, but a copy of it, because
        # we depend on its elements' order when referencing it later during
        # verification, but the method under test sorts the list changing it.
        mock_list_devs.return_value = list(block_devices)
        mock__is_vmedia.side_effect = lambda _, dev: dev.name == '/dev/sr0'
        mock_execute.side_effect = [
            ('sdb2 linux_raid_member host:1 f9978968', ''),
            ('sda2 linux_raid_member host:1 f9978969', ''),
            ('sda1', ''), ('sda', ''), ('md0', '')]

        self.hardware.erase_devices_metadata(self.node, [])

        self.assertEqual([mock.call('/dev/sda1', self.node['uuid']),
                          mock.call('/dev/sda', self.node['uuid']),
                          mock.call('/dev/md0', self.node['uuid'])],
                         mock_metadata.call_args_list)
        mock_list_devs.assert_called_with(self.hardware,
                                          include_partitions=True,
                                          all_serial_and_wwn=False)
        self.assertEqual([mock.call(self.hardware, block_devices[0]),
                          mock.call(self.hardware, block_devices[1]),
                          mock.call(self.hardware, block_devices[4]),
                          mock.call(self.hardware, block_devices[3]),
                          mock.call(self.hardware, block_devices[2]),
                          mock.call(self.hardware, block_devices[5])],
                         mock__is_vmedia.call_args_list)
        mock_safety_check.assert_has_calls([
            mock.call(self.node, '/dev/sda1'),
            mock.call(self.node, '/dev/sda'),
            # This is kind of redundant code/pattern behavior wise
            # but you never know what someone has done...
            mock.call(self.node, '/dev/md0')
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
    def test_erase_devices_metadata_safety_check(
            self, mock_metadata, mock_list_devs, mock__is_vmedia,
            mock_execute, mock_safety_check, mocked_ro_device):
        block_devices = [
            hardware.BlockDevice('/dev/sr0', 'vmedia', 12345, True),
            hardware.BlockDevice('/dev/sdb2', 'raid-member', 32767, False),
            hardware.BlockDevice('/dev/sda', 'small', 65535, False),
            hardware.BlockDevice('/dev/sda1', '', 32767, False),
            hardware.BlockDevice('/dev/sda2', 'raid-member', 32767, False),
            hardware.BlockDevice('/dev/md0', 'raid-device', 32767, False)
        ]
        # NOTE(coreywright): Don't return the list, but a copy of it, because
        # we depend on its elements' order when referencing it later during
        # verification, but the method under test sorts the list changing it.
        mock_list_devs.return_value = list(block_devices)
        mock__is_vmedia.side_effect = lambda _, dev: dev.name == '/dev/sr0'
        mock_execute.side_effect = [
            ('sdb2 linux_raid_member host:1 f9978968', ''),
            ('sda2 linux_raid_member host:1 f9978969', ''),
            ('sda1', ''), ('sda', ''), ('md0', '')]
        mock_safety_check.side_effect = [
            None,
            errors.ProtectedDeviceError(
                device='foo',
                what='bar')
        ]
        mocked_ro_device.return_value = False
        self.assertRaises(errors.ProtectedDeviceError,
                          self.hardware.erase_devices_metadata,
                          self.node, [])

        self.assertEqual([mock.call('/dev/sda1', self.node['uuid'])],
                         mock_metadata.call_args_list)
        mock_list_devs.assert_called_with(self.hardware,
                                          include_partitions=True,
                                          all_serial_and_wwn=False)
        mock_safety_check.assert_has_calls([
            mock.call(self.node, '/dev/sda1'),
            mock.call(self.node, '/dev/sda'),
        ])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_read_only_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_virtual_media_device', autospec=True)
    @mock.patch.object(hardware, 'safety_check_block_device', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'list_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'destroy_disk_metadata', autospec=True)
    def test_erase_devices_metadata_error(
            self, mock_metadata, mock_list_devs, mock__is_raid_member,
            mock_safety_check, mock__is_vmedia, mocked_ro_device):
        block_devices = [
            hardware.BlockDevice('/dev/sda', 'small', 65535, False),
            hardware.BlockDevice('/dev/sdb', 'big', 10737418240, True),
        ]
        mock__is_vmedia.return_value = False
        mock__is_raid_member.return_value = False
        mocked_ro_device.return_value = False
        # NOTE(coreywright): Don't return the list, but a copy of it, because
        # we depend on its elements' order when referencing it later during
        # verification, but the method under test sorts the list changing it.
        mock_list_devs.return_value = list(block_devices)
        # Simulate first call to destroy_disk_metadata() failing, which is for
        # /dev/sdb due to erase_devices_metadata() reverse sorting block
        # devices by name, and second call succeeding, which is for /dev/sda
        error_output = 'Booo00000ooommmmm'
        error_regex = '(?s)/dev/sdb.*' + error_output
        mock_metadata.side_effect = (
            processutils.ProcessExecutionError(error_output),
            None,
        )

        self.assertRaisesRegex(errors.BlockDeviceEraseError, error_regex,
                               self.hardware.erase_devices_metadata,
                               self.node, [])
        # Assert all devices are erased independent if one of them
        # failed previously
        self.assertEqual([mock.call('/dev/sdb', self.node['uuid']),
                          mock.call('/dev/sda', self.node['uuid'])],
                         mock_metadata.call_args_list)
        mock_list_devs.assert_called_with(self.hardware,
                                          include_partitions=True,
                                          all_serial_and_wwn=False)
        self.assertEqual([mock.call(self.hardware, block_devices[1]),
                          mock.call(self.hardware, block_devices[0])],
                         mock__is_vmedia.call_args_list)
        mock_safety_check.assert_has_calls([
            mock.call(self.node, '/dev/sdb'),
            mock.call(self.node, '/dev/sda')
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__is_linux_raid_member(self, mocked_execute):
        raid_member = hardware.BlockDevice('/dev/sda1', 'small', 65535, False)
        mocked_execute.return_value = ('linux_raid_member host.domain:0 '
                                       '85fa41e4-e0ae'), ''
        self.assertTrue(self.hardware._is_linux_raid_member(raid_member))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__is_linux_raid_member_false(self, mocked_execute):
        raid_member = hardware.BlockDevice('/dev/md0', 'small', 65535, False)
        mocked_execute.return_value = 'md0', ''
        self.assertFalse(self.hardware._is_linux_raid_member(raid_member))

    def test__is_read_only_device(self):
        fileobj = mock.mock_open(read_data='1\n')
        device = hardware.BlockDevice('/dev/sdfake', 'fake', 1024, False)
        with mock.patch(
                'builtins.open', fileobj, create=True) as mock_open:
            self.assertTrue(self.hardware._is_read_only_device(device))
            mock_open.assert_called_once_with(
                '/sys/block/sdfake/ro', 'r')

    def test__is_read_only_device_false(self):
        fileobj = mock.mock_open(read_data='0\n')
        device = hardware.BlockDevice('/dev/sdfake', 'fake', 1024, False)
        with mock.patch(
                'builtins.open', fileobj, create=True) as mock_open:
            self.assertFalse(self.hardware._is_read_only_device(device))
            mock_open.assert_called_once_with(
                '/sys/block/sdfake/ro', 'r')

    def test__is_read_only_device_error(self):
        device = hardware.BlockDevice('/dev/sdfake', 'fake', 1024, False)
        with mock.patch(
                'builtins.open', side_effect=IOError,
                autospec=True) as mock_open:
            self.assertFalse(self.hardware._is_read_only_device(device))
            mock_open.assert_called_once_with(
                '/sys/block/sdfake/ro', 'r')

    def test__is_read_only_device_partition_error(self):
        device = hardware.BlockDevice('/dev/sdfake1', 'fake', 1024, False)
        with mock.patch(
                'builtins.open', side_effect=IOError,
                autospec=True) as mock_open:
            self.assertFalse(self.hardware._is_read_only_device(device))
            mock_open.assert_has_calls([
                mock.call('/sys/block/sdfake1/ro', 'r'),
                mock.call('/sys/block/sdfake/ro', 'r')])

    def test__is_read_only_device_partition_ok(self):
        fileobj = mock.mock_open(read_data='1\n')
        device = hardware.BlockDevice('/dev/sdfake1', 'fake', 1024, False)
        reads = [IOError, '1']
        with mock.patch(
                'builtins.open', fileobj, create=True) as mock_open:
            mock_dev_file = mock_open.return_value.read
            mock_dev_file.side_effect = reads
            self.assertTrue(self.hardware._is_read_only_device(device))

    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(os, 'stat', autospec=True)
    @mock.patch.object(glob, 'glob', autospec=True)
    def test_ipmi_device_exists(self, mock_glob, mock_stat, mock_exists):
        mock_stat_result = mock.Mock()
        mock_stat_result.st_mode = stat.S_IFCHR
        mock_stat.return_value = mock_stat_result

        # 1. Test when no device is found in default locations,
        # but found in glob
        mock_exists.side_effect = [False, False, False]
        mock_glob.return_value = ['/dev/ipmi1']
        self.assertTrue(self.hardware.any_ipmi_device_exists())
        mock_stat.assert_called_once_with('/dev/ipmi1')

        mock_exists.reset_mock()
        mock_exists.reset_mock()
        mock_stat.reset_mock()

        # 2. Test when no device is found in default locations,
        # but found in glob
        mock_exists.side_effect = [False, False, False]
        mock_glob.return_value = ['/dev/ipmidev/11']
        self.assertTrue(self.hardware.any_ipmi_device_exists())
        mock_stat.assert_called_once_with('/dev/ipmidev/11')

        # Reset mocks
        mock_exists.reset_mock()
        mock_stat.reset_mock()
        mock_glob.reset_mock()

        # Test when no IPMI device is found at all
        mock_exists.side_effect = [False, False, False]
        mock_glob.return_value = []
        self.assertFalse(self.hardware.any_ipmi_device_exists())
        mock_stat.assert_not_called()

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address(self, mocked_execute, mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = '192.1.2.3\n', ''
        self.assertEqual('192.1.2.3', self.hardware.get_bmc_address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_virt(self, mocked_execute,
                                  mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        self.assertIsNone(self.hardware.get_bmc_address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_zeroed(self, mocked_execute,
                                    mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = '0.0.0.0\n', ''
        self.assertEqual('0.0.0.0', self.hardware.get_bmc_address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_invalid(self, mocked_execute,
                                     mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        # In case of invalid lan channel, stdout is empty and the error
        # on stderr is "Invalid channel"
        mocked_execute.return_value = '\n', 'Invalid channel: 55'
        self.assertEqual('0.0.0.0', self.hardware.get_bmc_address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_random_error(self, mocked_execute,
                                          mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = '192.1.2.3\n', 'Random error message'
        self.assertEqual('192.1.2.3', self.hardware.get_bmc_address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_iterate_channels(self, mocked_execute,
                                              mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        # For channel 1 we simulate unconfigured IP
        # and for any other we return a correct IP address

        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print 1"):
                return '', 'Invalid channel 1\n'
            elif args[0].startswith("ipmitool lan print 2"):
                return '0.0.0.0\n', ''
            elif args[0].startswith("ipmitool lan print 3"):
                return 'meow', ''
            else:
                return '192.1.2.3\n', ''
        mocked_execute.side_effect = side_effect
        self.assertEqual('192.1.2.3', self.hardware.get_bmc_address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_not_available(self, mocked_execute,
                                           mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = '', ''
        self.assertEqual('0.0.0.0', self.hardware.get_bmc_address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_not_available(self, mocked_execute,
                                       mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = '', ''
        self.assertRaises(errors.IncompatibleHardwareMethodError,
                          self.hardware.get_bmc_mac)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac(self, mocked_execute, mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = '192.1.2.3\n01:02:03:04:05:06', ''
        self.assertEqual('01:02:03:04:05:06', self.hardware.get_bmc_mac())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_virt(self, mocked_execute, mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        self.assertIsNone(self.hardware.get_bmc_mac())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_zeroed(self, mocked_execute,
                                mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = '0.0.0.0\n00:00:00:00:00:00', ''
        self.assertRaises(errors.IncompatibleHardwareMethodError,
                          self.hardware.get_bmc_mac)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_invalid(self, mocked_execute,
                                 mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        # In case of invalid lan channel, stdout is empty and the error
        # on stderr is "Invalid channel"
        mocked_execute.return_value = '\n', 'Invalid channel: 55'
        self.assertRaises(errors.IncompatibleHardwareMethodError,
                          self.hardware.get_bmc_mac)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_random_error(self, mocked_execute,
                                      mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.return_value = ('192.1.2.3\n00:00:00:00:00:02',
                                       'Random error message')
        self.assertEqual('00:00:00:00:00:02', self.hardware.get_bmc_mac())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_iterate_channels(self, mocked_execute,
                                          mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        # For channel 1 we simulate unconfigured IP
        # and for any other we return a correct IP address

        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print 1"):
                return '', 'Invalid channel 1\n'
            elif args[0].startswith("ipmitool lan print 2"):
                return '0.0.0.0\n00:00:00:00:23:42', ''
            elif args[0].startswith("ipmitool lan6 print"):
                return '::/255', ''
            elif args[0].startswith("ipmitool lan print 3"):
                return 'meow', ''
            elif args[0].startswith("ipmitool lan print 4"):
                return '192.1.2.3\n01:02:03:04:05:06', ''
            else:
                raise AssertionError
        mocked_execute.side_effect = side_effect
        self.assertEqual('01:02:03:04:05:06', self.hardware.get_bmc_mac())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_for_ipv6(self, mocked_execute,
                                  mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print"):
                return '0.0.0.0\n01:02:03:04:05:06', ''
            elif args[0].startswith("ipmitool lan6 print"):
                return '2001:db8::/32', ''
            else:
                raise AssertionError

        mocked_execute.side_effect = side_effect
        self.assertEqual('01:02:03:04:05:06', self.hardware.get_bmc_mac())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_with_invalid_ipv6(self, mocked_execute,
                                           mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print"):
                return '0.0.0.0\n01:02:03:04:05:06', ''
            elif args[0].startswith("ipmitool lan6 print"):
                return '::/255', ''
            else:
                raise AssertionError

        mocked_execute.side_effect = side_effect
        self.assertRaises(errors.IncompatibleHardwareMethodError,
                          self.hardware.get_bmc_mac)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_with_valid_ipv6_and_invalid_mac(
            self, mocked_execute, mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print"):
                return '0.0.0.0\n00:00:00:00:00:00', ''
            elif args[0].startswith("ipmitool lan6 print"):
                return '2001:db8::/32', ''
            else:
                raise AssertionError

        mocked_execute.side_effect = side_effect
        self.assertRaises(errors.IncompatibleHardwareMethodError,
                          self.hardware.get_bmc_mac)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_no_valid_ip_or_ipv6(self,
                                             mocked_execute,
                                             mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print"):
                return '0.0.0.0\n00:00:00:00:00:00', ''
            elif args[0].startswith("ipmitool lan6 print"):
                return '::/255', ''
            else:
                raise AssertionError

        mocked_execute.side_effect = side_effect
        self.assertRaises(errors.IncompatibleHardwareMethodError,
                          self.hardware.get_bmc_mac)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_iterate_channels_ipv6(self,
                                               mocked_execute,
                                               mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        # For channel 4 we simulate configured IPv6 and MAC

        def side_effect(*args, **kwargs):
            if args[0].startswith("ipmitool lan print 1"):
                return '', 'Invalid channel 1\n'
            elif args[0].startswith("ipmitool lan print 2"):
                return 'meow', ''
            elif args[0].startswith("ipmitool lan6 print 1"):
                return '', 'Invalid channel 1\n'
            elif args[0].startswith("ipmitool lan6 print 2"):
                return 'meow', ''
            elif args[0].startswith("ipmitool lan print 3"):
                return '0.0.0.0\n00:00:00:00:01:02', ''
            elif args[0].startswith("ipmitool lan6 print 3"):
                return 'fe80::/64', ''
            elif args[0].startswith("ipmitool lan print 4"):
                return '0.0.0.0\n01:02:03:04:05:06', ''
            elif args[0].startswith("ipmitool lan6 print 4"):
                return '2001:db8::/32', ''
            else:
                raise AssertionError

        mocked_execute.side_effect = side_effect
        self.assertEqual('01:02:03:04:05:06', self.hardware.get_bmc_mac())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_not_enabled(self, mocked_execute,
                                           mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.side_effect = [('ipv4\n', '')] * 11
        self.assertEqual('::/0', self.hardware.get_bmc_v6address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_dynamic_address(self, mocked_execute,
                                               mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.side_effect = [
            ('ipv6\n', ''),
            (hws.IPMITOOL_LAN6_PRINT_DYNAMIC_ADDR, '')
        ]
        self.assertEqual('2001:1234:1234:1234:1234:1234:1234:1234',
                         self.hardware.get_bmc_v6address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_static_address_both(self, mocked_execute,
                                                   mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        dynamic_disabled = \
            hws.IPMITOOL_LAN6_PRINT_DYNAMIC_ADDR.replace('active', 'disabled')
        mocked_execute.side_effect = [
            ('both\n', ''),
            (dynamic_disabled, ''),
            (hws.IPMITOOL_LAN6_PRINT_STATIC_ADDR, '')
        ]
        self.assertEqual('2001:5678:5678:5678:5678:5678:5678:5678',
                         self.hardware.get_bmc_v6address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_virt(self, mocked_execute,
                                    mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        self.assertIsNone(self.hardware.get_bmc_v6address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_invalid_enables(self, mocked_execute,
                                               mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if args[0].startswith('ipmitool lan6 print'):
                return '', 'Failed to get IPv6/IPv4 Addressing Enables'

        mocked_execute.side_effect = side_effect
        self.assertEqual('::/0', self.hardware.get_bmc_v6address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_invalid_get_address(self, mocked_execute,
                                                   mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if args[0].startswith('ipmitool lan6 print'):
                if args[0].endswith('dynamic_addr') \
                        or args[0].endswith('static_addr'):
                    raise processutils.ProcessExecutionError()
                return 'ipv6', ''

        mocked_execute.side_effect = side_effect
        self.assertEqual('::/0', self.hardware.get_bmc_v6address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(hardware, 'LOG', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_ipmitool_invalid_stdout_format(
            self, mocked_execute, mocked_log, mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if args[0].startswith('ipmitool lan6 print'):
                if args[0].endswith('dynamic_addr') \
                        or args[0].endswith('static_addr'):
                    return 'Invalid\n\tyaml', ''
                return 'ipv6', ''

        mocked_execute.side_effect = side_effect
        self.assertEqual('::/0', self.hardware.get_bmc_v6address())
        one_call = mock.call('Cannot process output of "%(cmd)s" '
                             'command: %(e)s', mock.ANY)
        mocked_log.warning.assert_has_calls([one_call] * 14)

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_channel_7(self, mocked_execute,
                                         mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = True

        def side_effect(*args, **kwargs):
            if not args[0].startswith('ipmitool lan6 print 7'):
                # ipv6 is not enabled for channels 1-6
                if 'enables |' in args[0]:
                    return '', ''
            else:
                if 'enables |' in args[0]:
                    return 'ipv6', ''
                if args[0].endswith('dynamic_addr'):
                    raise processutils.ProcessExecutionError()
                elif args[0].endswith('static_addr'):
                    return hws.IPMITOOL_LAN6_PRINT_STATIC_ADDR, ''

        mocked_execute.side_effect = side_effect
        self.assertEqual('2001:5678:5678:5678:5678:5678:5678:5678',
                         self.hardware.get_bmc_v6address())

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_address_no_ipmi_device(self, mock_execute,
                                            mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = False
        self.assertIsNone(self.hardware.get_bmc_address())
        mock_execute.assert_not_called()

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_mac_no_ipmi_device(self, mock_execute,
                                        mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = False
        self.assertIsNone(self.hardware.get_bmc_mac())
        mock_execute.assert_not_called()

    @mock.patch.object(hardware.GenericHardwareManager,
                       'any_ipmi_device_exists', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_bmc_v6address_no_ipmi_device(self, mock_execute,
                                              mock_ipmi_device_exists):
        mock_ipmi_device_exists.return_value = False
        self.assertIsNone(self.hardware.get_bmc_v6address())
        mock_execute.assert_not_called()

    @mock.patch.object(efi_utils, 'clean_boot_records', autospec=True)
    def test_clean_uefi_nvram_defaults(self, mock_efi_utils):
        self.hardware.clean_uefi_nvram(self.node, [])
        mock_efi_utils.assert_called_once_with(patterns=[
            re.compile(r'^HD\(', flags=re.IGNORECASE),
            re.compile(r'shim.*\.efi', flags=re.IGNORECASE),
            re.compile(r'grub.*\.efi', flags=re.IGNORECASE)
        ])

    @mock.patch.object(efi_utils, 'clean_boot_records', autospec=True)
    def test_clean_uefi_nvram(self, mock_efi_utils):
        self.hardware.clean_uefi_nvram(self.node, [], match_patterns=[
            'VenHw', 'VenMsg'
        ])
        mock_efi_utils.assert_called_once_with(patterns=[
            re.compile(r'VenHw', flags=re.IGNORECASE),
            re.compile(r'VenMsg', flags=re.IGNORECASE)
        ])

    @mock.patch.object(efi_utils, 'clean_boot_records', autospec=True)
    def test_clean_uefi_invalid(self, mock_efi_utils):
        # Not a list
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.hardware.clean_uefi_nvram, self.node, [],
                          match_patterns='VenHw')
        # Not a list of strings
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.hardware.clean_uefi_nvram, self.node, [],
                          match_patterns=[True])
        # Not valid regular expression
        self.assertRaises(errors.InvalidCommandParamsError,
                          self.hardware.clean_uefi_nvram, self.node, [],
                          match_patterns=[')oo('])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_no_configuration(self, mocked_execute):
        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.validate_configuration,
                          self.node, [])

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_do_create_configuration', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'delete_configuration', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'validate_configuration', autospec=True)
    def test_apply_configuration(self, mocked_validate, mocked_delete,
                                 mocked_create):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }

        result = self.hardware.apply_configuration(self.node, [], raid_config)
        self.assertIs(result, mocked_create.return_value)
        mocked_validate.assert_called_once_with(self.hardware, raid_config,
                                                self.node)
        mocked_delete.assert_called_once_with(self.hardware, self.node, [])
        mocked_create.assert_called_once_with(self.hardware, self.node, [],
                                              raid_config)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_do_create_configuration', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'delete_configuration', autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'validate_configuration', autospec=True)
    def test_apply_configuration_no_delete(self, mocked_validate,
                                           mocked_delete, mocked_create):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }

        result = self.hardware.apply_configuration(self.node, [], raid_config,
                                                   delete_existing=False)
        self.assertIs(result, mocked_create.return_value)
        mocked_validate.assert_called_once_with(self.hardware, raid_config,
                                                self.node)
        self.assertFalse(mocked_delete.called)
        mocked_create.assert_called_once_with(self.hardware, self.node, [],
                                              raid_config)

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    def test__handle_raid_skip_list_partial_skip_list(
            self, mocked_get_holder_disks, mocked_get_volume_name):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        raid_device2 = hardware.BlockDevice('/dev/md1', 'RAID-0',
                                            2147483648, True)
        raid_devices = [raid_device1, raid_device2]
        skip_list = ['data']
        mocked_get_holder_disks.side_effect = [
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"]
        ]
        mocked_get_volume_name.side_effect = [
            "root", "data"
        ]
        raid_skip_list_dict = self.hardware._handle_raid_skip_list(
            raid_devices, skip_list)
        delete_raid_devices = raid_skip_list_dict['delete_raid_devices']
        volume_name_of_raid_devices = raid_skip_list_dict[
            'volume_name_of_raid_devices']
        cause_of_not_deleting = raid_skip_list_dict['cause_of_not_deleting']
        self.assertEqual(delete_raid_devices,
                         {'/dev/md0': 'wipe', '/dev/md1': 'keep'})
        self.assertEqual(volume_name_of_raid_devices,
                         {'/dev/md0': 'root', '/dev/md1': 'data'})
        self.assertEqual(cause_of_not_deleting,
                         {'/dev/md0': 'data'})

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    def test__handle_raid_skip_list_complete_skip_list(
            self, mocked_get_holder_disks, mocked_get_volume_name):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        raid_device2 = hardware.BlockDevice('/dev/md1', 'RAID-0',
                                            2147483648, True)
        raid_devices = [raid_device1, raid_device2]
        skip_list = ['data1', 'data2']
        mocked_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb']
        ]
        mocked_get_volume_name.side_effect = [
            'data1', 'data2'
        ]
        raid_skip_list_dict = self.hardware._handle_raid_skip_list(
            raid_devices, skip_list)
        delete_raid_devices = raid_skip_list_dict['delete_raid_devices']
        volume_name_of_raid_devices = raid_skip_list_dict[
            'volume_name_of_raid_devices']
        cause_of_not_deleting = raid_skip_list_dict['cause_of_not_deleting']
        self.assertEqual(delete_raid_devices,
                         {'/dev/md0': 'keep', '/dev/md1': 'keep'})
        self.assertEqual(volume_name_of_raid_devices,
                         {'/dev/md0': 'data1', '/dev/md1': 'data2'})
        # When evaluating /dev/md0, it is marked as the cause
        self.assertEqual(cause_of_not_deleting, {'/dev/md1': 'data1'})

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    def test__analyze_raid_device_device_on_skip_list(
            self, mocked_get_holder_disks, mocked_get_volume_name):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        skip_list = ['data1', 'data2']
        mocked_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb']
        ]
        mocked_get_volume_name.return_value = 'data1'
        volume_name_of_raid_devices = {}
        raid_devices_on_holder_disks = {}
        volume_name_on_skip_list = {}
        esp_part = self.hardware._analyze_raid_device(
            raid_device1, skip_list,
            raid_devices_on_holder_disks,
            volume_name_on_skip_list,
            volume_name_of_raid_devices)
        self.assertIsNone(esp_part)
        self.assertEqual(volume_name_of_raid_devices,
                         {'/dev/md0': 'data1'})
        self.assertEqual(raid_devices_on_holder_disks,
                         {'/dev/sda': ['/dev/md0'], '/dev/sdb': ['/dev/md0']})
        self.assertEqual(volume_name_on_skip_list,
                         {'/dev/md0': True})

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    def test__analyze_raid_device_efi_device(
            self, mocked_get_holder_disks, mocked_get_volume_name):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        skip_list = ['data1', 'data2']
        mocked_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb']
        ]
        mocked_get_volume_name.return_value = 'esp'
        volume_name_of_raid_devices = {}
        raid_devices_on_holder_disks = {}
        volume_name_on_skip_list = {}
        esp_part = self.hardware._analyze_raid_device(
            raid_device1, skip_list,
            raid_devices_on_holder_disks,
            volume_name_on_skip_list,
            volume_name_of_raid_devices)
        self.assertEqual(esp_part, raid_device1.name)
        self.assertEqual(volume_name_of_raid_devices,
                         {'/dev/md0': 'esp'})
        self.assertEqual(raid_devices_on_holder_disks,
                         {'/dev/sda': ['/dev/md0'], '/dev/sdb': ['/dev/md0']})
        self.assertEqual(volume_name_on_skip_list,
                         {'/dev/md0': False})

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    def test__analyze_raid_device_device_not_on_skip_list(
            self, mocked_get_holder_disks, mocked_get_volume_name):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        skip_list = ['data1', 'data2']
        mocked_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb']
        ]
        mocked_get_volume_name.return_value = 'root'
        volume_name_of_raid_devices = {}
        raid_devices_on_holder_disks = {}
        volume_name_on_skip_list = {}
        esp_part = self.hardware._analyze_raid_device(
            raid_device1, skip_list,
            raid_devices_on_holder_disks,
            volume_name_on_skip_list,
            volume_name_of_raid_devices)
        self.assertIsNone(esp_part)
        self.assertEqual(volume_name_of_raid_devices,
                         {'/dev/md0': 'root'})
        self.assertEqual(raid_devices_on_holder_disks,
                         {'/dev/sda': ['/dev/md0'], '/dev/sdb': ['/dev/md0']})
        self.assertEqual(volume_name_on_skip_list,
                         {'/dev/md0': False})

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    def test__handle_raids_with_volume_name_on_skip_list(
            self, mocked_get_holder_disks, mocked_get_volume_name):
        hardware.BlockDevice('/dev/md0', 'RAID-1',
                             107374182400, True)
        raid_device2 = hardware.BlockDevice('/dev/md1', 'RAID-0',
                                            2147483648, True)
        mocked_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb']
        ]
        cause_of_not_deleting = {}
        delete_raid_devices = {'/dev/md0': 'delete', '/dev/md1': 'delete'}
        raid_devices_on_holder_disks = {'/dev/sda': ['/dev/md0', '/dev/md1'],
                                        '/dev/sdb': ['/dev/md0', '/dev/md1']}
        volume_name_of_raid_devices = \
            {'/dev/md0': 'root', '/dev/md1': 'data'}
        mocked_get_volume_name.return_value = 'data'
        self.hardware._handle_raids_with_volume_name_on_skip_list(
            raid_device2.name, delete_raid_devices,
            cause_of_not_deleting, raid_devices_on_holder_disks,
            volume_name_of_raid_devices)
        self.assertEqual(cause_of_not_deleting, {'/dev/md0': 'data'})

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=False)
    def test_create_configuration(self, mocked_os_path_isdir, mocked_execute,
                                  mock_list_parts, mocked_actual_comp):
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        mock_list_parts.side_effect = [
            [],
            processutils.ProcessExecutionError
        ]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        result = self.hardware.create_configuration(node, [])
        mocked_os_path_isdir.assert_has_calls([
            mock.call('/sys/firmware/efi')
        ])
        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md1',
                      '--raid-devices', 2, '/dev/sda2', '/dev/sdb2')])

        self.assertEqual(raid_config, result)

        self.assertEqual(2, mock_list_parts.call_count)
        mock_list_parts.assert_has_calls([
            mock.call(x) for x in ['/dev/sda', '/dev/sdb']
        ])

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_root_volume(self,
                                                   mocked_execute,
                                                   mock_list_parts,
                                                   mocked_actual_comp):
        # Note(mostepha): Ensure that the is_root_volume properties
        # from the raid config are added to
        # GenericHardwareManager._raid_root_device_mapping
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "40",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "root",
                    "is_root_volume": True
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "volume_name": "data",
                    "is_root_volume": False
                },
            ]
        }
        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        mock_list_parts.side_effect = [
            [],
            processutils.ProcessExecutionError
        ]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        self.hardware.create_configuration(node, [])

        self.assertEqual({'/dev/md0': True, '/dev/md1': False},
                         self.hardware._raid_root_device_mapping)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_raid_5(self, mocked_execute,
                                         mock_list_parts, mocked_actual_comp):
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "5",
                    "controller": "software",
                },
            ]
        }
        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        device3 = hardware.BlockDevice('/dev/sdc', 'sdc', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2,
                                                         device3]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sdb
            ('42', None),  # sgdisk -F sdb
            None,  # mklabel sdc
            ('42', None),  # sgdisk -F sdc
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sdc
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sdc
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1', '/dev/sdc1'),
            ('/dev/sda2', '/dev/sdb2', '/dev/sdc2'),
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sdc', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdc'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdc', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdc', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdc', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdc', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 3, '/dev/sda1', '/dev/sdb1',
                      '/dev/sdc1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '5', '--name', 'md1',
                      '--raid-devices', 3, '/dev/sda2', '/dev/sdb2',
                      '/dev/sdc2')])
        self.assertEqual(raid_config, result)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_raid_6(self, mocked_execute,
                                         mock_list_parts, mocked_actual_comp):
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "6",
                    "controller": "software",
                },
            ]
        }
        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        device3 = hardware.BlockDevice('/dev/sdc', 'sdc', 107374182400, True)
        device4 = hardware.BlockDevice('/dev/sdd', 'sdd', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2,
                                                         device3, device4]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sdb
            ('42', None),  # sgdisk -F sdb
            None,  # mklabel sdc
            ('42', None),  # sgdisk -F sdc
            None,  # mklabel sdd
            ('42', None),  # sgdisk -F sdd
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sdc
            None, None, None,  # parted + partx + udevadm_settle sdd
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sdc
            None, None, None,  # parted + partx + udevadm_settle sdd
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1', '/dev/sdc1', '/dev/sdd1'),
            ('/dev/sda2', '/dev/sdb2', '/dev/sdc2', '/dev/sdd2'),
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sdc', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdc'),
            mock.call('parted', '/dev/sdd', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdd'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdc', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdc', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdd', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdd', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdc', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdc', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdd', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdd', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 4, '/dev/sda1', '/dev/sdb1',
                      '/dev/sdc1', '/dev/sdd1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '6', '--name', 'md1',
                      '--raid-devices', 4, '/dev/sda2', '/dev/sdb2',
                      '/dev/sdc2', '/dev/sdd2')])
        self.assertEqual(raid_config, result)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=True)
    def test_create_configuration_efi(self, mocked_os_path_isdir,
                                      mocked_execute, mock_list_parts,
                                      mocked_actual_comp):
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            None,  # mklabel sda
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        result = self.hardware.create_configuration(node, [])
        mocked_os_path_isdir.assert_has_calls([
            mock.call('/sys/firmware/efi')
        ])
        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'gpt'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'gpt'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '551MiB', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '551MiB', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md1',
                      '--raid-devices', 2, '/dev/sda2', '/dev/sdb2')])
        self.assertEqual(raid_config, result)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=False)
    def test_create_configuration_force_gpt_with_disk_label(
            self, mocked_os_path_isdir, mocked_execute, mock_list_part,
            mocked_actual_comp):
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {
            'capabilities': {
                'disk_label': 'gpt'
            }
        }

        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            None,  # mklabel sda
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        result = self.hardware.create_configuration(node, [])
        mocked_os_path_isdir.assert_has_calls([
            mock.call('/sys/firmware/efi')
        ])
        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'gpt'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'gpt'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '8MiB', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '8MiB', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md1',
                      '--raid-devices', 2, '/dev/sda2', '/dev/sdb2')])
        self.assertEqual(raid_config, result)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=False)
    def test_create_configuration_no_max(self, _mocked_isdir, mocked_execute,
                                         mock_list_parts, mocked_actual_comp):
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "20",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }

        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None   # mdadms
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '30GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '30GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md1',
                      '--raid-devices', 2, '/dev/sda2', '/dev/sdb2')])
        self.assertEqual(raid_config, result)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=False)
    def test_create_configuration_max_is_first_logical(self, _mocked_isdir,
                                                       mocked_execute,
                                                       mock_list_parts,
                                                       mocked_actual_comp):
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "20",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }

        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '20GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '20GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '20GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '20GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md0',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md1',
                      '--raid-devices', 2, '/dev/sda2', '/dev/sdb2')])
        self.assertEqual(raid_config, result)

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_hints(self, mocked_execute,
                                             mock_list_parts,
                                             mocked_actual_comp):
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "physical_disks": [
                        {'size': '>= 50'}
                    ] * 2,
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "physical_disks": [
                        {'rotational': True}
                    ] * 2,
                },
            ]
        }
        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            device1,
            hardware.BlockDevice('/dev/sdc', 'sdc', 21474836480, False),
            device2,
            hardware.BlockDevice('/dev/sdd', 'sdd', 21474836480, False),
        ]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md1',
                      '--raid-devices', 2, '/dev/sda2', '/dev/sdb2')])
        self.assertEqual(raid_config, result)

        self.assertEqual(2, mock_list_parts.call_count)
        mock_list_parts.assert_has_calls([
            mock.call(x) for x in ['/dev/sda', '/dev/sdb']
        ])

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_different_disks(self, mocked_execute,
                                                       mock_list_parts,
                                                       mocked_actual_comp):
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "physical_disks": [{'name': '/dev/sda'},
                                       {'name': '/dev/sdb'}],
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "physical_disks": [{'name': '/dev/sdc'},
                                       {'name': '/dev/sdd'}],
                },
            ]
        }
        node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        device3 = hardware.BlockDevice('/dev/sdc', 'sdc', 107374182400, True)
        device4 = hardware.BlockDevice('/dev/sdd', 'sdd', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            device1,
            device2,
            device3,
            device4,
        ]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None,  # mklabel sdc
            ('42', None),  # sgdisk -F sdc
            None,  # mklabel sdd
            ('42', None),  # sgdisk -F sdd
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sdc
            None, None, None,  # parted + partx + udevadm_settle sdd
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sdc1', '/dev/sdd1'),
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sdc', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdc'),
            mock.call('parted', '/dev/sdd', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdd'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdc', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '-1'),
            mock.call('partx', '-av', '/dev/sdc', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdd', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '-1'),
            mock.call('partx', '-av', '/dev/sdd', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md1',
                      '--raid-devices', 2, '/dev/sdc1', '/dev/sdd1')])
        self.assertEqual(raid_config, result)

        self.assertEqual(4, mock_list_parts.call_count)
        mock_list_parts.assert_has_calls([
            mock.call(x) for x in ['/dev/sda', '/dev/sdb',
                                   '/dev/sdc', '/dev/sdd']
        ])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_different_disks_skip_list(
            self, mocked_execute, mock_list_parts, mocked_get_components,
            mocked_list_all_devices, mocked_get_holder_disks,
            mocked_actual_comp, mocked_get_volume_name):
        # The array on skip list is already present
        # We expect to create just the one which is not on skip list, i.e. root
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "root",
                    "physical_disks": [{'name': '/dev/sda'},
                                       {'name': '/dev/sdb'}],
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "data",
                    "physical_disks": [{'name': '/dev/sdc'},
                                       {'name': '/dev/sdd'}],
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'data'}]}
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        device3 = hardware.BlockDevice('/dev/sdc', 'sdc', 107374182400, True)
        device4 = hardware.BlockDevice('/dev/sdd', 'sdd', 107374182400, True)
        raid_device1 = hardware.BlockDevice('/dev/md1', 'RAID-1',
                                            107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            device1,
            device2,
            device3,
            device4,
        ]
        hardware.list_all_block_devices.side_effect = [
            # Calls from _create_raid_ignore_list
            [raid_device1],  # block_type raid
            []               # block type md
        ]
        mocked_get_volume_name.return_value = 'data'
        mocked_get_holder_disks.return_value = ['/dev/sdc', '/dev/sdd']
        mocked_get_components.return_value = ['/dev/sdc1', '/dev/sdd1']

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None  # mdadm create md0
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sdc1', '/dev/sdd1'),
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'root',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1')])
        self.assertEqual(raid_config, result)

        # disk_utils.list_partitions should not be called as the rm_from_list
        # is not None
        self.assertEqual(0, mock_list_parts.call_count)

    def test_create_configuration_with_skip_list_and_unnamed_raid(self):
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "data"
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'data'}]}

        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]

        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.create_configuration,
                          self.node, [])

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=False)
    def test_create_configuration_invalid_raid_config(self,
                                                      mocked_os_path_is_dir,
                                                      mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        self.node['target_raid_config'] = raid_config
        mocked_execute.return_value = (hws.RAID_BLK_DEVICE_TEMPLATE, '')
        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.create_configuration,
                          self.node, [])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_invalid_hints(self, mocked_execute):
        for hints in [
                [],
                [{'size': '>= 50'}],  # more than one disk required,
                "size >= 50",
                [{'size': '>= 50'}, "size >= 50"],
        ]:
            raid_config = {
                "logical_disks": [
                    {
                        "size_gb": "MAX",
                        "raid_level": "1",
                        "controller": "software",
                        "physical_disks": hints,
                    }
                ]
            }
            self.node['target_raid_config'] = raid_config
            self.assertRaises(errors.SoftwareRAIDError,
                              self.hardware.create_configuration,
                              self.node, [])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_mismatching_hints(self, mocked_execute):
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            device1,
            hardware.BlockDevice('/dev/sdc', 'sdc', 21474836480, False),
            device2,
            hardware.BlockDevice('/dev/sdd', 'sdd', 21474836480, False),
        ]
        for hints in [
                [{'size': '>= 150'}] * 2,
                [{'name': '/dev/sda'}] * 2,
        ]:
            raid_config = {
                "logical_disks": [
                    {
                        "size_gb": "MAX",
                        "raid_level": "1",
                        "controller": "software",
                        "physical_disks": hints,
                    }
                ]
            }
            self.node['target_raid_config'] = raid_config
            self.assertRaisesRegex(errors.SoftwareRAIDError,
                                   'No candidates',
                                   self.hardware.create_configuration,
                                   self.node, [])

    @mock.patch.object(disk_utils, 'list_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=False)
    def test_create_configuration_partitions_detected(self,
                                                      mocked_os_path_is_dir,
                                                      mocked_execute,
                                                      mock_list_parts):

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        mock_list_parts.side_effect = [
            [],
            [{'partition_name': '/dev/sdb1'}],
        ]
        self.node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            device1, device2
        ]

        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.create_configuration,
                          self.node, [])

    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=False)
    def test_create_configuration_device_handling_failures(
            self, mocked_os_path_is_dir, mocked_execute, mock_list_parts):

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        self.node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.side_effect = [
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2]]

        # partition table creation
        error_regex = "Failed to create partition table on /dev/sda"
        mocked_execute.side_effect = [
            processutils.ProcessExecutionError]
        self.assertRaisesRegex(errors.CommandExecutionError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])
        # partition creation
        error_regex = "Failed to create partitions on /dev/sda"
        mocked_execute.side_effect = [
            None,  # partition tables on sda
            ('42', None),  # sgdisk -F sda
            None,  # partition tables on sdb
            ('42', None),  # sgdisk -F sdb
            processutils.ProcessExecutionError]
        self.assertRaisesRegex(errors.SoftwareRAIDError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])
        # raid device creation
        error_regex = "Failed to create partitions on /dev/sda"
        mocked_execute.side_effect = [
            None,  # partition tables on sda
            ('42', None),  # sgdisk -F sda
            None,  # partition tables on sdb
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # RAID-1 partitions on sd{a,b}
            None, None, None,  # RAID-N partitions on sd{a,b}
            processutils.ProcessExecutionError]
        self.assertRaisesRegex(errors.SoftwareRAIDError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])

    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_device_handling_failures_raid5(
            self, mocked_execute, mock_list_parts):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "5",
                    "controller": "software",
                },
            ]
        }
        self.node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.side_effect = [
            [device1, device2],
            [device1, device2]]

        # validation configuration explicitly fails before any action
        error_regex = ("Software RAID configuration is not possible for "
                       "RAID level 5 with only 2 block devices found.")
        # Execute is actually called for listing_block_devices
        self.assertFalse(mocked_execute.called)
        self.assertRaisesRegex(errors.SoftwareRAIDError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_device_handling_failures_raid6(
            self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "6",
                    "controller": "software",
                },
            ]
        }
        self.node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        device3 = hardware.BlockDevice('/dev/sdc', 'sdc', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.side_effect = [
            [device1, device2, device3],
            [device1, device2, device3]]

        # pre-creation validation fails as insufficient number of devices found
        error_regex = ("Software RAID configuration is not possible for "
                       "RAID level 6 with only 3 block devices found.")

        # Execute is actually called for listing_block_devices
        self.assertFalse(mocked_execute.called)
        self.assertRaisesRegex(errors.SoftwareRAIDError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])

    def test_create_configuration_empty_target_raid_config(self):
        self.node['target_raid_config'] = {}
        result = self.hardware.create_configuration(self.node, [])
        self.assertEqual(result, {})

    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=True)
    def test_create_configuration_with_nvme(self, mocked_os_path_isdir,
                                            mocked_execute, mock_list_parts,
                                            mocked_actual_comp):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        self.node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/nvme0n1', 'nvme0n1',
                                       107374182400, True)
        device2 = hardware.BlockDevice('/dev/nvme1n1', 'nvme1n1',
                                       107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            None,  # mklabel sda
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/nvme0n1p1', '/dev/nvme1n1p1'),
            ('/dev/nvme0n1p2', '/dev/nvme1n1p2'),
        ]

        result = self.hardware.create_configuration(self.node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/nvme0n1', '-s', '--', 'mklabel',
                      'gpt'),
            mock.call('parted', '/dev/nvme1n1', '-s', '--', 'mklabel',
                      'gpt'),
            mock.call('parted', '/dev/nvme0n1', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '551MiB', '10GiB'),
            mock.call('partx', '-av', '/dev/nvme0n1', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/nvme1n1', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '551MiB', '10GiB'),
            mock.call('partx', '-av', '/dev/nvme1n1', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/nvme0n1', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/nvme0n1', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/nvme1n1', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/nvme1n1', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'md0',
                      '--raid-devices', 2, '/dev/nvme0n1p1',
                      '/dev/nvme1n1p1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'md1',
                      '--raid-devices', 2, '/dev/nvme0n1p2', '/dev/nvme1n1p2')
        ])
        self.assertEqual(raid_config, result)

    @mock.patch.object(disk_utils, 'list_partitions', autospec=True,
                       return_value=[])
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True, return_value=True)
    def test_create_configuration_failure_with_nvme(self,
                                                    mocked_os_path_isdir,
                                                    mocked_execute,
                                                    mock_list_parts):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        self.node['target_raid_config'] = raid_config
        device1 = hardware.BlockDevice('/dev/nvme0n1', 'nvme0n1',
                                       107374182400, True)
        device2 = hardware.BlockDevice('/dev/nvme1n1', 'nvme1n1',
                                       107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.side_effect = [
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2],
            [device1, device2]]

        # partition table creation
        error_regex = "Failed to create partition table on /dev/nvme0n1"
        mocked_execute.side_effect = [
            processutils.ProcessExecutionError]
        self.assertRaisesRegex(errors.CommandExecutionError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])
        # partition creation
        error_regex = "Failed to create partitions on /dev/nvme0n1"
        mocked_execute.side_effect = [
            None,  # partition tables on sda
            None,  # partition tables on sdb
            processutils.ProcessExecutionError]
        self.assertRaisesRegex(errors.SoftwareRAIDError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])
        # raid device creation
        error_regex = "Failed to create partitions on /dev/nvme0n1"
        mocked_execute.side_effect = [
            None,  # partition tables on sda
            None,  # partition tables on sdb
            None, None, None,  # RAID-1 partitions on sd{a,b}
            None, None, None,  # RAID-N partitions on sd{a,b}
            processutils.ProcessExecutionError]
        self.assertRaisesRegex(errors.SoftwareRAIDError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])

    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_skip_list(
            self, mocked_execute, mock_list_parts, mocked_list_all_devices,
            mocked_get_components, mocked_get_holder_disks, mocked_actual_comp,
            mocked_get_volume_name):
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "small"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "volume_name": "large"
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'large'}]}
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        hardware.list_all_block_devices.side_effect = [
            [raid_device1],  # block_type raid
            []               # block type md
        ]
        mocked_get_volume_name.return_value = "large"

        mocked_get_holder_disks.return_value = ['/dev/sda', '/dev/sdb']
        mocked_get_components.return_value = ['/dev/sda1', '/dev/sdb1']

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        result = self.hardware.create_configuration(node, [])
        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'small',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1')])
        self.assertEqual(raid_config, result)

        self.assertEqual(0, mock_list_parts.call_count)

    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_skip_list_root_on_more_disks_than_data(
            self, mocked_execute, mock_list_parts, mocked_list_all_devices,
            mocked_get_components, mocked_get_holder_disks,
            mocked_get_volume_name):
        # Please note that this test case is solely for testing purposes
        # and does not make sense in real deployments.
        # There are two RAID arrays: root and data
        # - root spans 100GB on all 4 disks present on the node
        # - data spans the rest of 2 of those disks and is in skip list
        # In this case, root should be only wiped, not deleted, so no array
        # should be created
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "root",
                    "physical_disks": [{'name': '/dev/sda'},
                                       {'name': '/dev/sdb'},
                                       {'name': '/dev/sdc'},
                                       {'name': '/dev/sdd'}],
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "data",
                    "physical_disks": [{'name': '/dev/sda'},
                                       {'name': '/dev/sdb'}],
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'data'}]}
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 1073741824000, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 1073741824000, True)
        hardware.BlockDevice('/dev/sda', 'sda', 1073741824000, True)
        hardware.BlockDevice('/dev/sdb', 'sdb', 1073741824000, True)
        raid_device_root = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                                107374182400, True)
        raid_device_data = hardware.BlockDevice('/dev/md1', 'RAID-1',
                                                966367641600, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        hardware.list_all_block_devices.side_effect = [
            [raid_device_root, raid_device_data],  # block_type raid
            []               # block type md
        ]
        mocked_get_volume_name.side_effect = [
            'root', 'data',  # handle raid skip list
            'root', 'data'  # create ignore list
        ]

        mocked_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb', '/dev/sdc', '/dev/sdd'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb', '/dev/sdc', '/dev/sdd'],
            ['/dev/sda', '/dev/sdb']
        ]
        mocked_get_components.side_effect = [
            ['/dev/sda1', '/dev/sdb1', '/dev/sdc1', '/dev/sdd1'],
            ['/dev/sda2', '/dev/sdb2']
        ]

        result = self.hardware.create_configuration(node, [])
        self.assertEqual(raid_config, result)

        self.assertEqual(0, mocked_execute.call_count)
        self.assertEqual(0, mock_list_parts.call_count)

    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_skip_list_multiple_raids_on_disk(
            self, mocked_execute, mocked_get_volume_name,
            mocked_get_component_devices, mocked_list_all_block_devices):
        # We expect that both root and data to already be present,
        # so we do not create any
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "root"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "data"
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'data'}]}

        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        sda1 = hardware.BlockDevice('/dev/sda1', 'model12', 10737418240, True)
        sdb1 = hardware.BlockDevice('/dev/sdb1', 'model12', 10737418240, True)
        sda2 = hardware.BlockDevice('/dev/sda2', 'model12', 96636764160, True)
        sdb2 = hardware.BlockDevice('/dev/sdb2', 'model12', 96636764160, True)
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            10737418240, True)
        raid_device2 = hardware.BlockDevice('/dev/md1', 'RAID-1',
                                            96636764160, True)

        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        mocked_get_component_devices.side_effect = [
            [sda1, sdb1],
            [sda2, sdb2]
        ]
        mocked_list_all_block_devices.side_effect = [
            [raid_device1, raid_device2],  # block type raid
            [],                            # block type md
        ]
        mocked_get_volume_name.side_effect = [
            'root', 'data'  # create ignore list
        ]

        self.hardware._handle_raid_skip_list = mock.Mock()
        self.hardware._handle_raid_skip_list.return_value = {
            'delete_raid_devices': {raid_device1.name: 'wipe',
                                    raid_device2.name: 'keep'},
            'volume_name_of_raid_devices': {raid_device1.name: 'root',
                                            raid_device2.name: 'data'},
            'cause_of_not_deleting': {raid_device1.name: 'data'}
        }
        mocked_execute.side_effect = [
            None,  # Examine /dev/sda1
            None,  # Examine /dev/sda2
        ]

        result = self.hardware.create_configuration(node, [])

        self.assertEqual(0, mocked_execute.call_count)
        self.assertEqual(raid_config, result)

    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_skip_list_on_separate_disks(
            self, mocked_execute, mocked_get_actual_component_devices,
            mocked_get_volume_name, mocked_get_component_devices,
            mocked_list_all_block_devices):
        # The array new_volume is on two disks
        # The other array saved_data is on other disks and is already present
        # We only expect to create new_volume
        node = self.node
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "new_volume",
                    "physical_disks": [{'name': '/dev/sdc'},
                                       {'name': '/dev/sdd'}],
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "saved_data",
                    "physical_disks": [{'name': '/dev/sda'},
                                       {'name': '/dev/sdb'}],
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {
            'skip_block_devices': [{'volume_name': 'saved_data'}]
        }

        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        device3 = hardware.BlockDevice('/dev/sdc', 'sdc', 107374182400, True)
        device4 = hardware.BlockDevice('/dev/sdd', 'sdd', 107374182400, True)
        sda1 = hardware.BlockDevice('/dev/sda1', 'model12', 107374182400, True)
        sdb1 = hardware.BlockDevice('/dev/sdb1', 'model12', 107374182400, True)
        raid_device1 = hardware.BlockDevice('/dev/md127', 'RAID-1',
                                            107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            device1, device2, device3, device4
        ]
        mocked_list_all_block_devices.side_effect = [
            # create ignore list
            [raid_device1],  # block type raid
            [],              # block type md
        ]
        mocked_get_component_devices.side_effect = [
            [sda1, sdb1]
        ]
        mocked_get_volume_name.side_effect = [
            'saved_data'  # create ignore list
        ]

        self.hardware._handle_raid_skip_list = mock.Mock()
        self.hardware._handle_raid_skip_list.return_value = {
            'delete_raid_devices': {raid_device1.name: 'keep'},
            'volume_name_of_raid_devices': {raid_device1.name: 'saved_data'},
            'cause_of_not_deleting': {raid_device1.name: 'saved_data'}
        }
        mocked_execute.side_effect = [
            None,  # mklabel sdc
            ('42', None),  # sgdisk -F sdc
            None,  # mklabel sdd
            ('42', None),  # sgdisk -F sdd
            None, None, None,  # parted + partx + udevadm_settle sdc
            None, None, None,  # parted + partx + udevadm_settle sdd
            None  # mdadm --create /dev/md0
        ]
        mocked_get_actual_component_devices.side_effect = [
            ('/dev/sdc1', '/dev/sdd1')
        ]

        result = self.hardware.create_configuration(node, [])

        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sdc', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdc'),
            mock.call('parted', '/dev/sdd', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdd'),
            mock.call('parted', '/dev/sdc', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '100GiB'),
            mock.call('partx', '-av', '/dev/sdc', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdd', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '100GiB'),
            mock.call('partx', '-av', '/dev/sdd', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'new_volume',
                      '--raid-devices', 2, '/dev/sdc1', '/dev/sdd1')
        ])
        self.assertEqual(raid_config, result)

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_skip_list_existing_device_does_not_match(
            self, mocked_execute, mocked_list_all_devices,
            mocked_get_components, mocked_get_holder_disks,
            mocked_get_volume_name):
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "small"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "volume_name": "large"
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'large'}]}
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        hardware.list_all_block_devices.side_effect = [
            [raid_device1],  # block_type raid
            []               # block type md
        ]
        mocked_get_volume_name.return_value = "small"

        mocked_get_holder_disks.return_value = ['/dev/sda', '/dev/sdb']
        mocked_get_components.return_value = ['/dev/sda1', '/dev/sdb1']

        error_regex = "Existing Software RAID device detected that should not"
        mocked_execute.side_effect = [
            processutils.ProcessExecutionError]
        self.assertRaisesRegex(errors.SoftwareRAIDError, error_regex,
                               self.hardware.create_configuration,
                               self.node, [])

        self.assertEqual(0, mocked_execute.call_count)

    @mock.patch.object(utils, 'get_node_boot_mode', lambda node: 'bios')
    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(disk_utils, 'list_partitions', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_skip_list_no_existing_device(
            self, mocked_execute, mock_list_parts,
            mocked_list_all_devices, mocked_actual_comp):
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "small"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "volume_name": "large"
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'large'}]}
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        mock_list_parts.side_effect = [
            [],
            processutils.ProcessExecutionError
        ]
        hardware.list_all_block_devices.side_effect = [
            [],  # block_type raid
            []               # block type md
        ]

        mocked_execute.side_effect = [
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sda
            None,  # mklabel sda
            ('42', None),  # sgdisk -F sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None, None,  # parted + partx + udevadm_settle sda
            None, None, None,  # parted + partx + udevadm_settle sdb
            None, None  # mdadms
        ]

        mocked_actual_comp.side_effect = [
            ('/dev/sda1', '/dev/sdb1'),
            ('/dev/sda2', '/dev/sdb2'),
        ]

        result = self.hardware.create_configuration(node, [])
        mocked_execute.assert_has_calls([
            mock.call('parted', '/dev/sda', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sda'),
            mock.call('parted', '/dev/sdb', '-s', '--', 'mklabel', 'msdos'),
            mock.call('sgdisk', '-F', '/dev/sdb'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '42s', '10GiB'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sda', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sda', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('parted', '/dev/sdb', '-s', '-a', 'optimal', '--',
                      'mkpart', 'primary', '10GiB', '-1'),
            mock.call('partx', '-av', '/dev/sdb', attempts=3,
                      delay_on_retry=True),
            mock.call('udevadm', 'settle'),
            mock.call('mdadm', '--create', '/dev/md0', '--force', '--run',
                      '--metadata=1', '--level', '1', '--name', 'small',
                      '--raid-devices', 2, '/dev/sda1', '/dev/sdb1'),
            mock.call('mdadm', '--create', '/dev/md1', '--force', '--run',
                      '--metadata=1', '--level', '0', '--name', 'large',
                      '--raid-devices', 2, '/dev/sda2', '/dev/sdb2')])

        self.assertEqual(raid_config, result)

        self.assertEqual(2, mock_list_parts.call_count)
        mock_list_parts.assert_has_calls([
            mock.call(x) for x in ['/dev/sda', '/dev/sdb']
        ])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(raid_utils, '_get_actual_component_devices',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_create_configuration_with_complete_skip_list(
            self, mocked_execute, mocked_ls_all_devs, mocked_get_components,
            mocked_get_holder_disks, mocked_actual_comp,
            mocked_get_volume_name):
        node = self.node

        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "10",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "small"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "volume_name": "large"
                },
            ]
        }
        node['target_raid_config'] = raid_config
        node['properties'] = {'skip_block_devices': [{'volume_name': 'small'},
                                                     {'volume_name': 'large'}]}
        raid_device0 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            2147483648, True)
        raid_device1 = hardware.BlockDevice('/dev/md1', 'RAID-0',
                                            107374182400, True)
        device1 = hardware.BlockDevice('/dev/sda', 'sda', 107374182400, True)
        device2 = hardware.BlockDevice('/dev/sdb', 'sdb', 107374182400, True)
        hardware.list_all_block_devices.side_effect = [
            [raid_device0, raid_device1],  # block_type raid
            []                             # block type md
        ]
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [device1, device2]
        mocked_get_volume_name.side_effect = [
            "small",
            "large",
            "small",
            "large"
        ]

        mocked_get_holder_disks.side_effect = [
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb']]
        mocked_get_components.side_effect = [
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sda2', '/dev/sdb2']]
        self.hardware.create_configuration(node, [])
        self.assertEqual(0, mocked_execute.call_count)
        self.assertEqual(0, mocked_get_components.call_count)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__get_md_uuid(self, mocked_execute):
        mocked_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT, '')]
        md_uuid = hardware._get_md_uuid('/dev/md0')
        self.assertEqual('83143055:2781ddf5:2c8f44c7:9b45d92e', md_uuid)

    @mock.patch.object(hardware, '_get_md_uuid', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_component_devices(self, mocked_execute,
                                   mocked_list_all_block_devices,
                                   mocked_md_uuid):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        sda = hardware.BlockDevice('/dev/sda', 'model12', 21, True)
        sdz = hardware.BlockDevice('/dev/sdz', 'model12', 21, True)
        sda1 = hardware.BlockDevice('/dev/sda1', 'model12', 21, True)
        sdz1 = hardware.BlockDevice('/dev/sdz1', 'model12', 21, True)

        mocked_md_uuid.return_value = '83143055:2781ddf5:2c8f44c7:9b45d92e'
        hardware.list_all_block_devices.side_effect = [
            [sda, sdz],    # list_all_block_devices
            [sda1, sdz1],  # list_all_block_devices partitions
        ]
        mocked_execute.side_effect = [
            ['mdadm --examine output for sda', '_'],
            ['mdadm --examine output for sdz', '_'],
            [hws.MDADM_EXAMINE_OUTPUT_MEMBER, '_'],
            [hws.MDADM_EXAMINE_OUTPUT_NON_MEMBER, '_'],
        ]

        component_devices = hardware.get_component_devices(raid_device1)
        self.assertEqual(['/dev/sda1'], component_devices)
        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--examine', '/dev/sda',
                      use_standard_locale=True),
            mock.call('mdadm', '--examine', '/dev/sdz',
                      use_standard_locale=True),
            mock.call('mdadm', '--examine', '/dev/sda1',
                      use_standard_locale=True),
            mock.call('mdadm', '--examine', '/dev/sdz1',
                      use_standard_locale=True)])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_holder_disks(self, mocked_execute):
        mocked_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT, '')]
        holder_disks = hardware.get_holder_disks('/dev/md0')
        self.assertEqual(['/dev/vde', '/dev/vdf'], holder_disks)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(os, 'stat', autospec=True)
    def test_get_holder_disks_with_whole_device(self, mocked_stat,
                                                mocked_exists,
                                                mocked_execute):
        mocked_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT_WHOLE_DEVICE,
                                       '')]
        mocked_exists.return_value = True
        mocked_stat.return_value.st_mode = stat.S_IFBLK
        holder_disks = hardware.get_holder_disks('/dev/md0')
        self.assertEqual(['/dev/vde', '/dev/vdf'], holder_disks)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_holder_disks_with_nvme(self, mocked_execute):
        mocked_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT_NVME, '')]
        holder_disks = hardware.get_holder_disks('/dev/md0')
        self.assertEqual(['/dev/nvme0n1', '/dev/nvme1n1'], holder_disks)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_holder_disks_unexpected_devices(self, mocked_execute):
        side_effect = hws.MDADM_DETAIL_OUTPUT_NVME.replace('nvme1n1p1',
                                                           'notmatching1a')
        mocked_execute.side_effect = [(side_effect, '')]
        self.assertRaisesRegex(
            errors.SoftwareRAIDError,
            r'^Software RAID caused unknown error: Could not get holder disks '
            r'of /dev/md0: unexpected pattern for partition '
            r'/dev/notmatching1a$',
            hardware.get_holder_disks, '/dev/md0')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_holder_disks_broken_raid0(self, mocked_execute):
        mocked_execute.side_effect = [(hws.MDADM_DETAIL_OUTPUT_BROKEN_RAID0,
                                       '')]
        holder_disks = hardware.get_holder_disks('/dev/md126')
        self.assertEqual(['/dev/sda'], holder_disks)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_holder_disks_poisoned_output(self, mocked_execute):
        mocked_execute.side_effect = [(hws.MDADM_DETAIL_POISONED, '')]
        holder_disks = hardware.get_holder_disks('/dev/md0')
        self.assertEqual(['/dev/vda', '/dev/vdb'], holder_disks)

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration(self, mocked_execute, mocked_list,
                                  mocked_get_component, mocked_get_holder,
                                  mocked_get_volume_name):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        raid_device2 = hardware.BlockDevice('/dev/md1', 'RAID-0',
                                            2147483648, True)
        sda = hardware.BlockDevice('/dev/sda', 'model12', 21, True)
        sdb = hardware.BlockDevice('/dev/sdb', 'model12', 21, True)
        sdc = hardware.BlockDevice('/dev/sdc', 'model12', 21, True)

        hardware.list_all_block_devices.side_effect = [
            [raid_device1, raid_device2],  # list_all_block_devices raid
            [],  # list_all_block_devices raid (md)
            [sda, sdb, sdc],  # list_all_block_devices disks
            [],  # list_all_block_devices parts
            [],  # list_all_block_devices raid
            [],  # list_all_block_devices raid (md)
        ]
        mocked_get_component.side_effect = [
            ["/dev/sda1", "/dev/sdb1"],
            ["/dev/sda2", "/dev/sdb2"]]
        mocked_get_holder.side_effect = [
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"]]
        mocked_get_volume_name.side_effect = [
            "/dev/md0", "/dev/md1"
        ]
        mocked_execute.side_effect = [
            None,  # mdadm --assemble --scan
            None,  # wipefs md0
            None,  # mdadm --stop md0
            ['_', 'mdadm --examine output for sda1'],
            None,  # mdadm zero-superblock sda1
            ['_', 'mdadm --examine output for sdb1'],
            None,  # mdadm zero-superblock sdb1
            None,  # wipefs sda
            None,  # wipefs sdb
            None,  # wipfs md1
            None,  # mdadm --stop md1
            ['_', 'mdadm --examine output for sda2'],
            None,  # mdadm zero-superblock sda2
            ['_', 'mdadm --examine output for sdb2'],
            None,  # mdadm zero-superblock sdb2
            None,  # wipefs sda
            None,  # wipefs sda
            ['_', 'mdadm --examine output for sdc'],
            None,   # mdadm zero-superblock sdc
            # examine sdb
            processutils.ProcessExecutionError('No md superblock detected'),
            # examine sda
            processutils.ProcessExecutionError('No md superblock detected'),
            None,  # mdadm --assemble --scan
        ]

        self.hardware.delete_configuration(self.node, [])

        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('wipefs', '-af', '/dev/md0'),
            mock.call('mdadm', '--stop', '/dev/md0'),
            mock.call('mdadm', '--examine', '/dev/sda1',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sda1'),
            mock.call('mdadm', '--examine', '/dev/sdb1',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdb1'),
            mock.call('wipefs', '-af', '/dev/md1'),
            mock.call('mdadm', '--stop', '/dev/md1'),
            mock.call('mdadm', '--examine', '/dev/sda2',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sda2'),
            mock.call('mdadm', '--examine', '/dev/sdb2',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdb2'),
            mock.call('mdadm', '--examine', '/dev/sdc',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdc'),
            mock.call('mdadm', '--examine', '/dev/sdb',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdb'),
            mock.call('mdadm', '--examine', '/dev/sda',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sda'),
            mock.call('wipefs', '-af', '/dev/sda'),
            mock.call('wipefs', '-af', '/dev/sdb'),
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
        ])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration_partition(self, mocked_execute, mocked_list,
                                            mocked_get_component,
                                            mocked_get_volume_name):
        # This test checks that if no components are returned for a given
        # raid device, then it must be a nested partition and so it gets
        # skipped
        raid_device1_part1 = hardware.BlockDevice('/dev/md0p1', 'RAID-1',
                                                  1073741824, True)
        hardware.list_all_block_devices.side_effect = [
            [raid_device1_part1],  # list_all_block_devices raid + md
            [],  # list_all_block_devices disks
            [],  # list_all_block_devices parts
            [],  # list_all_block_devices raid + md
        ]
        mocked_get_volume_name.return_value = None
        mocked_get_component.return_value = []
        self.assertIsNone(self.hardware.delete_configuration(self.node, []))
        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
        ])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration_failure_blocks_remaining(
            self, mocked_execute, mocked_list, mocked_get_component,
            mocked_get_volume_name):

        # This test checks that, if after two raid clean passes there still
        # remain softraid hints on drives, then the delete_configuration call
        # raises an error
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)

        hardware.list_all_block_devices.side_effect = [
            [raid_device1],  # list_all_block_devices raid + md
            [],  # list_all_block_devices disks
            [],  # list_all_block_devices parts
            [raid_device1],  # list_all_block_devices raid + md
            [],  # list_all_block_devices disks
            [],  # list_all_block_devices parts
            [raid_device1],  # list_all_block_devices raid + md
        ]
        mocked_get_component.return_value = []
        mocked_get_volume_name.return_value = "/dev/md0"

        self.assertRaisesRegex(
            errors.SoftwareRAIDError,
            r"^Software RAID caused unknown error: Unable to clean all "
            r"softraid correctly. Remaining \['/dev/md0'\]$",
            self.hardware.delete_configuration, self.node, [])

        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
        ])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_skip_list_from_node_for_raids', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration_skip_list(self, mocked_execute, mocked_list,
                                            mocked_get_component,
                                            mocked_get_holder,
                                            mocked_get_skip_list,
                                            mocked_get_volume_name):
        raid_device1 = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                            107374182400, True)
        raid_device2 = hardware.BlockDevice('/dev/md1', 'RAID-0',
                                            2147483648, True)
        sda = hardware.BlockDevice('/dev/sda', 'model12', 21, True)
        sdb = hardware.BlockDevice('/dev/sdb', 'model12', 21, True)
        sdc = hardware.BlockDevice('/dev/sdc', 'model12', 21, True)

        partitions = [
            hardware.BlockDevice('/dev/sdb1', 'raid-member', 32767, False),
            hardware.BlockDevice('/dev/sdb2', 'raid-member', 32767, False),
            hardware.BlockDevice('/dev/sda1', 'raid_member', 32767, False),
            hardware.BlockDevice('/dev/sda2', 'raid-member', 32767, False),
        ]

        hardware.list_all_block_devices.side_effect = [
            [raid_device1, raid_device2],  # list_all_block_devices raid + md
            [sda, sdb, sdc],  # list_all_block_devices disks
            partitions,  # list_all_block_devices parts
            [],  # list_all_block_devices raid + md
        ]
        mocked_get_component.side_effect = [
            ["/dev/sda1", "/dev/sdb1"],
            ["/dev/sda2", "/dev/sdb2"]]
        mocked_get_holder.side_effect = [
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"],
            ["/dev/sda", "/dev/sdb"]]
        mocked_get_volume_name.side_effect = [
            "/dev/md0", "small"
        ]
        mocked_get_skip_list.return_value = set({"small"})

        self.hardware.delete_configuration(self.node, [])

        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('wipefs', '-af', '/dev/md0'),
            mock.call('mdadm', '--examine', '/dev/sdc',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdc'),
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
        ])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_skip_list_from_node_for_raids', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration_skip_list_root_on_more_disks_than_data(
            self, mocked_execute, mocked_list, mocked_get_components,
            mocked_get_holder, mocked_get_skip_list, mocked_get_volume_name):
        # Please note that this test case is solely for testing purposes
        # and does not make sense in real deployments.
        # There are two RAID arrays: root and data
        # - root spans 100GB on all 4 disks present on the node
        # - data spans the rest of 2 of those disks and is in skip list
        # The data should be untouched, the root should be wiped,
        # but not deleted
        sda = hardware.BlockDevice('/dev/sda', 'sda', 1073741824000, True)
        sdb = hardware.BlockDevice('/dev/sdb', 'sdb', 1073741824000, True)
        sdc = hardware.BlockDevice('/dev/sdc', 'sdc', 1073741824000, True)
        sdd = hardware.BlockDevice('/dev/sdd', 'sdd', 1073741824000, True)
        rd_root = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                       107374182400, True)
        rd_data = hardware.BlockDevice('/dev/md1', 'RAID-1',
                                       966367641600, True)
        partitions = [
            hardware.BlockDevice('/dev/sda1', 'raid-member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sdb1', 'raid-member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sdc1', 'raid_member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sdd1', 'raid-member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sda2', 'raid-member', 966367641600,
                                 False),
            hardware.BlockDevice('/dev/sdb2', 'raid-member', 966367641600,
                                 False),
        ]

        mocked_list.side_effect = [
            [rd_root, rd_data],  # list_all_block_devices raid + md
            [sda, sdb, sdc, sdd],  # list_all_block_devices disks
            partitions,  # list_all_block_devices parts
            [rd_root, rd_data],  # list_all_block_devices raid + md
        ]
        mocked_get_volume_name.side_effect = [
            'root', 'data'
        ]

        mocked_get_holder.side_effect = [
            ['/dev/sda', '/dev/sdb', '/dev/sdc', '/dev/sdd'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb', '/dev/sdc', '/dev/sdd'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sda', '/dev/sdb', '/dev/sdc', '/dev/sdd'],
            ['/dev/sda', '/dev/sdb']
        ]
        mocked_get_components.side_effect = [
            ['/dev/sda1', '/dev/sdb1', '/dev/sdc1', '/dev/sdd1'],
            ['/dev/sda2', '/dev/sdb2'],
            ['/dev/sda1', '/dev/sdb1', '/dev/sdc1', '/dev/sdd1'],
            ['/dev/sda2', '/dev/sdb2'],
        ]
        mocked_get_skip_list.return_value = set({'data'})

        self.hardware.delete_configuration(self.node, [])
        mocked_list.assert_has_calls([
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
            mock.call(all_serial_and_wwn=False),
            mock.call(block_type='part', ignore_raid=True),
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
        ])
        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('wipefs', '-af', '/dev/md0'),  # wipe root
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False)])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_skip_list_from_node_for_raids', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration_skip_list_uefi(
            self, mocked_execute, mocked_list, mocked_get_components,
            mocked_get_holder, mocked_get_skip_list, mocked_get_volume_name):
        # Raid arrays: root, data, and esp (EFI partition) span two disks
        # Data is on the skip list, so none of the partitions gets deleted
        # Root gets wiped, esp stays to keep the filesystem
        sda = hardware.BlockDevice('/dev/sda', 'sda', 1073741824000, True)
        sdb = hardware.BlockDevice('/dev/sdb', 'sdb', 1073741824000, True)
        rd_root = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                       107374182400, True)
        rd_data = hardware.BlockDevice('/dev/md1', 'RAID-1',
                                       966367641088, True)
        rd_esp = hardware.BlockDevice('/dev/md2', 'RAID-1',
                                      512, True)
        partitions = [
            hardware.BlockDevice('/dev/sda1', 'raid-member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sdb1', 'raid-member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sda2', 'raid-member', 9663676416088,
                                 False),
            hardware.BlockDevice('/dev/sdb2', 'raid-member', 966367641088,
                                 False),
            hardware.BlockDevice('/dev/sda3', 'raid-member', 512, False),
            hardware.BlockDevice('/dev/sdb3', 'raid-member', 512, False),
        ]

        mocked_list.side_effect = [
            [rd_root, rd_data, rd_esp],  # list_all_block_devices raid + md
            [sda, sdb],  # list_all_block_devices disks
            partitions,  # list_all_block_devices parts
            [rd_root, rd_data, rd_esp],  # list_all_block_devices raid + md
        ]
        mocked_get_volume_name.side_effect = [
            'root', 'data', 'esp'
        ]

        mocked_get_holder.side_effect = [
            ['/dev/sda', '/dev/sdb'],  # md0 handle raid skip list
            ['/dev/sda', '/dev/sdb'],  # md1 handle raid skip list
            ['/dev/sda', '/dev/sdb'],  # md2 handle raid skip list
            ['/dev/sda', '/dev/sdb'],  # data handle raid skip list
            ['/dev/sda', '/dev/sdb'],  # md0 delete config pass
            ['/dev/sda', '/dev/sdb'],  # md1 delete config pass
            ['/dev/sda', '/dev/sdb'],  # md2 delete config pass
        ]
        mocked_get_components.side_effect = [
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sda2', '/dev/sdb2'],
            ['/dev/sda3', '/dev/sdb3'],
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sda2', '/dev/sdb2'],
            ['/dev/sda3', '/dev/sdb3'],
        ]
        mocked_get_skip_list.return_value = set({'data'})

        self.hardware.delete_configuration(self.node, [])
        mocked_list.assert_has_calls([
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
            mock.call(all_serial_and_wwn=False),
            mock.call(block_type='part', ignore_raid=True),
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
        ])
        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('wipefs', '-af', '/dev/md0'),  # wipe root
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False)])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_skip_list_from_node_for_raids', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration_skip_list_root_weirdly_placed_with_data(
            self, mocked_execute, mocked_list, mocked_get_components,
            mocked_get_holder, mocked_get_skip_list, mocked_get_volume_name):
        # Please note that this test case is solely for testing purposes
        # and does not make sense in real deployments.
        # There are two RAID arrays: root and data
        # - root spans 100GB on 2 disks present on the node
        # - data spans the rest of 1 of those disks and most of a third disk
        #   and it is in skip list
        # The data should be untouched, the root should be wiped,
        # but not deleted
        sda = hardware.BlockDevice('/dev/sda', 'sda', 1073741824000, True)
        sdb = hardware.BlockDevice('/dev/sdb', 'sdb', 1073741824000, True)
        sdc = hardware.BlockDevice('/dev/sdc', 'sdc', 1073741824000, True)
        rd_root = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                       107374182400, True)
        rd_data = hardware.BlockDevice('/dev/md1', 'RAID-1',
                                       966367641600, True)
        partitions = [
            hardware.BlockDevice('/dev/sda1', 'raid-member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sdb1', 'raid-member', 107374182400,
                                 False),
            hardware.BlockDevice('/dev/sdb2', 'raid-member', 966367641600,
                                 False),
            hardware.BlockDevice('/dev/sdc1', 'raid_member', 966367641600,
                                 False),
        ]

        mocked_list.side_effect = [
            [rd_root, rd_data],  # list_all_block_devices raid + md
            [sda, sdb, sdc],  # list_all_block_devices disks
            partitions,  # list_all_block_devices parts
            [rd_root, rd_data],  # list_all_block_devices raid + md
        ]
        mocked_get_volume_name.side_effect = [
            'root', 'data'
        ]

        mocked_get_holder.side_effect = [
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sdb', '/dev/sdc'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sdb', '/dev/sdc'],
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sdb', '/dev/sdc'],
        ]
        mocked_get_components.side_effect = [
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sdb2', '/dev/sdc1'],
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sdb2', '/dev/sdc1'],
        ]
        mocked_get_skip_list.return_value = set({'data'})

        self.hardware.delete_configuration(self.node, [])
        mocked_list.assert_has_calls([
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
            mock.call(all_serial_and_wwn=False),
            mock.call(block_type='part', ignore_raid=True),
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
        ])
        mocked_execute.assert_has_calls([
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            mock.call('wipefs', '-af', '/dev/md0'),  # wipe root
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False)])

    @mock.patch.object(raid_utils, 'get_volume_name_of_raid_device',
                       autospec=True)
    @mock.patch.object(hardware.GenericHardwareManager,
                       'get_skip_list_from_node_for_raids', autospec=True)
    @mock.patch.object(hardware, 'get_holder_disks', autospec=True)
    @mock.patch.object(hardware, 'get_component_devices', autospec=True)
    @mock.patch.object(hardware, 'list_all_block_devices', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_delete_configuration_skip_list_separated_raid_volumes_with_uefi(
            self, mocked_execute, mocked_list_all_block_devices,
            mocked_get_components, mocked_get_holder, mocked_get_skip_list,
            mocked_get_volume_name):
        # Three raid volumes: 'root', 'data' and 'esp' (EFI System Partition).
        # 'data' is a raid1 on sda and sdb (it should not be deleted)
        # 'root' and 'esp' are both raid1 and they share sdc and sdd
        # both 'root' and 'esp' should be deleted
        sda = hardware.BlockDevice('/dev/sda', 'sda', 1073741824000, True)
        sdb = hardware.BlockDevice('/dev/sdb', 'sdb', 1073741824000, True)
        sdc = hardware.BlockDevice('/dev/sdc', 'sdc', 1073741824000, True)
        sdd = hardware.BlockDevice('/dev/sdd', 'sdd', 1073741824000, True)
        rd_data = hardware.BlockDevice('/dev/md0', 'RAID-1',
                                       1073741824000, True)
        rd_root = hardware.BlockDevice('/dev/md1', 'RAID-1',
                                       1073741823488, True)
        rd_esp = hardware.BlockDevice('/dev/md2', 'RAID-1',
                                      512, True)
        partitions = [
            hardware.BlockDevice('/dev/sda1', 'raid-member', 1073741824000,
                                 False),
            hardware.BlockDevice('/dev/sdb1', 'raid-member', 1073741824000,
                                 False),
            hardware.BlockDevice('/dev/sdc1', 'raid-member', 1073741823488,
                                 False),
            hardware.BlockDevice('/dev/sdd1', 'raid-member', 1073741823488,
                                 False),
            hardware.BlockDevice('/dev/sdc2', 'raid-member', 512,
                                 False),
            hardware.BlockDevice('/dev/sdd2', 'raid-member', 512,
                                 False)
        ]
        self.hardware.list_block_devices = mock.Mock()
        self.hardware.list_block_devices.return_value = [
            sda, sdb, sdc, sdd, partitions[0], partitions[1],  # disk + part
            partitions[2], partitions[3], partitions[4], partitions[5]
        ]

        mocked_list_all_block_devices.side_effect = [
            # scan_raids - before deletion
            [rd_data, rd_root, rd_esp],  # block type raid + md
            # scan_raids - after deletion
            [rd_data],  # block type raid + md
        ]

        mocked_get_volume_name.side_effect = [
            'data', 'root', 'esp'
        ]

        mocked_get_holder.side_effect = [
            # _handle_skip_raid_devices
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sdc', '/dev/sdd'],
            ['/dev/sdc', '/dev/sdd'],
            ['/dev/sda', '/dev/sdb'],
            # _delete_config_pass
            ['/dev/sda', '/dev/sdb'],
            ['/dev/sdc', '/dev/sdd'],
            ['/dev/sdc', '/dev/sdd'],

        ]
        mocked_get_components.side_effect = [
            # _delete_config_pass
            ['/dev/sda1', '/dev/sdb1'],
            ['/dev/sdc1', '/dev/sdd1'],
            ['/dev/sdc2', '/dev/sdd2']

        ]
        mocked_get_skip_list.return_value = set({'data'})

        self.hardware.delete_configuration(self.node, [])

        assert mocked_list_all_block_devices.call_count == 2
        mocked_list_all_block_devices.assert_has_calls([
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
            mock.call(block_type=['raid', 'md'], ignore_raid=False,
                      ignore_empty=False),
        ])
        mocked_execute.assert_has_calls([
            # Scan raids
            mock.call('mdadm', '--assemble', '--scan', check_exit_code=False),
            # Delete root
            mock.call('wipefs', '-af', '/dev/md1'),
            mock.call('mdadm', '--stop', '/dev/md1'),
            mock.call('mdadm', '--examine', '/dev/sdc1',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdc1'),
            mock.call('mdadm', '--examine', '/dev/sdd1',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdd1'),
            # Delete esp
            mock.call('wipefs', '-af', '/dev/md2'),
            mock.call('mdadm', '--stop', '/dev/md2'),
            mock.call('mdadm', '--examine', '/dev/sdc2',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdc2'),
            mock.call('mdadm', '--examine', '/dev/sdd2',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdd2'),
            # Remove remaining raid traces from disks
            mock.call('mdadm', '--examine', '/dev/sdd2',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdd2'),
            mock.call('mdadm', '--examine', '/dev/sdc2',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdc2'),
            mock.call('mdadm', '--examine', '/dev/sdd1',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdd1'),
            mock.call('mdadm', '--examine', '/dev/sdc1',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdc1'),
            mock.call('mdadm', '--examine', '/dev/sdd',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdd'),
            mock.call('mdadm', '--examine', '/dev/sdc',
                      use_standard_locale=True),
            mock.call('mdadm', '--zero-superblock', '/dev/sdc'),
            # Wipe fs on non-saved disks
            mock.call('wipefs', '-af', '/dev/sdc'),
            mock.call('wipefs', '-af', '/dev/sdd'),
            # Scan raids
            mock.call('mdadm', '--assemble', '--scan',
                      check_exit_code=False)
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_valid_raid1(self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                },
            ]
        }
        self.assertIsNone(self.hardware.validate_configuration(raid_config,
                                                               self.node))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_valid_raid1_raidN(self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        mocked_execute.return_value = (hws.RAID_BLK_DEVICE_TEMPLATE, '')
        self.assertIsNone(self.hardware.validate_configuration(raid_config,
                                                               self.node))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_valid_root_volume(
            self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "is_root_volume": True,
                    "controller": "software",
                    "volume_name": "root"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "volume_name": "data"
                },
            ]
        }
        mocked_execute.return_value = (hws.RAID_BLK_DEVICE_TEMPLATE, '')
        self.assertIsNone(self.hardware.validate_configuration(raid_config,
                                                               self.node))

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_invalid_MAX_MAX(self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
            ]
        }
        mocked_execute.return_value = (hws.RAID_BLK_DEVICE_TEMPLATE, '')
        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.validate_configuration,
                          raid_config, self.node)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_invalid_raid_level(self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "42",
                    "controller": "software",
                },
            ]
        }
        mocked_execute.return_value = (hws.RAID_BLK_DEVICE_TEMPLATE, '')
        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.validate_configuration,
                          raid_config, self.node)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_invalid_no_of_raids(self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "MAX",
                    "raid_level": "1",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "1+0",
                    "controller": "software",
                },
            ]
        }
        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.validate_configuration,
                          raid_config, self.node)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_invalid_duplicate_volume_name(
            self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "controller": "software",
                    "volume_name": "thedisk"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "controller": "software",
                    "volume_name": "thedisk"
                },
            ]
        }
        mocked_execute.return_value = (hws.RAID_BLK_DEVICE_TEMPLATE, '')
        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.validate_configuration,
                          raid_config, self.node)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_validate_configuration_invalid_multiple_root_volumes(
            self, mocked_execute):
        raid_config = {
            "logical_disks": [
                {
                    "size_gb": "100",
                    "raid_level": "1",
                    "is_root_volume": True,
                    "controller": "software",
                    "volume_name": "root"
                },
                {
                    "size_gb": "MAX",
                    "raid_level": "0",
                    "is_root_volume": True,
                    "controller": "software",
                    "volume_name": "data"
                },
            ]
        }
        mocked_execute.return_value = (hws.RAID_BLK_DEVICE_TEMPLATE, '')
        self.assertRaises(errors.SoftwareRAIDError,
                          self.hardware.validate_configuration,
                          raid_config, self.node)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_system_vendor_info(self, mocked_execute):
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_V1
        vendor_info = self.hardware.get_system_vendor_info()
        self.assertEqual('ABC123 (GENERIC_SERVER)', vendor_info.product_name)
        self.assertEqual('1234567', vendor_info.serial_number)
        self.assertEqual('GENERIC', vendor_info.manufacturer)
        # This sample does not have firmware information
        self.assertEqual('', vendor_info.firmware.vendor)
        self.assertEqual('', vendor_info.firmware.build_date)
        self.assertEqual('', vendor_info.firmware.version)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_system_vendor_info_lshw_list(self, mocked_execute):
        mocked_execute.return_value = (f"[{hws.LSHW_JSON_OUTPUT_V2[0]}]", "")
        vendor_info = self.hardware.get_system_vendor_info()
        self.assertEqual('ABCD', vendor_info.product_name)
        self.assertEqual('1234', vendor_info.serial_number)
        self.assertEqual('ABCD', vendor_info.manufacturer)
        self.assertEqual('BIOSVNDR', vendor_info.firmware.vendor)
        self.assertEqual('03/30/2023', vendor_info.firmware.build_date)
        self.assertEqual('1.2.3', vendor_info.firmware.version)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_system_vendor_info_failure(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        vendor_info = self.hardware.get_system_vendor_info()
        self.assertEqual('', vendor_info.product_name)
        self.assertEqual('', vendor_info.serial_number)
        self.assertEqual('', vendor_info.manufacturer)
        self.assertEqual('', vendor_info.firmware.vendor)
        self.assertEqual('', vendor_info.firmware.build_date)
        self.assertEqual('', vendor_info.firmware.version)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_usb_devices(self, mocked_execute):

        device = hardware.USBInfo('MyProduct', 'MyVendor', 'USB:1:2')

        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_V1
        detected_usb_devices = self.hardware.get_usb_devices()

        self.assertEqual([device], detected_usb_devices)

    @mock.patch.object(hardware.GenericHardwareManager, 'filter_device',
                       autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_usb_devices_with_filter_device(self, mocked_execute,
                                                mocked_filter):
        seen_devices = set()
        device = hardware.USBInfo('MyProduct', 'MyVendor', 'USB:1:2')

        def _filter(hwmgr, device_to_filter):
            self.assertIsInstance(device_to_filter, hardware.USBInfo)
            self.assertEqual(device, device_to_filter)
            seen_devices.add(device_to_filter.product)
            return None

        mocked_filter.side_effect = _filter
        mocked_execute.return_value = hws.LSHW_JSON_OUTPUT_V1
        detected_usb_devices = self.hardware.get_usb_devices()

        self.assertEqual([], detected_usb_devices)
        self.assertEqual({'MyProduct'}, seen_devices)

    @mock.patch.object(utils, 'get_agent_params',
                       lambda: {'BOOTIF': 'boot:if'})
    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_get_boot_info_pxe_interface(self, mocked_isdir):
        mocked_isdir.return_value = False
        result = self.hardware.get_boot_info()
        self.assertEqual(hardware.BootInfo(current_boot_mode='bios',
                                           pxe_interface='boot:if'),
                         result)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_get_boot_info_bios(self, mocked_isdir):
        mocked_isdir.return_value = False
        result = self.hardware.get_boot_info()
        self.assertEqual(hardware.BootInfo(current_boot_mode='bios'), result)
        mocked_isdir.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_get_boot_info_uefi(self, mocked_isdir):
        mocked_isdir.return_value = True
        result = self.hardware.get_boot_info()
        self.assertEqual(hardware.BootInfo(current_boot_mode='uefi'), result)
        mocked_isdir.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_nvme_crypto_success(self, mocked_execute,
                                                    mocked_raid_member):
        info = self.node['driver_internal_info']
        info['agent_enable_nvme_erase'] = True
        info['agent_continue_if_secure_erase_failed'] = True
        mocked_raid_member.return_value = False
        mocked_execute.side_effect = [
            (hws.NVME_CLI_INFO_TEMPLATE_CRYPTO_SUPPORTED, ''),
            ('', ''),
        ]

        block_device = hardware.BlockDevice('/dev/nvme0n1', "testdisk",
                                            1073741824, False)
        retval = self.hardware._nvme_erase(block_device)
        mocked_execute.assert_has_calls([
            mock.call('nvme', 'id-ctrl', '/dev/nvme0n1', '-o', 'json'),
            mock.call('nvme', 'format', '/dev/nvme0n1', '-s', 2, '-f'),
        ])

        self.assertTrue(retval)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_nvme_userdata_success(self, mocked_execute,
                                                      mocked_raid_member):
        info = self.node['driver_internal_info']
        info['agent_enable_nvme_erase'] = True
        info['agent_continue_if_secure_erase_failed'] = True
        mocked_raid_member.return_value = False
        mocked_execute.side_effect = [
            (hws.NVME_CLI_INFO_TEMPLATE_USERDATA_SUPPORTED, ''),
            ('', ''),
        ]

        block_device = hardware.BlockDevice('/dev/nvme0n1', "testdisk",
                                            1073741824, False)
        retval = self.hardware._nvme_erase(block_device)
        mocked_execute.assert_has_calls([
            mock.call('nvme', 'id-ctrl', '/dev/nvme0n1', '-o', 'json'),
            mock.call('nvme', 'format', '/dev/nvme0n1', '-s', 1, '-f'),
        ])

        self.assertTrue(retval)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_nvme_failed(self, mocked_execute,
                                            mocked_raid_member):
        info = self.node['driver_internal_info']
        info['agent_enable_nvme_erase'] = True
        mocked_raid_member.return_value = False
        mocked_execute.side_effect = [
            (hws.NVME_CLI_INFO_TEMPLATE_CRYPTO_SUPPORTED, ''),
            (processutils.ProcessExecutionError()),
        ]

        block_device = hardware.BlockDevice('/dev/nvme0n1', "testdisk",
                                            1073741824, False)
        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._nvme_erase, block_device)

    @mock.patch.object(hardware.GenericHardwareManager,
                       '_is_linux_raid_member', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_erase_block_device_nvme_format_unsupported(self, mocked_execute,
                                                        mocked_raid_member):
        info = self.node['driver_internal_info']
        info['agent_enable_nvme_erase'] = True
        mocked_raid_member.return_value = False
        mocked_execute.side_effect = [
            (hws.NVME_CLI_INFO_TEMPLATE_FORMAT_UNSUPPORTED, ''),
        ]

        block_device = hardware.BlockDevice('/dev/nvme0n1', "testdisk",
                                            1073741824, False)
        self.assertRaises(errors.BlockDeviceEraseError,
                          self.hardware._nvme_erase, block_device)


@mock.patch.object(hardware, '_enable_multipath', autospec=True)
@mock.patch.object(hardware, '_load_ipmi_modules', autospec=True)
@mock.patch.object(hardware.GenericHardwareManager,
                   'get_os_install_device', autospec=True)
@mock.patch.object(hardware, '_md_scan_and_assemble', autospec=True)
@mock.patch.object(hardware, '_check_for_iscsi', autospec=True)
@mock.patch.object(time, 'sleep', autospec=True)
class TestInitializeSupport(base.IronicAgentTest):
    def setUp(self):
        super().setUp()
        self.hardware = hardware.GenericHardwareManager()

    def test_initialize_waits_for_disks(
            self, mocked_sleep, mocked_check_for_iscsi,
            mocked_md_assemble, mocked_get_inst_dev,
            mocked_load_ipmi_modules, mocked_enable_mpath):
        mocked_get_inst_dev.side_effect = [
            errors.DeviceNotFound('boom'),
            None
        ]

        self.hardware.initialize()

        self.assertTrue(mocked_load_ipmi_modules.called)
        self.assertTrue(mocked_check_for_iscsi.called)
        self.assertTrue(mocked_md_assemble.called)
        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(2, mocked_get_inst_dev.call_count)
        mocked_sleep.assert_called_once_with(CONF.disk_wait_delay)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    def test_initialize_no_wait_for_disks(
            self, mocked_log, mocked_sleep, mocked_check_for_iscsi,
            mocked_md_assemble, mocked_get_inst_dev,
            mocked_load_ipmi_modules, mocked_enable_mpath):
        CONF.set_override('disk_wait_attempts', '0')

        self.hardware.initialize()

        self.assertTrue(mocked_check_for_iscsi.called)
        self.assertFalse(mocked_get_inst_dev.called)
        self.assertFalse(mocked_sleep.called)
        self.assertFalse(mocked_log.called)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    def test_initialize_waits_for_disks_nonconfigured(
            self, mocked_log, mocked_sleep, mocked_check_for_iscsi,
            mocked_md_assemble, mocked_get_inst_dev,
            mocked_load_ipmi_modules, mocked_enable_mpath):
        mocked_get_inst_dev.side_effect = [
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            None
        ]

        self.hardware.initialize()

        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(10, mocked_get_inst_dev.call_count)
        expected_calls = [mock.call(CONF.disk_wait_delay)] * 9
        mocked_sleep.assert_has_calls(expected_calls)
        mocked_log.warning.assert_called_once_with(
            'The root device was not detected in %d seconds',
            CONF.disk_wait_delay * 9)

    @mock.patch.object(hardware, 'LOG', autospec=True)
    def test_initialize_waits_for_disks_configured(self, mocked_log,
                                                   mocked_sleep,
                                                   mocked_check_for_iscsi,
                                                   mocked_md_assemble,
                                                   mocked_get_inst_dev,
                                                   mocked_load_ipmi_modules,
                                                   mocked_enable_mpath):
        CONF.set_override('disk_wait_attempts', '1')

        mocked_get_inst_dev.side_effect = [
            errors.DeviceNotFound('boom'),
            errors.DeviceNotFound('boom'),
            None
        ]

        self.hardware.initialize()

        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(1, mocked_get_inst_dev.call_count)
        self.assertFalse(mocked_sleep.called)
        mocked_log.warning.assert_called_once_with(
            'The root device was not detected')

    def test_initialize_disks_timeout_unconfigured(self, mocked_sleep,
                                                   mocked_check_for_iscsi,
                                                   mocked_md_assemble,
                                                   mocked_get_inst_dev,
                                                   mocked_load_ipmi_modules,
                                                   mocked_enable_mpath):
        mocked_get_inst_dev.side_effect = errors.DeviceNotFound('boom')
        self.hardware.initialize()
        mocked_sleep.assert_called_with(3)

    def test_initialize_disks_timeout_configured(self, mocked_sleep,
                                                 mocked_check_for_iscsi,
                                                 mocked_md_assemble,
                                                 mocked_root_dev,
                                                 mocked_load_ipmi_modules,
                                                 mocked_enable_mpath):
        CONF.set_override('disk_wait_delay', '5')
        mocked_root_dev.side_effect = errors.DeviceNotFound('boom')

        self.hardware.initialize()
        mocked_sleep.assert_called_with(5)

    def test_initialize_disks_timeout(
            self, mocked_sleep, mocked_check_for_iscsi,
            mocked_md_assemble, mocked_get_inst_dev,
            mocked_load_ipmi_modules,
            mocked_enable_mpath):
        mocked_get_inst_dev.side_effect = errors.DeviceNotFound('boom')
        self.hardware.initialize()
        mocked_get_inst_dev.assert_called_with(mock.ANY)
        self.assertEqual(CONF.disk_wait_attempts,
                         mocked_get_inst_dev.call_count)
        mocked_sleep.assert_called_with(CONF.disk_wait_delay)


@mock.patch.object(os, 'listdir', lambda *_: [])
@mock.patch.object(utils, 'execute', autospec=True)
class TestModuleFunctions(base.IronicAgentTest):

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(hardware, '_get_device_info',
                       lambda x, y, z: 'FooTastic')
    @mock.patch.object(disk_utils, 'udev_settle', autospec=True)
    @mock.patch.object(hardware.pyudev.Devices, "from_device_file",
                       autospec=False)
    def test_list_all_block_devices_success(self, mocked_fromdevfile,
                                            mocked_udev, mocked_readlink,
                                            mocked_mpath, mocked_execute):
        mocked_mpath.return_value = True
        mocked_readlink.return_value = '../../sda'
        mocked_fromdevfile.return_value = {}
        mocked_execute.side_effect = [
            (hws.BLK_DEVICE_TEMPLATE_SMALL, ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb'),
        ]
        result = hardware.list_all_block_devices()
        expected_calls = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
            mock.call('multipath', '-c', '/dev/sda'),
            mock.call('multipath', '-c', '/dev/sdb')
        ]

        mocked_execute.assert_has_calls(expected_calls)
        self.assertEqual(BLK_DEVICE_TEMPLATE_SMALL_DEVICES, result)
        mocked_udev.assert_called_once_with()
        mocked_mpath.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(hardware, '_get_device_info',
                       lambda x, y, z: 'FooTastic')
    @mock.patch.object(disk_utils, 'udev_settle', autospec=True)
    @mock.patch.object(hardware.pyudev.Devices, "from_device_file",
                       autospec=False)
    def test_list_all_block_devices_success_raid(self, mocked_fromdevfile,
                                                 mocked_udev, mocked_readlink,
                                                 mocked_mpath, mocked_execute):
        mocked_readlink.return_value = '../../sda'
        mocked_fromdevfile.return_value = {}
        mocked_mpath.return_value = True
        mocked_execute.side_effect = [
            (hws.RAID_BLK_DEVICE_TEMPLATE, ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda1'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb1'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # md0p1
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # md0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # md0
            processutils.ProcessExecutionError(
                stderr='the -c option requires a path to check'),  # md1
        ]
        expected_calls = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
            mock.call('multipath', '-c', '/dev/sda'),
            mock.call('multipath', '-c', '/dev/sda1'),
            mock.call('multipath', '-c', '/dev/sdb'),
            mock.call('multipath', '-c', '/dev/sdb1'),
            mock.call('multipath', '-c', '/dev/md0p1'),
            mock.call('multipath', '-c', '/dev/md0'),
            mock.call('multipath', '-c', '/dev/md1'),
        ]
        result = hardware.list_all_block_devices(ignore_empty=False)
        mocked_execute.assert_has_calls(expected_calls)
        self.assertEqual(RAID_BLK_DEVICE_TEMPLATE_DEVICES, result)
        mocked_udev.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(os, 'readlink', autospec=True)
    @mock.patch.object(hardware, '_get_device_info',
                       lambda x, y, z: 'FooTastic')
    @mock.patch.object(disk_utils, 'udev_settle', autospec=True)
    @mock.patch.object(hardware.pyudev.Devices, "from_device_file",
                       autospec=False)
    def test_list_all_block_devices_partuuid_success(
            self, mocked_fromdevfile,
            mocked_udev, mocked_readlink,
            mocked_mpath, mocked_execute):
        mocked_readlink.return_value = '../../sda'
        mocked_fromdevfile.return_value = {}
        mocked_mpath.return_value = True
        mocked_execute.side_effect = [
            (hws.PARTUUID_DEVICE_TEMPLATE, ''),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sda'),
            processutils.ProcessExecutionError(
                stderr=hws.MULTIPATH_INVALID_PATH % '/dev/sdb'),
        ]
        result = hardware.list_all_block_devices(block_type='part')
        expected_calls = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
            mock.call('multipath', '-c', '/dev/sda'),
            mock.call('multipath', '-c', '/dev/sda1'),
        ]
        mocked_execute.assert_has_calls(expected_calls)
        self.assertEqual(BLK_DEVICE_TEMPLATE_PARTUUID_DEVICE, result)
        mocked_udev.assert_called_once_with()
        mocked_mpath.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(hardware, '_get_device_info',
                       lambda x, y: "FooTastic")
    @mock.patch.object(disk_utils, 'udev_settle', autospec=True)
    def test_list_all_block_devices_wrong_block_type(self, mocked_udev,
                                                     mock_mpath_enabled,
                                                     mocked_execute):
        mock_mpath_enabled.return_value = False
        mocked_execute.return_value = (
            '{"blockdevices": [{"type":"foo", "model":"model"}]}', '')
        result = hardware.list_all_block_devices()
        mocked_execute.assert_called_once_with(
            'lsblk', '-bia', '--json',
            '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
            'LOG-SEC,PHY-SEC,TRAN',
            check_exit_code=[0])
        self.assertEqual([], result)
        mocked_udev.assert_called_once_with()

    @mock.patch.object(hardware, 'get_multipath_status', autospec=True)
    @mock.patch.object(disk_utils, 'udev_settle', autospec=True)
    def test_list_all_block_devices_missing(self, mocked_udev,
                                            mocked_mpath,
                                            mocked_execute):
        """Test for missing values returned from lsblk"""
        mocked_mpath.return_value = False
        expected_calls = [
            mock.call('lsblk', '-bia', '--json',
                      '-oKNAME,MODEL,SIZE,ROTA,TYPE,UUID,PARTUUID,SERIAL,WWN,'
                      'LOG-SEC,PHY-SEC,TRAN',
                      check_exit_code=[0]),
        ]
        mocked_execute.return_value = (
            '{"blockdevices": [{"type":"disk", "model":"model"}]}', '')
        self.assertRaisesRegex(
            errors.BlockDeviceError,
            r'Block device caused unknown error: kname, log-sec, partuuid, '
            r'phy-sec, rota, serial, size, tran, uuid, wwn '
            r'must be returned by lsblk.',
            hardware.list_all_block_devices)
        mocked_udev.assert_called_once_with()
        mocked_execute.assert_has_calls(expected_calls)

    def test__check_for_iscsi(self, mocked_execute):
        hardware._check_for_iscsi()
        mocked_execute.assert_has_calls([
            mock.call('iscsistart', '-f'),
            mock.call('iscsistart', '-b')])

    def test__check_for_iscsi_no_iscsi(self, mocked_execute):
        mocked_execute.side_effect = processutils.ProcessExecutionError()
        hardware._check_for_iscsi()
        mocked_execute.assert_has_calls([
            mock.call('iscsistart', '-f')])

    @mock.patch.object(processutils, 'execute', autospec=True)
    def test__load_ipmi_modules(self, mocked_proc_execute, mocked_execute):
        hardware._load_ipmi_modules()
        mocked_proc_execute.assert_has_calls([
            mock.call('modprobe', 'ipmi_msghandler'),
            mock.call('modprobe', 'ipmi_devintf'),
            mock.call('modprobe', 'ipmi_si')])

    @mock.patch.object(hardware, 'LOG', autospec=True)
    @mock.patch.object(processutils, 'execute', autospec=True)
    def test__load_ipmi_modules_fail(self, mocked_proc_execute, mocked_log,
                                     mocked_execute):
        mocked_proc_execute.side_effect = [
            processutils.ProcessExecutionError,
            ('', ''),
            ('', ''),
        ]
        hardware._load_ipmi_modules()
        mocked_proc_execute.assert_has_calls([
            mock.call('modprobe', 'ipmi_msghandler'),
            mock.call('modprobe', 'ipmi_devintf'),
            mock.call('modprobe', 'ipmi_si')])
        mocked_log.debug.assert_called_once()


@mock.patch.object(utils, 'execute', autospec=True)
class TestMultipathEnabled(base.IronicAgentTest):

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_enable_multipath_with_config(self, mock_isfile, mocked_execute):
        mock_isfile.side_effect = [True, True]
        mocked_execute.side_effect = [
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
        ]
        self.assertTrue(hardware._enable_multipath())
        mocked_execute.assert_has_calls([
            mock.call('modprobe', 'dm_multipath'),
            mock.call('modprobe', 'multipath'),
            mock.call('multipathd'),
            mock.call('multipath', '-ll'),
        ])

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_enable_multipath_already_running(self,
                                              mock_isfile,
                                              mocked_execute):
        mock_isfile.side_effect = [True, True]
        mocked_execute.side_effect = [
            ('', ''),
            ('', ''),
            (OSError),
            ('', ''),
        ]
        self.assertTrue(hardware._enable_multipath())
        self.assertEqual(4, mocked_execute.call_count)
        mocked_execute.assert_has_calls([
            mock.call('modprobe', 'dm_multipath'),
            mock.call('modprobe', 'multipath'),
            mock.call('multipathd'),
            mock.call('multipath', '-ll'),
        ])

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_enable_multipath_ll_fails(self,
                                       mock_isfile,
                                       mocked_execute):
        mock_isfile.side_effect = [True, True]
        mocked_execute.side_effect = [
            ('', ''),
            ('', ''),
            ('', ''),
            (OSError),
        ]
        self.assertFalse(hardware._enable_multipath())
        self.assertEqual(4, mocked_execute.call_count)
        mocked_execute.assert_has_calls([
            mock.call('modprobe', 'dm_multipath'),
            mock.call('modprobe', 'multipath'),
            mock.call('multipathd'),
            mock.call('multipath', '-ll'),
        ])

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_enable_multipath_mpathconf(self, mock_isfile, mocked_execute):
        mock_isfile.side_effect = [True, False]
        mocked_execute.side_effect = [
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
        ]
        self.assertTrue(hardware._enable_multipath())
        mocked_execute.assert_has_calls([
            mock.call('/usr/sbin/mpathconf', '--enable',
                      '--find_multipaths', 'yes',
                      '--with_module', 'y',
                      '--with_multipathd', 'y'),
            mock.call('multipathd'),
            mock.call('multipath', '-ll'),
        ])

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_enable_multipath_no_multipath(self, mock_isfile, mocked_execute):
        mock_isfile.return_value = False
        mocked_execute.side_effect = [
            ('', ''),
            ('', ''),
            ('', ''),
            ('', ''),
        ]
        self.assertTrue(hardware._enable_multipath())
        mocked_execute.assert_has_calls([
            mock.call('modprobe', 'dm_multipath'),
            mock.call('modprobe', 'multipath'),
            mock.call('multipathd'),
            mock.call('multipath', '-ll'),
        ])

    @mock.patch.object(hardware, '_load_multipath_modules', autospec=True)
    @mock.patch.object(utils, 'try_execute', autospec=True)
    def test_enable_multipath_not_found_mpath_config(self,
                                                     mock_try_exec,
                                                     mock_modules,
                                                     mocked_execute):
        mock_modules.side_effect = FileNotFoundError()
        self.assertFalse(hardware._enable_multipath())
        self.assertEqual(1, mock_modules.call_count)
        self.assertEqual(0, mock_try_exec.call_count)

    @mock.patch.object(hardware, '_load_multipath_modules', autospec=True)
    def test_enable_multipath_lacking_support(self,
                                              mock_modules,
                                              mocked_execute):
        mocked_execute.side_effect = [
            ('', ''),  # Help will of course work.
            processutils.ProcessExecutionError('lacking kernel support')
        ]
        self.assertFalse(hardware._enable_multipath())
        self.assertEqual(2, mocked_execute.call_count)
        self.assertEqual(1, mock_modules.call_count)


def create_hdparm_info(supported=False, enabled=False, locked=False,
                       frozen=False, enhanced_erase=False):

    def update_values(values, state, key):
        if not state:
            values[key] = 'not' + values[key]

    values = {
        'supported': '\tsupported',
        'enabled': '\tenabled',
        'locked': '\tlocked',
        'frozen': '\tfrozen',
        'enhanced_erase': '\tsupported: enhanced erase',
    }

    update_values(values, supported, 'supported')
    update_values(values, enabled, 'enabled')
    update_values(values, locked, 'locked')
    update_values(values, frozen, 'frozen')
    update_values(values, enhanced_erase, 'enhanced_erase')

    return hws.HDPARM_INFO_TEMPLATE % values


@mock.patch('ironic_python_agent.hardware.dispatch_to_all_managers',
            autospec=True)
class TestVersions(base.IronicAgentTest):
    version = {'generic': '1', 'specific': '1'}

    def test_get_current_versions(self, mock_dispatch):
        mock_dispatch.return_value = {'SpecificHardwareManager':
                                      {'name': 'specific', 'version': '1'},
                                      'GenericHardwareManager':
                                      {'name': 'generic', 'version': '1'}}
        self.assertEqual(self.version, hardware.get_current_versions())

    def test_check_versions(self, mock_dispatch):
        mock_dispatch.return_value = {'SpecificHardwareManager':
                                      {'name': 'specific', 'version': '1'}}

        self.assertRaises(errors.VersionMismatch,
                          hardware.check_versions,
                          {'not_specific': '1'})


@mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
            autospec=True)
class TestListHardwareInfo(base.IronicAgentTest):

    def test_caching(self, mock_dispatch):
        fake_info = {'I am': 'hardware'}
        mock_dispatch.return_value = fake_info

        self.assertEqual(fake_info, hardware.list_hardware_info())
        self.assertEqual(fake_info, hardware.list_hardware_info())
        mock_dispatch.assert_called_once_with('list_hardware_info')

        self.assertEqual(fake_info,
                         hardware.list_hardware_info(use_cache=False))
        self.assertEqual(fake_info, hardware.list_hardware_info())
        mock_dispatch.assert_called_with('list_hardware_info')
        self.assertEqual(2, mock_dispatch.call_count)


class TestAPIClientSaveAndUse(base.IronicAgentTest):

    def test_save_api_client(self):
        hardware.API_CLIENT = None
        mock_api_client = mock.Mock()
        hardware.save_api_client(mock_api_client, 1, 2)
        self.assertEqual(mock_api_client, hardware.API_CLIENT)

    @mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
                autospec=True)
    @mock.patch.object(hardware, 'get_cached_node', autospec=True)
    def test_update_node_cache(self, mock_cached_node, mock_dispatch):
        mock_cached_node.return_value = {'uuid': 'node1'}
        updated_node = {'uuid': 'node1', 'other': 'key'}
        hardware.API_CLIENT = None
        mock_api_client = mock.Mock()
        hardware.save_api_client(mock_api_client, 1, 2)
        mock_api_client.lookup_node.return_value = {'node': updated_node}
        self.assertEqual(updated_node, hardware.update_cached_node())
        mock_api_client.lookup_node.assert_called_with(
            hardware_info=mock.ANY,
            timeout=1,
            starting_interval=2,
            node_uuid='node1')
        self.assertEqual(updated_node, hardware.NODE)
        calls = [mock.call('list_hardware_info'),
                 mock.call('wait_for_disks')]
        mock_dispatch.assert_has_calls(calls)


@mock.patch.object(utils, 'execute', autospec=True)
class TestProtectedDiskSafetyChecks(base.IronicAgentTest):

    def test_special_filesystem_guard_not_enabled(self, mock_execute):
        CONF.set_override('guard_special_filesystems', False)
        hardware.safety_check_block_device({}, '/dev/foo')
        mock_execute.assert_not_called()

    def test_special_filesystem_guard_node_indicates_skip(self, mock_execute):
        node = {
            'driver_internal_info': {
                'wipe_special_filesystems': False
            }
        }
        mock_execute.return_value = ('', '')
        hardware.safety_check_block_device(node, '/dev/foo')
        mock_execute.assert_not_called()

    def test_special_filesystem_guard_enabled_no_results(self, mock_execute):
        mock_execute.return_value = ('{"blockdevices": [{"foo": "bar"}]}', '')
        hardware.safety_check_block_device({}, '/dev/foo')

    def test_special_filesystem_guard_raises(self, mock_execute):
        GFS2 = '"fstype": "gfs2"'
        GPFS1 = '"uuid": "37AFFC90-EF7D-4E96-91C3-2D7AE055B174"'
        GPFS2 = '"ptuuid": "37AFFC90-EF7D-4E96-91C3-2D7AE055B174"'
        GPFS3 = '"parttype": "37AFFC90-EF7D-4E96-91C3-2D7AE055B174"'
        GPFS4 = '"partuuid": "37AFFC90-EF7D-4E96-91C3-2D7AE055B174"'
        VMFS1 = '"uuid": "AA31E02A-400F-11DB-9590-000C2911D1B8"'
        VMFS2 = '"uuid": "AA31E02A-400F-11DB-9590-000C2911D1B8"'
        VMFS3 = '"uuid": "AA31E02A-400F-11DB-9590-000C2911D1B8"'
        VMFS4 = '"uuid": "AA31E02A-400F-11DB-9590-000C2911D1B8"'
        VMFS5 = '"uuid": "0xfb"'
        VMFS6 = '"ptuuid": "0xfb"'
        VMFS7 = '"parttype": "0xfb"'
        VMFS8 = '"partuuid": "0xfb"'

        expected_failures = [GFS2, GPFS1, GPFS2, GPFS3, GPFS4, VMFS1, VMFS2,
                             VMFS3, VMFS4, VMFS5, VMFS6, VMFS7, VMFS8]
        for failure in expected_failures:
            mock_execute.reset_mock()
            dev_failure = ('{{"blockdevices": [{{{failure}}}]}}'
                           .format(failure=failure))
            mock_execute.return_value = (dev_failure, '')
            self.assertRaises(errors.ProtectedDeviceError,
                              hardware.safety_check_block_device,
                              {}, '/dev/foo')
            self.assertEqual(1, mock_execute.call_count)


@mock.patch.object(utils, 'execute', autospec=True)
class TestCollectSystemLogs(base.IronicAgentTest):

    def setUp(self):
        super().setUp()
        self.hardware = hardware.GenericHardwareManager()

    @mock.patch('pyudev.Context', lambda: mock.sentinel.context)
    @mock.patch('pyudev.Devices.from_device_file', autospec=True)
    def test__collect_udev(self, mock_from_dev, mock_execute):
        mock_execute.return_value = """
            fake0
            fake1
            fake42
        """, ""
        mock_from_dev.side_effect = [
            mock.Mock(properties={'ID_UUID': '0'}),
            RuntimeError('nope'),
            {'ID_UUID': '42'}
        ]

        result = {}
        hardware._collect_udev(result)
        self.assertEqual({'udev/fake0', 'udev/fake42'}, set(result))
        for i in ('0', '42'):
            buf = result[f'udev/fake{i}']
            # Avoiding getvalue on purpose - checking that the IO is not closed
            val = json.loads(buf.read().decode('utf-8'))
            self.assertEqual({'ID_UUID': i}, val)

    @mock.patch.object(hardware, '_collect_udev', autospec=True)
    def test_collect_system_logs(self, mock_udev, mock_execute):
        commands = set()
        expected = {'df', 'dmesg', 'efibootmgr', 'iptables', 'ip', 'lsblk',
                    'lshw', 'cat', 'mount', 'multipath', 'parted', 'ps'}

        def fake_execute(cmd, *args, **kwargs):
            commands.add(cmd)
            return cmd.encode(), ''

        mock_execute.side_effect = fake_execute

        io_dict = {}
        file_list = []
        self.hardware.collect_system_logs(io_dict, file_list)

        self.assertEqual(commands, expected)
        self.assertGreaterEqual(len(io_dict), len(expected))


FakeAddr = namedtuple('FakeAddr', ('family', 'address'))


@mock.patch.object(netutils, 'get_mac_addr', autospec=True)
@mock.patch.object(hardware.GenericHardwareManager, '_get_system_lshw_dict',
                   autospec=True, return_value={'id': 'host'})
@mock.patch.object(hardware, 'get_managers', autospec=True,
                   return_value=[hardware.GenericHardwareManager()])
@mock.patch('psutil.net_if_addrs', autospec=True)
@mock.patch('os.listdir', autospec=True)
@mock.patch('os.path.exists', autospec=True)
@mock.patch('builtins.open', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
@mock.patch.object(netutils, 'interface_has_carrier', autospec=True)
class TestListNetworkInterfaces(base.IronicAgentTest):

    def setUp(self):
        super().setUp()
        self.hardware = hardware.GenericHardwareManager()

    def test_list_network_interfaces(self,
                                     mock_has_carrier,
                                     mocked_execute,
                                     mocked_open,
                                     mocked_exists,
                                     mocked_listdir,
                                     mocked_net_if_addrs,
                                     mockedget_managers,
                                     mocked_lshw,
                                     mocked_get_mac_addr):
        mocked_lshw.return_value = json.loads(hws.LSHW_JSON_OUTPUT_V2[0])
        mocked_listdir.return_value = ['lo', 'eth0', 'foobar']
        mocked_exists.side_effect = [False, False, True, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ],
            'foobar': [
                FakeAddr(socket.AF_INET, '192.168.2.2'),
                FakeAddr(socket.AF_INET6, 'fd00:1000::101')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)
        self.assertEqual(1000, interfaces[0].speed_mbps)

    def test_list_network_interfaces_with_biosdevname(self,
                                                      mock_has_carrier,
                                                      mocked_execute,
                                                      mocked_open,
                                                      mocked_exists,
                                                      mocked_listdir,
                                                      mocked_net_if_addrs,
                                                      mockedget_managers,
                                                      mocked_lshw,
                                                      mocked_get_mac_addr):
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)
        self.assertIsNone(interfaces[0].speed_mbps)

    @mock.patch.object(netutils, 'get_lldp_info', autospec=True)
    def test_list_network_interfaces_with_lldp(self,
                                               mocked_lldp_info,
                                               mock_has_carrier,
                                               mocked_execute,
                                               mocked_open,
                                               mocked_exists,
                                               mocked_listdir,
                                               mocked_net_if_addrs,
                                               mockedget_managers,
                                               mocked_lshw,
                                               mocked_get_mac_addr):
        CONF.set_override('collect_lldp', True)
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_lldp_info.return_value = {'eth0': [
            (0, b''),
            (1, b'\x04\x88Z\x92\xecTY'),
            (2, b'\x05Ethernet1/18'),
            (3, b'\x00x')]
        }
        mock_has_carrier.return_value = True
        mocked_execute.return_value = ('em0\n', '')
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        expected_lldp_info = [
            (0, ''),
            (1, '04885a92ec5459'),
            (2, '0545746865726e6574312f3138'),
            (3, '0078'),
        ]
        self.assertEqual(expected_lldp_info, interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)

    @mock.patch.object(netutils, 'get_lldp_info', autospec=True)
    def test_list_network_interfaces_with_lldp_error(self,
                                                     mocked_lldp_info,
                                                     mock_has_carrier,
                                                     mocked_execute,
                                                     mocked_open,
                                                     mocked_exists,
                                                     mocked_listdir,
                                                     mocked_net_if_addrs,
                                                     mockedget_managers,
                                                     mocked_lshw,
                                                     mocked_get_mac_addr):
        CONF.set_override('collect_lldp', True)
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_lldp_info.side_effect = Exception('Boom!')
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)

    def test_list_network_interfaces_no_carrier(self,
                                                mock_has_carrier,
                                                mocked_execute,
                                                mocked_open,
                                                mocked_exists,
                                                mocked_listdir,
                                                mocked_net_if_addrs,
                                                mockedget_managers,
                                                mocked_lshw,
                                                mocked_get_mac_addr):

        mockedget_managers.return_value = [hardware.GenericHardwareManager()]
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = [OSError('boom')]
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = False
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertFalse(interfaces[0].has_carrier)
        self.assertIsNone(interfaces[0].vendor)
        self.assertEqual('em0', interfaces[0].biosdevname)

    def test_list_network_interfaces_with_vendor_info(self,
                                                      mock_has_carrier,
                                                      mocked_execute,
                                                      mocked_open,
                                                      mocked_exists,
                                                      mocked_listdir,
                                                      mocked_net_if_addrs,
                                                      mockedget_managers,
                                                      mocked_lshw,
                                                      mocked_get_mac_addr):
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        mac = '00:0c:29:8c:11:b1'
        read_mock.side_effect = ['0x15b3\n', '0x1014\n']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual(mac, interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('0x15b3', interfaces[0].vendor)
        self.assertEqual('0x1014', interfaces[0].product)
        self.assertEqual('em0', interfaces[0].biosdevname)

    def test_list_network_interfaces_with_bond(self,
                                               mock_has_carrier,
                                               mocked_execute,
                                               mocked_open,
                                               mocked_exists,
                                               mocked_listdir,
                                               mocked_net_if_addrs,
                                               mockedget_managers,
                                               mocked_lshw,
                                               mocked_get_mac_addr):
        mocked_listdir.return_value = ['lo', 'bond0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'bond0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'bond0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('\n', '')
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('bond0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('', interfaces[0].biosdevname)

    @mock.patch.object(netutils, 'get_interface_driver', autospec=True)
    @mock.patch.object(netutils, 'get_interface_pci_address', autospec=True)
    def test_list_network_interfaces_with_pci_address(self,
                                                      mock_get_pci,
                                                      mock_get_driver,
                                                      mock_has_carrier,
                                                      mocked_execute,
                                                      mocked_open,
                                                      mocked_exists,
                                                      mocked_listdir,
                                                      mocked_net_if_addrs,
                                                      mockedget_managers,
                                                      mocked_lshw,
                                                      mocked_get_mac_addr):
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        mock_get_pci.return_value = '0000:02:00.0'
        mock_get_driver.return_value = 'e1000e'
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertTrue(interfaces[0].has_carrier)
        self.assertEqual('em0', interfaces[0].biosdevname)
        self.assertIsNone(interfaces[0].speed_mbps)
        self.assertEqual('0000:02:00.0', interfaces[0].pci_address)
        self.assertEqual('e1000e', interfaces[0].driver)

    def test_list_network_vlan_interfaces(self,
                                          mock_has_carrier,
                                          mocked_execute,
                                          mocked_open,
                                          mocked_exists,
                                          mocked_listdir,
                                          mocked_net_if_addrs,
                                          mockedget_managers,
                                          mocked_lshw,
                                          mocked_get_mac_addr):
        CONF.set_override('enable_vlan_interfaces', 'eth0.100')
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ],
            'eth0.100': [
                FakeAddr(socket.AF_INET, '192.168.2.2'),
                FakeAddr(socket.AF_INET6, 'fd00::1000::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
            'eth0.100': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(2, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertEqual('eth0.100', interfaces[1].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[1].mac_address)
        self.assertIsNone(interfaces[1].lldp)

    def test_list_network_vlan_interfaces_mac(self,
                                              mock_has_carrier,
                                              mocked_execute,
                                              mocked_open,
                                              mocked_exists,
                                              mocked_listdir,
                                              mocked_net_if_addrs,
                                              mockedget_managers,
                                              mocked_lshw,
                                              mocked_get_mac_addr):
        CONF.set_override('enable_vlan_interfaces', '00:0c:29:8c:11:b1.100')
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ],
            'eth0.100': [
                FakeAddr(socket.AF_INET, '192.168.2.2'),
                FakeAddr(socket.AF_INET6, 'fd00::1000::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
            'eth0.100': '00:0c:29:8c:11:b1',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(2, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        self.assertEqual('192.168.1.2', interfaces[0].ipv4_address)
        self.assertEqual('fd00::101', interfaces[0].ipv6_address)
        self.assertIsNone(interfaces[0].lldp)
        self.assertEqual('eth0.100', interfaces[1].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[1].mac_address)
        self.assertIsNone(interfaces[1].lldp)

    @mock.patch.object(netutils, 'get_lldp_info', autospec=True)
    def test_list_network_vlan_interfaces_using_lldp(self,
                                                     mocked_lldp_info,
                                                     mock_has_carrier,
                                                     mocked_execute,
                                                     mocked_open,
                                                     mocked_exists,
                                                     mocked_listdir,
                                                     mocked_net_if_addrs,
                                                     mockedget_managers,
                                                     mocked_lshw,
                                                     mocked_get_mac_addr):
        CONF.set_override('collect_lldp', True)
        CONF.set_override('enable_vlan_interfaces', 'eth0')
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_execute.return_value = ('em0\n', '')
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ],
            'eth0.100': [
                FakeAddr(socket.AF_INET, '192.168.100.2'),
                FakeAddr(socket.AF_INET6, 'fd00:0100::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:c1')
            ],
            'eth0.101': [
                FakeAddr(socket.AF_INET, '192.168.101.2'),
                FakeAddr(socket.AF_INET6, 'fd00:0101::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:c2')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
            'eth0.100': '00:0c:29:8c:11:c1',
            'eth0.101': '00:0c:29:8c:11:c2',
        }.get(iface)
        mocked_lldp_info.return_value = {'eth0': [
            (0, b''),
            (127, b'\x00\x80\xc2\x03\x00d\x08vlan-100'),
            (127, b'\x00\x80\xc2\x03\x00e\x08vlan-101')]
        }
        mock_has_carrier.return_value = True
        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(3, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('00:0c:29:8c:11:b1', interfaces[0].mac_address)
        expected_lldp_info = [
            (0, ''),
            (127, "0080c203006408766c616e2d313030"),
            (127, "0080c203006508766c616e2d313031")
        ]
        self.assertEqual(expected_lldp_info, interfaces[0].lldp)
        self.assertEqual('eth0.100', interfaces[1].name)
        self.assertEqual('00:0c:29:8c:11:c1', interfaces[1].mac_address)
        self.assertIsNone(interfaces[1].lldp)
        self.assertEqual('eth0.101', interfaces[2].name)
        self.assertEqual('00:0c:29:8c:11:c2', interfaces[2].mac_address)
        self.assertIsNone(interfaces[2].lldp)

    @mock.patch.object(netutils, 'LOG', autospec=True)
    def test_list_network_vlan_invalid_int(self,
                                           mocked_log,
                                           mock_has_carrier,
                                           mocked_execute,
                                           mocked_open,
                                           mocked_exists,
                                           mocked_listdir,
                                           mocked_net_if_addrs,
                                           mockedget_managers,
                                           mocked_lshw,
                                           mocked_get_mac_addr):
        CONF.set_override('collect_lldp', True)
        CONF.set_override('enable_vlan_interfaces', 'enp0s1')
        mocked_listdir.return_value = ['lo', 'eth0']
        mocked_exists.side_effect = [False, False, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ]
        }
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True

        self.hardware.list_network_interfaces()
        mocked_log.warning.assert_called_once_with(
            'Provided interface name %s was not found', 'enp0s1')

    @mock.patch.object(netutils, 'get_lldp_info', autospec=True)
    def test_list_network_vlan_interfaces_using_lldp_all(self,
                                                         mocked_lldp_info,
                                                         mock_has_carrier,
                                                         mocked_execute,
                                                         mocked_open,
                                                         mocked_exists,
                                                         mocked_listdir,
                                                         mocked_net_if_addrs,
                                                         mockedget_managers,
                                                         mocked_lshw,
                                                         mocked_get_mac_addr):
        CONF.set_override('collect_lldp', True)
        CONF.set_override('enable_vlan_interfaces', 'all')
        mocked_listdir.return_value = ['lo', 'eth0', 'eth1']
        mocked_execute.return_value = ('em0\n', '')
        mocked_exists.side_effect = [False, False, True, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ],
            'eth1': [
                FakeAddr(socket.AF_INET, '192.168.2.2'),
                FakeAddr(socket.AF_INET6, 'fd00:1000::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b2')
            ],
            'eth0.100': [
                FakeAddr(socket.AF_INET, '192.168.100.2'),
                FakeAddr(socket.AF_INET6, 'fd00:0100::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:c1')
            ],
            'eth0.101': [
                FakeAddr(socket.AF_INET, '192.168.101.2'),
                FakeAddr(socket.AF_INET6, 'fd00:0101::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:c2')
            ],
            'eth1.102': [
                FakeAddr(socket.AF_INET, '192.168.102.2'),
                FakeAddr(socket.AF_INET6, 'fd00:1102::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:d1')
            ],
            'eth1.103': [
                FakeAddr(socket.AF_INET, '192.168.103.2'),
                FakeAddr(socket.AF_INET6, 'fd00:1103::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:d2')
            ]
        }
        mocked_lldp_info.return_value = {'eth0': [
            (0, b''),
            (127, b'\x00\x80\xc2\x03\x00d\x08vlan-100'),
            (127, b'\x00\x80\xc2\x03\x00e\x08vlan-101')],
            'eth1': [
            (0, b''),
            (127, b'\x00\x80\xc2\x03\x00f\x08vlan-102'),
            (127, b'\x00\x80\xc2\x03\x00g\x08vlan-103')]
        }

        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(6, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual('eth1', interfaces[1].name)
        self.assertEqual('eth0.100', interfaces[2].name)
        self.assertEqual('eth0.101', interfaces[3].name)
        self.assertEqual('eth1.102', interfaces[4].name)
        self.assertEqual('eth1.103', interfaces[5].name)

    @mock.patch.object(hardware.GenericHardwareManager, 'filter_device',
                       autospec=True)
    def test_list_network_interfaces_with_filter_device(
            self, mock_filter_device, mock_has_carrier, mocked_execute,
            mocked_open, mocked_exists, mocked_listdir, mocked_net_if_addrs,
            mockedget_managers, mocked_lshw, mocked_get_mac_addr):
        mocked_lshw.return_value = json.loads(hws.LSHW_JSON_OUTPUT_V2[0])
        mocked_listdir.return_value = ['lo', 'eth0', 'eth1']
        mocked_exists.side_effect = [False, False, True, True]
        mocked_open.return_value.__enter__ = lambda s: s
        mocked_open.return_value.__exit__ = mock.Mock()
        read_mock = mocked_open.return_value.read
        read_mock.side_effect = ['1']
        mocked_net_if_addrs.return_value = {
            'lo': [
                FakeAddr(socket.AF_INET, '127.0.0.1'),
                FakeAddr(socket.AF_INET6, '::1'),
                FakeAddr(socket.AF_PACKET, '00:00:00:00:00:00')
            ],
            'eth0': [
                FakeAddr(socket.AF_INET, '192.168.1.2'),
                FakeAddr(socket.AF_INET6, 'fd00::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b1')
            ],
            'eth1': [
                FakeAddr(socket.AF_INET, '192.168.2.2'),
                FakeAddr(socket.AF_INET6, 'fd00:1000::101'),
                FakeAddr(socket.AF_PACKET, '00:0c:29:8c:11:b2')
            ]
        }
        mocked_get_mac_addr.side_effect = lambda iface: {
            'lo': '00:00:00:00:00:00',
            'eth0': '00:0c:29:8c:11:b1',
            'eth1': '00:0c:29:8c:11:b2',
        }.get(iface)
        mocked_execute.return_value = ('em0\n', '')
        mock_has_carrier.return_value = True

        seen_devices = set()

        def _filter(hwmgr, device):
            self.assertIsInstance(device, hardware.NetworkInterface)
            seen_devices.add(device.name)
            if device.name == 'eth1':
                return None
            return device

        mock_filter_device.side_effect = _filter

        interfaces = self.hardware.list_network_interfaces()
        self.assertEqual(1, len(interfaces))
        self.assertEqual('eth0', interfaces[0].name)
        self.assertEqual({'eth0', 'eth1'}, seen_devices)


@mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
class TestFullSync(base.IronicAgentTest):
    def setUp(self):
        super().setUp()
        self.hardware = hardware.GenericHardwareManager()

    def test_sync_fails(self, mock_execute, mock_dispatch):
        mock_execute.side_effect = processutils.ProcessExecutionError
        self.assertRaises(errors.CommandExecutionError,
                          self.hardware.full_sync)

    def test_full_sync(self, mock_execute, mock_dispatch):
        mock_dispatch.return_value = [
            hardware.BlockDevice('/dev/sda', '', 42, False),
            hardware.BlockDevice('/dev/nvme0n1', '', 42, True),
        ]
        with mock.patch.object(hardware, 'open', mock.mock_open()) as mock_opn:
            self.hardware.full_sync()
            mock_opn.return_value.write.assert_called_once_with(b'3')
        mock_execute.assert_has_calls([
            mock.call('sync'),
            mock.call('blockdev', '--flushbufs', '/dev/sda'),
            mock.call('blockdev', '--flushbufs', '/dev/nvme0n1'),
        ])

    def test_optional_calls_fail(self, mock_execute, mock_dispatch):
        mock_dispatch.return_value = [
            hardware.BlockDevice('/dev/sda', '', 42, False),
            hardware.BlockDevice('/dev/nvme0n1', '', 42, True),
        ]
        mock_execute.side_effect = [
            ('', ''),
            processutils.ProcessExecutionError,
            processutils.ProcessExecutionError,
        ]
        with mock.patch.object(hardware, 'open', mock.mock_open()) as mock_opn:
            mock_opn.return_value.write.side_effect = OSError
            self.hardware.full_sync()
            mock_opn.return_value.write.assert_called_once_with(b'3')
        mock_execute.assert_has_calls([
            mock.call('sync'),
            mock.call('blockdev', '--flushbufs', '/dev/sda'),
            mock.call('blockdev', '--flushbufs', '/dev/nvme0n1'),
        ])


class TestExecuteBootCInstall(base.IronicAgentTest):

    def setUp(self):
        super().setUp()
        self.hardware = hardware.GenericHardwareManager()

    @mock.patch.object(ext_base, 'get_extension', autospec=True)
    def test_execute_bootc_install(self, mock_get_ext):
        ext = mock.Mock()
        node = {'name': 'node-0', 'instance_info': {'foo': 'bar'}}
        mock_get_ext.return_value = ext
        self.hardware.execute_bootc_install(node, [], 'oci://foo',
                                            None, 'secret')
        ext.execute_bootc_install.assert_called_once_with(
            image_source='oci://foo',
            instance_info={'foo': 'bar'},
            pull_secret='secret',
            configdrive=None)
        mock_get_ext.assert_called_once_with('standby')

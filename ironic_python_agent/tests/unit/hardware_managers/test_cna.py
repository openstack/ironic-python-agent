# Copyright (C) 2016 Intel Corporation
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

import os

import mock
from oslo_config import cfg
from oslotest import base as test_base

from ironic_python_agent import hardware
from ironic_python_agent.hardware_managers import cna
from ironic_python_agent import utils

CONF = cfg.CONF


class TestIntelCnaHardwareManager(test_base.BaseTestCase):
    def setUp(self):
        super(TestIntelCnaHardwareManager, self).setUp()
        self.hardware = cna.IntelCnaHardwareManager()
        self.node = {'uuid': 'dda135fb-732d-4742-8e72-df8f3199d244',
                     'driver_internal_info': {}}
        CONF.clear_override('disk_wait_attempts')
        CONF.clear_override('disk_wait_delay')

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_detect_cna_card(self, mock_execute, mock_listdir):
        def mock_return_execute(*args, **kwargs):
            if 'eth0' in args[0][1]:
                return '/foo/bar/fake', ''
            if 'eth1' in args[0][1]:
                return '/foo/bar/i40e', ''

        mock_listdir.return_value = ['eth0', 'eth1']
        mock_execute.side_effect = mock_return_execute
        self.assertEqual(True, cna._detect_cna_card())

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_detect_cna_card_execute_error(self, mock_execute, mock_listdir):
        def mock_return_execute(*args, **kwargs):
            if 'eth0' in args[0][1]:
                return '/foo/bar/fake', ''
            if 'eth1' in args[0][1]:
                return '', 'fake error'
            if 'eth2' in args[0][1]:
                raise OSError('fake')

        mock_listdir.return_value = ['eth0', 'eth1', 'eth2']
        mock_execute.side_effect = mock_return_execute
        self.assertEqual(False, cna._detect_cna_card())

    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test_detect_cna_card_no_i40e_driver(self, mock_execute, mock_listdir):
        def mock_return_execute(*args, **kwargs):
            if 'eth0' in args[0][1]:
                return '/foo/bar/fake1', ''
            if 'eth1' in args[0][1]:
                return '/foo/bar/fake2', ''

        mock_listdir.return_value = ['eth0', 'eth1']
        mock_execute.side_effect = mock_return_execute
        self.assertEqual(False, cna._detect_cna_card())

    @mock.patch.object(cna, 'LOG', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_disable_embedded_lldp_agent_in_cna_card(self, mock_exists,
                                                     mock_listdir, mock_log):
        mock_exists.return_value = True
        mock_listdir.return_value = ['foo', 'bar']
        write_mock = mock.mock_open()
        with mock.patch('six.moves.builtins.open', write_mock, create=True):
            cna._disable_embedded_lldp_agent_in_cna_card()
            write_mock().write.assert_called_with('lldp stop')
            self.assertEqual(False, mock_log.warning.called)

    @mock.patch.object(cna, 'LOG', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_disable_embedded_lldp_agent_wrong_dir_path(self, mock_exists,
                                                        mock_log):
        mock_exists.return_value = False
        cna._disable_embedded_lldp_agent_in_cna_card()
        expected_log_message = 'Driver i40e was not loaded properly'
        mock_log.warning.assert_called_once_with(expected_log_message)

    @mock.patch.object(cna, 'LOG', autospec=True)
    @mock.patch.object(os, 'listdir', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_disable_embedded_lldp_agent_write_error(self, mock_exists,
                                                     mock_listdir, mock_log):
        mock_exists.return_value = True
        listdir_dict = ['foo', 'bar']
        mock_listdir.return_value = listdir_dict
        write_mock = mock.mock_open()
        with mock.patch('six.moves.builtins.open', write_mock, create=True):
            write_mock.side_effect = IOError('fake error')
            cna._disable_embedded_lldp_agent_in_cna_card()
            expected_log_message = ('Failed to disable the embedded LLDP on '
                                    'Intel CNA network card. Addresses of '
                                    'failed pci devices: {}'
                                    .format(str(listdir_dict).strip('[]')))
            mock_log.warning.assert_called_once_with(expected_log_message)

    @mock.patch.object(cna, 'LOG', autospec=True)
    @mock.patch.object(cna, '_detect_cna_card', autospec=True)
    def test_evaluate_hardware_support(self, mock_detect_card, mock_log):
        mock_detect_card.return_value = True
        expected_support = hardware.HardwareSupport.MAINLINE
        actual_support = self.hardware.evaluate_hardware_support()
        self.assertEqual(expected_support, actual_support)
        mock_log.debug.assert_called_once()

    @mock.patch.object(cna, 'LOG', autospec=True)
    @mock.patch.object(cna, '_detect_cna_card', autospec=True)
    def test_evaluate_hardware_support_no_cna_card_detected(self,
                                                            mock_detect_card,
                                                            mock_log):
        mock_detect_card.return_value = False
        expected_support = hardware.HardwareSupport.NONE
        actual_support = self.hardware.evaluate_hardware_support()
        self.assertEqual(expected_support, actual_support)
        mock_log.debug.assert_called_once()

    @mock.patch.object(hardware.GenericHardwareManager, 'collect_lldp_data',
                       autospec=True)
    def test_collect_lldp_data(self, mock_super_collect):
        iface_names = ['eth0', 'eth1']
        returned_lldp_data = [
            (0, 'foo'),
            (1, 'bar'),
        ]
        mock_super_collect.return_value = returned_lldp_data
        with mock.patch.object(cna,
                               '_disable_embedded_lldp_agent_in_cna_card'):
            result = self.hardware.collect_lldp_data(iface_names)
            mock_super_collect.assert_called_once_with(self.hardware,
                                                       iface_names)
            self.assertEqual(returned_lldp_data, result)

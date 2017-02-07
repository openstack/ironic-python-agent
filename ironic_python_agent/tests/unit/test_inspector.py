# Copyright 2015 Red Hat, Inc.
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

import collections
import copy
import os
import time

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslotest import base as test_base
import requests
import stevedore

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import inspector
from ironic_python_agent import utils


CONF = cfg.CONF


class AcceptingFailure(mock.Mock):
    def __call__(self, *args):
        return super(mock.Mock, self).__call__(
            *(copy.deepcopy(x) for x in args))

    def assert_called_with_failure(self, expect_error=False):
        self.assert_called_once_with({}, mock.ANY)
        failure = self.call_args[0][1]
        assert bool(failure) is expect_error, '%s is not %s' % (
            failure, expect_error)


class TestMisc(test_base.BaseTestCase):
    def test_default_collector_loadable(self):
        ext = inspector.extension_manager([inspector.DEFAULT_COLLECTOR])
        self.assertIs(ext[inspector.DEFAULT_COLLECTOR].plugin,
                      inspector.collect_default)

    def test_raise_on_wrong_collector(self):
        self.assertRaisesRegex(errors.InspectionError,
                               'foobar',
                               inspector.extension_manager,
                               ['foobar'])


@mock.patch.object(inspector, 'setup_ipmi_credentials', autospec=True)
@mock.patch.object(inspector, 'call_inspector', new_callable=AcceptingFailure)
@mock.patch.object(stevedore, 'NamedExtensionManager', autospec=True)
class TestInspect(test_base.BaseTestCase):
    def setUp(self):
        super(TestInspect, self).setUp()
        CONF.set_override('inspection_callback_url', 'http://foo/bar',
                          enforce_type=True)
        CONF.set_override('inspection_collectors', '', enforce_type=True)
        self.mock_collect = AcceptingFailure()
        self.mock_ext = mock.Mock(spec=['plugin', 'name'],
                                  plugin=self.mock_collect)

    def test_ok(self, mock_ext_mgr, mock_call, mock_setup_ipmi):
        mock_ext_mgr.return_value = [self.mock_ext]
        mock_call.return_value = {'uuid': 'uuid1'}

        result = inspector.inspect()

        self.mock_collect.assert_called_with_failure()
        mock_call.assert_called_with_failure()
        self.assertEqual('uuid1', result)
        mock_setup_ipmi.assert_called_once_with(mock_call.return_value)

    def test_collectors_option(self, mock_ext_mgr, mock_call, mock_setup_ipmi):
        CONF.set_override('inspection_collectors', 'foo,bar',
                          enforce_type=True)
        mock_ext_mgr.return_value = [
            mock.Mock(spec=['name', 'plugin'], plugin=AcceptingFailure()),
            mock.Mock(spec=['name', 'plugin'], plugin=AcceptingFailure()),
        ]

        inspector.inspect()

        for fake_ext in mock_ext_mgr.return_value:
            fake_ext.plugin.assert_called_with_failure()
        mock_call.assert_called_with_failure()

    def test_collector_failed(self, mock_ext_mgr, mock_call, mock_setup_ipmi):
        mock_ext_mgr.return_value = [self.mock_ext]
        self.mock_collect.side_effect = RuntimeError('boom')

        self.assertRaisesRegex(errors.InspectionError,
                               'boom', inspector.inspect)

        self.mock_collect.assert_called_with_failure()
        mock_call.assert_called_with_failure(expect_error=True)
        self.assertFalse(mock_setup_ipmi.called)

    def test_extensions_failed(self, mock_ext_mgr, mock_call, mock_setup_ipmi):
        CONF.set_override('inspection_collectors', 'foo,bar',
                          enforce_type=True)
        mock_ext_mgr.side_effect = RuntimeError('boom')

        self.assertRaisesRegex(RuntimeError, 'boom', inspector.inspect)

        mock_call.assert_called_with_failure(expect_error=True)
        self.assertFalse(mock_setup_ipmi.called)

    def test_inspector_error(self, mock_ext_mgr, mock_call, mock_setup_ipmi):
        mock_call.return_value = None
        mock_ext_mgr.return_value = [self.mock_ext]

        result = inspector.inspect()

        self.mock_collect.assert_called_with_failure()
        mock_call.assert_called_with_failure()
        self.assertIsNone(result)
        self.assertFalse(mock_setup_ipmi.called)


@mock.patch.object(requests, 'post', autospec=True)
class TestCallInspector(test_base.BaseTestCase):
    def setUp(self):
        super(TestCallInspector, self).setUp()
        CONF.set_override('inspection_callback_url', 'url',
                          enforce_type=True)

    def test_ok(self, mock_post):
        failures = utils.AccumulatedFailures()
        data = collections.OrderedDict(data=42)
        mock_post.return_value.status_code = 200

        res = inspector.call_inspector(data, failures)

        mock_post.assert_called_once_with('url',
                                          cert=None, verify=True,
                                          data='{"data": 42, "error": null}')
        self.assertEqual(mock_post.return_value.json.return_value, res)

    def test_send_failure(self, mock_post):
        failures = mock.Mock(spec=utils.AccumulatedFailures)
        failures.get_error.return_value = "boom"
        data = collections.OrderedDict(data=42)
        mock_post.return_value.status_code = 200

        res = inspector.call_inspector(data, failures)

        mock_post.assert_called_once_with('url',
                                          cert=None, verify=True,
                                          data='{"data": 42, "error": "boom"}')
        self.assertEqual(mock_post.return_value.json.return_value, res)

    def test_inspector_error(self, mock_post):
        failures = utils.AccumulatedFailures()
        data = collections.OrderedDict(data=42)
        mock_post.return_value.status_code = 400

        res = inspector.call_inspector(data, failures)

        mock_post.assert_called_once_with('url',
                                          cert=None, verify=True,
                                          data='{"data": 42, "error": null}')
        self.assertIsNone(res)


@mock.patch.object(utils, 'execute', autospec=True)
class TestSetupIpmiCredentials(test_base.BaseTestCase):
    def setUp(self):
        super(TestSetupIpmiCredentials, self).setUp()
        self.resp = {'ipmi_username': 'user',
                     'ipmi_password': 'pwd',
                     'ipmi_setup_credentials': True}

    def test_disabled(self, mock_call):
        del self.resp['ipmi_setup_credentials']

        inspector.setup_ipmi_credentials(self.resp)

        self.assertFalse(mock_call.called)

    def test_ok(self, mock_call):
        inspector.setup_ipmi_credentials(self.resp)

        expected = [
            mock.call('ipmitool', 'user', 'set', 'name', '2', 'user'),
            mock.call('ipmitool', 'user', 'set', 'password', '2', 'pwd'),
            mock.call('ipmitool', 'user', 'enable', '2'),
            mock.call('ipmitool', 'channel', 'setaccess', '1', '2',
                      'link=on', 'ipmi=on', 'callin=on', 'privilege=4'),
        ]
        self.assertEqual(expected, mock_call.call_args_list)

    def test_user_failed(self, mock_call):
        mock_call.side_effect = processutils.ProcessExecutionError()

        self.assertRaises(errors.InspectionError,
                          inspector.setup_ipmi_credentials,
                          self.resp)

        mock_call.assert_called_once_with('ipmitool', 'user', 'set', 'name',
                                          '2', 'user')

    def test_password_failed(self, mock_call):
        mock_call.side_effect = iter((None,
                                      processutils.ProcessExecutionError))

        self.assertRaises(errors.InspectionError,
                          inspector.setup_ipmi_credentials,
                          self.resp)

        expected = [
            mock.call('ipmitool', 'user', 'set', 'name', '2', 'user'),
            mock.call('ipmitool', 'user', 'set', 'password', '2', 'pwd')
        ]
        self.assertEqual(expected, mock_call.call_args_list)


class BaseDiscoverTest(test_base.BaseTestCase):
    def setUp(self):
        super(BaseDiscoverTest, self).setUp()
        self.inventory = {
            'interfaces': [
                hardware.NetworkInterface(name='em1',
                                          mac_addr='aa:bb:cc:dd:ee:ff',
                                          ipv4_address='1.1.1.1'),
                hardware.NetworkInterface(name='em2',
                                          mac_addr='11:22:33:44:55:66',
                                          ipv4_address=None),
            ],
            'cpu': hardware.CPU(model_name='generic', frequency='3000',
                                count=4, architecture='x86_64'),
            'memory': hardware.Memory(total=11998396 * 1024,
                                      physical_mb=12288),
            'disks': [
                hardware.BlockDevice(name='/dev/sdc',
                                     model='Disk 2',
                                     size=500107862016,
                                     rotational=False),
                hardware.BlockDevice(name='/dev/sda',
                                     model='Too Small Disk',
                                     size=4294967295,
                                     rotational=False),
                hardware.BlockDevice(name='/dev/sdb',
                                     model='Disk 1',
                                     size=500107862016,
                                     rotational=True)
            ],
            'bmc_address': '1.2.3.4',
            'boot': hardware.BootInfo(current_boot_mode='bios',
                                      pxe_interface='boot:if')
        }
        self.failures = utils.AccumulatedFailures()
        self.data = {}


@mock.patch.object(inspector, 'wait_for_dhcp', autospec=True)
@mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
class TestCollectDefault(BaseDiscoverTest):
    def test_ok(self, mock_dispatch, mock_wait_for_dhcp):
        mock_dispatch.return_value = self.inventory

        inspector.collect_default(self.data, self.failures)

        for key in ('memory', 'interfaces', 'cpu', 'disks'):
            self.assertTrue(self.data['inventory'][key])

        self.assertEqual('1.2.3.4', self.data['ipmi_address'])
        self.assertEqual('boot:if', self.data['boot_interface'])
        self.assertEqual(self.inventory['disks'][0].name,
                         self.data['root_disk'].name)

        mock_dispatch.assert_called_once_with('list_hardware_info')
        mock_wait_for_dhcp.assert_called_once_with()

    def test_no_root_disk(self, mock_dispatch, mock_wait_for_dhcp):
        mock_dispatch.return_value = self.inventory
        self.inventory['disks'] = []

        inspector.collect_default(self.data, self.failures)

        for key in ('memory', 'interfaces', 'cpu'):
            self.assertTrue(self.data['inventory'][key])

        self.assertEqual('1.2.3.4', self.data['ipmi_address'])
        self.assertEqual('boot:if', self.data['boot_interface'])
        self.assertNotIn('root_disk', self.data)

        mock_dispatch.assert_called_once_with('list_hardware_info')
        mock_wait_for_dhcp.assert_called_once_with()


@mock.patch.object(utils, 'collect_system_logs', autospec=True)
class TestCollectLogs(test_base.BaseTestCase):

    def test(self, mock_collect):
        data = {}
        ret = 'SpongeBob SquarePants'
        mock_collect.return_value = ret

        inspector.collect_logs(data, None)
        self.assertEqual({'logs': ret}, data)

    def test_fail(self, mock_collect):
        data = {}
        mock_collect.side_effect = errors.CommandExecutionError('boom')
        self.assertIsNone(inspector.collect_logs(data, None))
        self.assertNotIn('logs', data)


@mock.patch.object(utils, 'execute', autospec=True)
class TestCollectExtraHardware(test_base.BaseTestCase):
    def setUp(self):
        super(TestCollectExtraHardware, self).setUp()
        self.data = {}
        self.failures = utils.AccumulatedFailures()

    def test_no_benchmarks(self, mock_execute):
        mock_execute.return_value = ("[1, 2, 3]", "")

        inspector.collect_extra_hardware(self.data, None)

        self.assertEqual({'data': [1, 2, 3]}, self.data)
        mock_execute.assert_called_once_with('hardware-detect')

    @mock.patch.object(utils, 'get_agent_params', autospec=True)
    def test_benchmarks(self, mock_params, mock_execute):
        mock_params.return_value = {'ipa-inspection-benchmarks': 'cpu,mem'}
        mock_execute.return_value = ("[1, 2, 3]", "")

        inspector.collect_extra_hardware(self.data, None)

        self.assertEqual({'data': [1, 2, 3]}, self.data)
        mock_execute.assert_called_once_with('hardware-detect',
                                             '--benchmark',
                                             'cpu', 'mem')

    def test_execute_failed(self, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError()

        inspector.collect_extra_hardware(self.data, self.failures)

        self.assertNotIn('data', self.data)
        self.assertTrue(self.failures)
        mock_execute.assert_called_once_with('hardware-detect')

    def test_parsing_failed(self, mock_execute):
        mock_execute.return_value = ("foobar", "")

        inspector.collect_extra_hardware(self.data, self.failures)

        self.assertNotIn('data', self.data)
        self.assertTrue(self.failures)
        mock_execute.assert_called_once_with('hardware-detect')


@mock.patch.object(os, 'listdir', autospec=True)
class TestCollectPciDevicesInfo(test_base.BaseTestCase):
    def setUp(self):
        super(TestCollectPciDevicesInfo, self).setUp()
        self.data = {}
        self.failures = utils.AccumulatedFailures()

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_success(self, mock_isdir, mock_listdir):
        subdirs = ['foo', 'bar']
        mock_listdir.return_value = subdirs
        mock_isdir.return_value = True
        reads = ['0x1234', '0x5678', '0x9876', '0x5432']
        expected_pci_devices = [{'vendor_id': '1234', 'product_id': '5678'},
                                {'vendor_id': '9876', 'product_id': '5432'}]

        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_read = mock_open.return_value.read
            mock_read.side_effect = reads
            inspector.collect_pci_devices_info(self.data, self.failures)

        self.assertEqual(2 * len(subdirs), mock_open.call_count)
        self.assertListEqual(expected_pci_devices, self.data['pci_devices'])

    def test_wrong_path(self, mock_listdir):
        mock_listdir.side_effect = OSError()

        inspector.collect_pci_devices_info(self.data, self.failures)

        self.assertNotIn('pci_devices', self.data)
        self.assertEqual(1, len(self.failures._failures))

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_bad_pci_device_info(self, mock_isdir, mock_listdir):
        subdirs = ['foo', 'bar', 'baz']
        mock_listdir.return_value = subdirs
        mock_isdir.return_value = True
        reads = ['0x1234', '0x5678', '0x9876', IOError, IndexError,
                 '0x5432']
        expected_pci_devices = [{'vendor_id': '1234', 'product_id': '5678'}]

        mock_open = mock.mock_open()
        with mock.patch('six.moves.builtins.open', mock_open):
            mock_read = mock_open.return_value.read
            mock_read.side_effect = reads
            inspector.collect_pci_devices_info(self.data, self.failures)

        # note(sborkows): due to throwing IOError, the corresponding mock_open
        # will not be called, so there are 5 mock_open calls in total
        self.assertEqual(5, mock_open.call_count)
        self.assertListEqual(expected_pci_devices, self.data['pci_devices'])


@mock.patch.object(utils, 'get_agent_params', lambda: {'BOOTIF': '01-cdef'})
@mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
class TestWaitForDhcp(test_base.BaseTestCase):
    def setUp(self):
        super(TestWaitForDhcp, self).setUp()
        CONF.set_override('inspection_dhcp_wait_timeout',
                          inspector.DEFAULT_DHCP_WAIT_TIMEOUT)

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_all(self, mocked_sleep, mocked_dispatch):
        CONF.set_override('inspection_dhcp_all_interfaces', True)
        # We used to rely on has_carrier check, but we've found it unreliable
        # in the DIB image, so we ignore its value.
        mocked_dispatch.side_effect = [
            [hardware.NetworkInterface(name='em0', mac_addr='abcd',
                                       ipv4_address=None,
                                       has_carrier=False),
             hardware.NetworkInterface(name='em1', mac_addr='cdef',
                                       ipv4_address='1.2.3.4',
                                       has_carrier=False)],
            [hardware.NetworkInterface(name='em0', mac_addr='abcd',
                                       ipv4_address=None,
                                       has_carrier=True),
             hardware.NetworkInterface(name='em1', mac_addr='cdef',
                                       ipv4_address='1.2.3.4',
                                       has_carrier=True)],
            [hardware.NetworkInterface(name='em0', mac_addr='abcd',
                                       ipv4_address='1.1.1.1',
                                       has_carrier=True),
             hardware.NetworkInterface(name='em1', mac_addr='cdef',
                                       ipv4_address='1.2.3.4',
                                       has_carrier=True)],
        ]

        self.assertTrue(inspector.wait_for_dhcp())

        mocked_dispatch.assert_called_with('list_network_interfaces')
        self.assertEqual(2, mocked_sleep.call_count)
        self.assertEqual(3, mocked_dispatch.call_count)

    @mock.patch.object(time, 'sleep', autospec=True)
    def test_boot_only(self, mocked_sleep, mocked_dispatch):
        CONF.set_override('inspection_dhcp_all_interfaces', False)
        mocked_dispatch.side_effect = [
            [hardware.NetworkInterface(name='em0', mac_addr='abcd',
                                       ipv4_address=None,
                                       has_carrier=False),
             hardware.NetworkInterface(name='em1', mac_addr='cdef',
                                       ipv4_address=None,
                                       has_carrier=False)],
            [hardware.NetworkInterface(name='em0', mac_addr='abcd',
                                       ipv4_address=None,
                                       has_carrier=True),
             hardware.NetworkInterface(name='em1', mac_addr='cdef',
                                       ipv4_address='1.2.3.4',
                                       has_carrier=True)],
        ]

        self.assertTrue(inspector.wait_for_dhcp())

        mocked_dispatch.assert_called_with('list_network_interfaces')
        self.assertEqual(1, mocked_sleep.call_count)
        self.assertEqual(2, mocked_dispatch.call_count)

    @mock.patch.object(inspector, '_DHCP_RETRY_INTERVAL', 0.01)
    def test_timeout(self, mocked_dispatch):
        CONF.set_override('inspection_dhcp_all_interfaces', True)
        CONF.set_override('inspection_dhcp_wait_timeout', 0.02)

        mocked_dispatch.return_value = [
            hardware.NetworkInterface(name='em0', mac_addr='abcd',
                                      ipv4_address=None),
            hardware.NetworkInterface(name='em1', mac_addr='abcd',
                                      ipv4_address='1.2.3.4'),
        ]

        self.assertFalse(inspector.wait_for_dhcp())

        mocked_dispatch.assert_called_with('list_network_interfaces')

    def test_disabled(self, mocked_dispatch):
        CONF.set_override('inspection_dhcp_wait_timeout', 0)

        self.assertTrue(inspector.wait_for_dhcp())

        self.assertFalse(mocked_dispatch.called)


class TestNormalizeMac(test_base.BaseTestCase):
    def test_correct_mac(self):
        self.assertEqual('11:22:33:aa:bb:cc',
                         inspector._normalize_mac('11:22:33:aa:BB:cc'))

    def test_pxelinux_mac(self):
        self.assertEqual('11:22:33:aa:bb:cc',
                         inspector._normalize_mac('01-11-22-33-aa-BB-cc'))

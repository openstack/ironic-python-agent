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

import base64
import collections
import copy
import io
import tarfile
import time
import unittest

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
import requests
import six
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


class TestMisc(unittest.TestCase):
    def test_default_collector_loadable(self):
        ext = inspector.extension_manager([inspector.DEFAULT_COLLECTOR])
        self.assertIs(ext[inspector.DEFAULT_COLLECTOR].plugin,
                      inspector.collect_default)

    def test_raise_on_wrong_collector(self):
        self.assertRaisesRegexp(errors.InspectionError,
                                'foobar',
                                inspector.extension_manager,
                                ['foobar'])


@mock.patch.object(inspector, 'setup_ipmi_credentials', autospec=True)
@mock.patch.object(inspector, 'call_inspector', new_callable=AcceptingFailure)
@mock.patch.object(stevedore, 'NamedExtensionManager', autospec=True)
class TestInspect(unittest.TestCase):
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

        self.assertRaisesRegexp(errors.InspectionError,
                                'boom', inspector.inspect)

        self.mock_collect.assert_called_with_failure()
        mock_call.assert_called_with_failure(expect_error=True)
        self.assertFalse(mock_setup_ipmi.called)

    def test_extensions_failed(self, mock_ext_mgr, mock_call, mock_setup_ipmi):
        CONF.set_override('inspection_collectors', 'foo,bar',
                          enforce_type=True)
        mock_ext_mgr.side_effect = RuntimeError('boom')

        self.assertRaisesRegexp(RuntimeError, 'boom', inspector.inspect)

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
class TestCallInspector(unittest.TestCase):
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
                                          data='{"data": 42, "error": null}')
        self.assertEqual(mock_post.return_value.json.return_value, res)

    def test_send_failure(self, mock_post):
        failures = mock.Mock(spec=utils.AccumulatedFailures)
        failures.get_error.return_value = "boom"
        data = collections.OrderedDict(data=42)
        mock_post.return_value.status_code = 200

        res = inspector.call_inspector(data, failures)

        mock_post.assert_called_once_with('url',
                                          data='{"data": 42, "error": "boom"}')
        self.assertEqual(mock_post.return_value.json.return_value, res)

    def test_inspector_error(self, mock_post):
        failures = utils.AccumulatedFailures()
        data = collections.OrderedDict(data=42)
        mock_post.return_value.status_code = 400

        res = inspector.call_inspector(data, failures)

        mock_post.assert_called_once_with('url',
                                          data='{"data": 42, "error": null}')
        self.assertIsNone(res)


@mock.patch.object(utils, 'execute', autospec=True)
class TestSetupIpmiCredentials(unittest.TestCase):
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


class BaseDiscoverTest(unittest.TestCase):
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
        }
        self.failures = utils.AccumulatedFailures()
        self.data = {}


class TestDiscoverNetworkProperties(BaseDiscoverTest):
    def test_no_network_interfaces(self):
        self.inventory['interfaces'] = [
            hardware.NetworkInterface(name='lo',
                                      mac_addr='aa:bb:cc:dd:ee:ff',
                                      ipv4_address='127.0.0.1'),
            hardware.NetworkInterface(name='local-2',
                                      mac_addr='aa:bb:cc:dd:ee:ff',
                                      ipv4_address='127.0.1.42'),
        ]

        inspector.discover_network_properties(self.inventory, self.data,
                                              self.failures)

        self.assertIn('no network interfaces found', self.failures.get_error())
        self.assertFalse(self.data['interfaces'])

    def test_ok(self):
        inspector.discover_network_properties(self.inventory, self.data,
                                              self.failures)

        self.assertEqual({'em1': {'mac': 'aa:bb:cc:dd:ee:ff',
                                  'ip': '1.1.1.1'},
                          'em2': {'mac': '11:22:33:44:55:66',
                                  'ip': None}},
                         self.data['interfaces'])
        self.assertFalse(self.failures)

    def test_missing(self):
        self.inventory['interfaces'] = [
            hardware.NetworkInterface(name='em1',
                                      mac_addr='aa:bb:cc:dd:ee:ff'),
            hardware.NetworkInterface(name='em2',
                                      mac_addr=None,
                                      ipv4_address='1.2.1.2'),
        ]

        inspector.discover_network_properties(self.inventory, self.data,
                                              self.failures)

        self.assertEqual({'em1': {'mac': 'aa:bb:cc:dd:ee:ff', 'ip': None}},
                         self.data['interfaces'])
        self.assertFalse(self.failures)


class TestDiscoverSchedulingProperties(BaseDiscoverTest):
    def test_ok(self):
        inspector.discover_scheduling_properties(
            self.inventory, self.data,
            root_disk=self.inventory['disks'][2])

        self.assertEqual({'cpus': 4, 'cpu_arch': 'x86_64', 'local_gb': 464,
                          'memory_mb': 12288}, self.data)

    def test_no_local_gb(self):
        # Some DRAC servers do not have any visible hard drive until RAID is
        # built

        inspector.discover_scheduling_properties(self.inventory, self.data)

        self.assertEqual({'cpus': 4, 'cpu_arch': 'x86_64', 'memory_mb': 12288},
                         self.data)


@mock.patch.object(utils, 'get_agent_params',
                   lambda: {'BOOTIF': 'boot:if'})
@mock.patch.object(inspector, 'wait_for_dhcp', autospec=True)
@mock.patch.object(inspector, 'discover_scheduling_properties', autospec=True)
@mock.patch.object(inspector, 'discover_network_properties', autospec=True)
@mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
class TestCollectDefault(BaseDiscoverTest):
    def test_ok(self, mock_dispatch, mock_discover_net, mock_discover_sched,
                mock_wait_for_dhcp):
        mock_dispatch.return_value = self.inventory

        inspector.collect_default(self.data, self.failures)

        for key in ('memory', 'interfaces', 'cpu', 'disks'):
            self.assertTrue(self.data['inventory'][key])

        self.assertEqual('1.2.3.4', self.data['ipmi_address'])
        self.assertEqual('boot:if', self.data['boot_interface'])
        self.assertEqual(self.inventory['disks'][0].name,
                         self.data['root_disk'].name)

        mock_dispatch.assert_called_once_with('list_hardware_info')
        mock_discover_net.assert_called_once_with(self.inventory, self.data,
                                                  self.failures)
        mock_discover_sched.assert_called_once_with(
            self.inventory, self.data,
            root_disk=self.inventory['disks'][0])
        mock_wait_for_dhcp.assert_called_once_with()

    def test_no_root_disk(self, mock_dispatch, mock_discover_net,
                          mock_discover_sched, mock_wait_for_dhcp):
        mock_dispatch.return_value = self.inventory
        self.inventory['disks'] = []

        inspector.collect_default(self.data, self.failures)

        for key in ('memory', 'interfaces', 'cpu'):
            self.assertTrue(self.data['inventory'][key])

        self.assertEqual('1.2.3.4', self.data['ipmi_address'])
        self.assertEqual('boot:if', self.data['boot_interface'])
        self.assertNotIn('root_disk', self.data)

        mock_dispatch.assert_called_once_with('list_hardware_info')
        mock_discover_net.assert_called_once_with(self.inventory, self.data,
                                                  self.failures)
        mock_discover_sched.assert_called_once_with(
            self.inventory, self.data, root_disk=None)
        mock_wait_for_dhcp.assert_called_once_with()


@mock.patch.object(utils, 'execute', autospec=True)
class TestCollectLogs(unittest.TestCase):
    def test(self, mock_execute):
        contents = 'journal contents \xd0\xbc\xd1\x8f\xd1\x83'
        # That's how execute() works with binary=True
        if six.PY3:
            contents = b'journal contents \xd0\xbc\xd1\x8f\xd1\x83'
        else:
            contents = 'journal contents \xd0\xbc\xd1\x8f\xd1\x83'
        expected_contents = u'journal contents \u043c\u044f\u0443'
        mock_execute.return_value = (contents, '')

        data = {}
        inspector.collect_logs(data, None)
        res = io.BytesIO(base64.b64decode(data['logs']))

        with tarfile.open(fileobj=res) as tar:
            members = [(m.name, m.size) for m in tar]
            self.assertEqual([('journal', len(contents))], members)

            member = tar.extractfile('journal')
            self.assertEqual(expected_contents, member.read().decode('utf-8'))

        mock_execute.assert_called_once_with('journalctl', '--full',
                                             '--no-pager', '-b',
                                             '-n', '10000', binary=True,
                                             log_stdout=False)

    def test_no_journal(self, mock_execute):
        mock_execute.side_effect = OSError()

        data = {}
        inspector.collect_logs(data, None)
        self.assertFalse(data)


@mock.patch.object(utils, 'execute', autospec=True)
class TestCollectExtraHardware(unittest.TestCase):
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


@mock.patch.object(utils, 'get_agent_params', lambda: {'BOOTIF': '01-cdef'})
@mock.patch.object(hardware, 'dispatch_to_managers', autospec=True)
class TestWaitForDhcp(unittest.TestCase):
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


class TestNormalizeMac(unittest.TestCase):
    def test_correct_mac(self):
        self.assertEqual('11:22:33:aa:bb:cc',
                         inspector._normalize_mac('11:22:33:aa:BB:cc'))

    def test_pxelinux_mac(self):
        self.assertEqual('11:22:33:aa:bb:cc',
                         inspector._normalize_mac('01-11-22-33-aa-BB-cc'))

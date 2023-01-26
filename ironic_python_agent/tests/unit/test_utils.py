# Copyright 2011 Justin Santa Barbara
# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import base64
import errno
import glob
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from unittest import mock

from ironic_lib import utils as ironic_utils
from oslo_concurrency import processutils
import requests
import testtools

from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent.tests.unit import base as ironic_agent_base
from ironic_python_agent import utils


class ExecuteTestCase(ironic_agent_base.IronicAgentTest):
    # This test case does call utils.execute(), so don't block access to the
    # execute calls.
    block_execute = False

    # We do mock out the call to ironic_utils.execute() so we don't actually
    # 'execute' anything, as utils.execute() calls ironic_utils.execute()
    @mock.patch.object(ironic_utils, 'execute', autospec=True)
    def test_execute(self, mock_execute):
        utils.execute('/usr/bin/env', 'false', check_exit_code=False)
        mock_execute.assert_called_once_with('/usr/bin/env', 'false',
                                             check_exit_code=False)


class GetAgentParamsTestCase(ironic_agent_base.IronicAgentTest):

    @mock.patch('oslo_log.log.getLogger', autospec=True)
    @mock.patch('builtins.open', autospec=True)
    def test__read_params_from_file_fail(self, logger_mock, open_mock):
        open_mock.side_effect = Exception
        params = utils._read_params_from_file('file-path')
        self.assertEqual({}, params)

    @mock.patch('builtins.open', autospec=True)
    def test__read_params_from_file(self, open_mock):
        kernel_line = 'api-url=http://localhost:9999 baz foo=bar\n'
        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        read_mock = open_mock.return_value.read
        read_mock.return_value = kernel_line
        params = utils._read_params_from_file('file-path')
        open_mock.assert_called_once_with('file-path')
        read_mock.assert_called_once_with()
        self.assertEqual('http://localhost:9999', params['api-url'])
        self.assertEqual('bar', params['foo'])
        self.assertNotIn('baz', params)

    @mock.patch.object(utils, '_set_cached_params', autospec=True)
    @mock.patch.object(utils, '_read_params_from_file', autospec=True)
    @mock.patch.object(utils, '_get_cached_params', autospec=True)
    def test_get_agent_params_kernel_cmdline(self, get_cache_mock,
                                             read_params_mock,
                                             set_cache_mock):
        get_cache_mock.return_value = {}
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        returned_params = utils.get_agent_params()
        read_params_mock.assert_called_once_with('/proc/cmdline')
        self.assertEqual(expected_params, returned_params)
        set_cache_mock.assert_called_once_with(expected_params)

    @mock.patch.object(utils, '_set_cached_params', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_params', autospec=True)
    @mock.patch.object(utils, '_read_params_from_file', autospec=True)
    @mock.patch.object(utils, '_get_cached_params', autospec=True)
    def test_get_agent_params_vmedia(self, get_cache_mock,
                                     read_params_mock,
                                     get_vmedia_params_mock,
                                     set_cache_mock):
        get_cache_mock.return_value = {}
        kernel_params = {'boot_method': 'vmedia'}
        vmedia_params = {'a': 'b'}
        expected_params = dict(
            list(kernel_params.items()) + list(vmedia_params.items()))
        read_params_mock.return_value = kernel_params
        get_vmedia_params_mock.return_value = vmedia_params

        returned_params = utils.get_agent_params()
        read_params_mock.assert_called_once_with('/proc/cmdline')
        self.assertEqual(expected_params, returned_params)
        # Make sure information is cached
        set_cache_mock.assert_called_once_with(expected_params)

    @mock.patch.object(utils, '_set_cached_params', autospec=True)
    @mock.patch.object(utils, '_get_cached_params', autospec=True)
    def test_get_agent_params_from_cache(self, get_cache_mock,
                                         set_cache_mock):
        get_cache_mock.return_value = {'a': 'b'}
        returned_params = utils.get_agent_params()
        expected_params = {'a': 'b'}
        self.assertEqual(expected_params, returned_params)
        self.assertEqual(0, set_cache_mock.call_count)

    @mock.patch('builtins.open', autospec=True)
    @mock.patch.object(glob, 'glob', autospec=True)
    def test__get_vmedia_device(self, glob_mock, open_mock):

        glob_mock.return_value = ['/sys/class/block/sda/device/model',
                                  '/sys/class/block/sdb/device/model',
                                  '/sys/class/block/sdc/device/model']
        fobj_mock = mock.MagicMock()
        mock_file_handle = mock.MagicMock()
        mock_file_handle.__enter__.return_value = fobj_mock
        open_mock.return_value = mock_file_handle

        fobj_mock.read.side_effect = ['scsi disk', Exception, 'Virtual Media']
        vmedia_device_returned = utils._get_vmedia_device()
        self.assertEqual('sdc', vmedia_device_returned)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__find_vmedia_device_by_labels_handles_exec_error(self,
                                                              execute_mock):
        execute_mock.side_effect = processutils.ProcessExecutionError
        self.assertIsNone(utils._find_vmedia_device_by_labels(['l1', 'l2']))
        execute_mock.assert_called_once_with('lsblk', '-p', '-P',
                                             '-oKNAME,LABEL')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__find_vmedia_device_by_labels(self, execute_mock):
        # NOTE(TheJulia): Case is intentionally mixed here to ensure
        # proper matching occurs
        disk_list = ('KNAME="/dev/sda" LABEL=""\n'
                     'KNAME="/dev/sda2" LABEL="Meow"\n'
                     'KNAME="/dev/sda3" LABEL="Recovery HD"\n'
                     'KNAME="/dev/sda1" LABEL="EFI"\n'
                     'KNAME="/dev/sdb" LABEL=""\n'
                     'KNAME="/dev/sdb1" LABEL=""\n'
                     'KNAME="/dev/sdb2" LABEL=""\n'
                     'KNAME="/dev/sdc" LABEL="meow"\n')
        invalid_disk = ('KNAME="sda1" SIZE="1610612736" TYPE="part" TRAN=""\n'
                        'KNAME="sda" SIZE="1610612736" TYPE="disk" '
                        'TRAN="sata"\n')
        valid_disk = ('KNAME="sdc" SIZE="1610612736" TYPE="disk" TRAN="usb"\n')
        execute_mock.side_effect = [
            (disk_list, ''),
            (invalid_disk, ''),
            (valid_disk, ''),
        ]
        self.assertEqual('/dev/sdc',
                         utils._find_vmedia_device_by_labels(['cat', 'meOw']))
        execute_mock.assert_has_calls([
            mock.call('lsblk', '-p', '-P', '-oKNAME,LABEL'),
            mock.call('lsblk', '-n', '-s', '-P', '-b',
                      '-oKNAME,TRAN,TYPE,SIZE', '/dev/sda2'),
            mock.call('lsblk', '-n', '-s', '-P', '-b',
                      '-oKNAME,TRAN,TYPE,SIZE', '/dev/sdc'),
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test__find_vmedia_device_by_labels_not_found(self, execute_mock):
        disk_list = ('KNAME="/dev/sdb" LABEL="evil"\n'
                     'KNAME="/dev/sdb1" LABEL="banana"\n'
                     'KNAME="/dev/sdb2" LABEL=""\n')
        execute_mock.return_value = (disk_list, '')
        self.assertIsNone(utils._find_vmedia_device_by_labels(['l1', 'l2']))
        execute_mock.assert_called_once_with('lsblk', '-p', '-P',
                                             '-oKNAME,LABEL')

    @mock.patch.object(utils, '_check_vmedia_device', autospec=True)
    @mock.patch.object(utils, '_find_vmedia_device_by_labels', autospec=True)
    @mock.patch.object(utils, '_read_params_from_file', autospec=True)
    @mock.patch.object(ironic_utils, 'mounted', autospec=True)
    def test__get_vmedia_params(self, mount_mock, read_params_mock, find_mock,
                                check_vmedia_mock):
        check_vmedia_mock.return_value = True
        find_mock.return_value = '/dev/fake'
        mount_mock.return_value.__enter__.return_value = '/tempdir'
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params

        returned_params = utils._get_vmedia_params()

        mount_mock.assert_called_once_with('/dev/fake')
        read_params_mock.assert_called_once_with("/tempdir/parameters.txt")
        self.assertEqual(expected_params, returned_params)

    @mock.patch.object(utils, '_check_vmedia_device', autospec=True)
    @mock.patch.object(utils, '_find_vmedia_device_by_labels', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_device', autospec=True)
    @mock.patch.object(utils, '_read_params_from_file', autospec=True)
    @mock.patch.object(ironic_utils, 'mounted', autospec=True)
    def test__get_vmedia_params_by_device(self, mount_mock, read_params_mock,
                                          get_device_mock, find_mock,
                                          check_vmedia_mock):
        check_vmedia_mock.return_value = True
        find_mock.return_value = None
        mount_mock.return_value.__enter__.return_value = '/tempdir'
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        get_device_mock.return_value = "sda"

        returned_params = utils._get_vmedia_params()

        mount_mock.assert_called_once_with('/dev/sda')
        read_params_mock.assert_called_once_with("/tempdir/parameters.txt")
        self.assertEqual(expected_params, returned_params)
        check_vmedia_mock.assert_called_with('/dev/sda')

    @mock.patch.object(utils, '_check_vmedia_device', autospec=True)
    @mock.patch.object(utils, '_find_vmedia_device_by_labels', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_device', autospec=True)
    @mock.patch.object(utils, '_read_params_from_file', autospec=True)
    @mock.patch.object(ironic_utils, 'mounted', autospec=True)
    def test__get_vmedia_params_by_device_device_invalid(
            self, mount_mock, read_params_mock,
            get_device_mock, find_mock,
            check_vmedia_mock):
        check_vmedia_mock.return_value = False
        find_mock.return_value = None
        expected_params = {}
        read_params_mock.return_value = expected_params
        get_device_mock.return_value = "sda"

        returned_params = utils._get_vmedia_params()

        mount_mock.assert_not_called()
        read_params_mock.assert_not_called
        self.assertEqual(expected_params, returned_params)
        check_vmedia_mock.assert_called_with('/dev/sda')

    @mock.patch.object(utils, '_find_vmedia_device_by_labels', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_device', autospec=True)
    def test__get_vmedia_params_cannot_find_dev(self, get_device_mock,
                                                find_mock):
        find_mock.return_value = None
        get_device_mock.return_value = None
        self.assertEqual({}, utils._get_vmedia_params())


class TestFailures(testtools.TestCase):
    def test_get_error(self):
        f = utils.AccumulatedFailures()
        self.assertFalse(f)
        self.assertIsNone(f.get_error())

        f.add('foo')
        f.add('%s', 'bar')
        f.add(RuntimeError('baz'))
        self.assertTrue(f)

        exp = ('The following errors were encountered:\n* foo\n* bar\n* baz')
        self.assertEqual(exp, f.get_error())

    def test_raise(self):
        class FakeException(Exception):
            pass

        f = utils.AccumulatedFailures(exc_class=FakeException)
        self.assertIsNone(f.raise_if_needed())
        f.add('foo')
        self.assertRaisesRegex(FakeException, 'foo', f.raise_if_needed)


class TestUtils(ironic_agent_base.IronicAgentTest):

    def _get_journalctl_output(self, mock_execute, lines=None, units=None):
        contents = b'Krusty Krab'
        mock_execute.return_value = (contents, '')
        data = utils.get_journalctl_output(lines=lines, units=units)

        cmd = ['journalctl', '--full', '--no-pager', '-b']
        if lines is not None:
            cmd.extend(['-n', str(lines)])
        if units is not None:
            [cmd.extend(['-u', u]) for u in units]

        mock_execute.assert_called_once_with(*cmd, binary=True,
                                             log_stdout=False)
        self.assertEqual(contents, data.read())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_journalctl_output(self, mock_execute):
        self._get_journalctl_output(mock_execute)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_journalctl_output_with_lines(self, mock_execute):
        self._get_journalctl_output(mock_execute, lines=123)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_journalctl_output_with_units(self, mock_execute):
        self._get_journalctl_output(mock_execute, units=['fake-unit1',
                                                         'fake-unit2'])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_journalctl_output_fail(self, mock_execute):
        mock_execute.side_effect = processutils.ProcessExecutionError()
        self.assertRaises(errors.CommandExecutionError,
                          self._get_journalctl_output, mock_execute)

    def test_gzip_and_b64encode(self):
        contents = b'Squidward Tentacles'
        io_dict = {'fake-name': io.BytesIO(bytes(contents))}
        data = utils.gzip_and_b64encode(io_dict=io_dict)
        self.assertIsInstance(data, str)

        res = io.BytesIO(base64.b64decode(data))
        with tarfile.open(fileobj=res) as tar:
            members = [(m.name, m.size) for m in tar]
            self.assertEqual([('fake-name', len(contents))], members)

            member = tar.extractfile('fake-name')
            self.assertEqual(contents, member.read())

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_get_command_output(self, mock_execute):
        contents = b'Sandra Sandy Cheeks'
        mock_execute.return_value = (contents, '')
        data = utils.get_command_output(['foo'])

        mock_execute.assert_called_once_with(
            'foo', binary=True, log_stdout=False)
        self.assertEqual(contents, data.read())

    @mock.patch.object(subprocess, 'check_call', autospec=True)
    def test_guess_root_disk_primary_sort(self, mock_call):
        block_devices = [
            hardware.BlockDevice(name='/dev/sdc',
                                 model='too small',
                                 size=4294967295,
                                 rotational=True),
            hardware.BlockDevice(name='/dev/sda',
                                 model='bigger than sdb',
                                 size=21474836480,
                                 rotational=True),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='',
                                 size=10737418240,
                                 rotational=True),
            hardware.BlockDevice(name='/dev/sdd',
                                 model='bigger than sdb',
                                 size=21474836480,
                                 rotational=True),
        ]
        device = utils.guess_root_disk(block_devices)
        self.assertEqual(device.name, '/dev/sdb')

    @mock.patch.object(subprocess, 'check_call', autospec=True)
    def test_guess_root_disk_secondary_sort(self, mock_call):
        block_devices = [
            hardware.BlockDevice(name='/dev/sdc',
                                 model='_',
                                 size=10737418240,
                                 rotational=True),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='_',
                                 size=10737418240,
                                 rotational=True),
            hardware.BlockDevice(name='/dev/sda',
                                 model='_',
                                 size=10737418240,
                                 rotational=True),
            hardware.BlockDevice(name='/dev/sdd',
                                 model='_',
                                 size=10737418240,
                                 rotational=True),
        ]
        device = utils.guess_root_disk(block_devices)
        self.assertEqual(device.name, '/dev/sda')

    @mock.patch.object(subprocess, 'check_call', autospec=True)
    def test_guess_root_disk_disks_too_small(self, mock_call):
        block_devices = [
            hardware.BlockDevice(name='/dev/sda',
                                 model='too small',
                                 size=4294967295,
                                 rotational=True),
            hardware.BlockDevice(name='/dev/sdb',
                                 model='way too small',
                                 size=1,
                                 rotational=True),
        ]
        self.assertRaises(errors.DeviceNotFound,
                          utils.guess_root_disk, block_devices)

    @mock.patch.object(subprocess, 'check_call', autospec=True)
    def test_is_journalctl_present(self, mock_call):
        self.assertTrue(utils.is_journalctl_present())

    @mock.patch.object(subprocess, 'check_call', autospec=True)
    def test_is_journalctl_present_false(self, mock_call):
        os_error = OSError()
        os_error.errno = errno.ENOENT
        mock_call.side_effect = os_error
        self.assertFalse(utils.is_journalctl_present())

    @mock.patch.object(utils, 'gzip_and_b64encode', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_all_managers', autospec=True)
    @mock.patch.object(utils, 'is_journalctl_present', autospec=True)
    @mock.patch.object(utils, 'get_journalctl_output', autospec=True)
    def test_collect_system_logs_journald(
            self, mock_logs, mock_journalctl, mock_dispatch, mock_gzip_b64):
        mock_journalctl.return_value = True
        ret = 'Patrick Star'
        mock_gzip_b64.return_value = ret

        logs_string = utils.collect_system_logs()
        self.assertEqual(ret, logs_string)
        mock_logs.assert_called_once_with(lines=None)
        mock_gzip_b64.assert_called_once_with(
            io_dict=mock.ANY, file_list=[])
        mock_dispatch.assert_called_once_with('collect_system_logs',
                                              mock.ANY, [])

    @mock.patch.object(utils, 'gzip_and_b64encode', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_all_managers', autospec=True)
    @mock.patch.object(utils, 'is_journalctl_present', autospec=True)
    @mock.patch.object(utils, 'get_journalctl_output', autospec=True)
    def test_collect_system_logs_journald_with_logfile(
            self, mock_logs, mock_journalctl, mock_dispatch, mock_gzip_b64):
        tmp = tempfile.NamedTemporaryFile()
        self.addCleanup(lambda: tmp.close())

        self.config(log_file=tmp.name)
        mock_journalctl.return_value = True
        ret = 'Patrick Star'
        mock_gzip_b64.return_value = ret

        logs_string = utils.collect_system_logs()
        self.assertEqual(ret, logs_string)
        mock_logs.assert_called_once_with(lines=None)
        mock_gzip_b64.assert_called_once_with(
            io_dict=mock.ANY, file_list=[tmp.name])
        mock_dispatch.assert_called_once_with('collect_system_logs',
                                              mock.ANY, [tmp.name])

    @mock.patch.object(utils, 'gzip_and_b64encode', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_all_managers', autospec=True)
    @mock.patch.object(utils, 'is_journalctl_present', autospec=True)
    def test_collect_system_logs_non_journald(
            self, mock_journalctl, mock_dispatch, mock_gzip_b64):
        mock_journalctl.return_value = False
        ret = 'SpongeBob SquarePants'
        mock_gzip_b64.return_value = ret

        logs_string = utils.collect_system_logs()
        self.assertEqual(ret, logs_string)
        mock_gzip_b64.assert_called_once_with(
            io_dict=mock.ANY, file_list=['/var/log'])
        mock_dispatch.assert_called_once_with('collect_system_logs',
                                              mock.ANY, ['/var/log'])

    @mock.patch.object(utils, 'gzip_and_b64encode', autospec=True)
    @mock.patch.object(hardware, 'dispatch_to_all_managers', autospec=True)
    @mock.patch.object(utils, 'is_journalctl_present', autospec=True)
    def test_collect_system_logs_non_journald_with_logfile(
            self, mock_journalctl, mock_dispatch, mock_gzip_b64):
        tmp = tempfile.NamedTemporaryFile()
        self.addCleanup(lambda: tmp.close())

        self.config(log_file=tmp.name)
        mock_journalctl.return_value = False
        ret = 'SpongeBob SquarePants'
        mock_gzip_b64.return_value = ret

        logs_string = utils.collect_system_logs()
        self.assertEqual(ret, logs_string)
        mock_gzip_b64.assert_called_once_with(
            io_dict=mock.ANY, file_list=['/var/log', tmp.name])
        mock_dispatch.assert_called_once_with('collect_system_logs',
                                              mock.ANY, ['/var/log', tmp.name])

    def test_get_ssl_client_options(self):
        # defaults
        conf = mock.Mock(insecure=False, cafile=None,
                         keyfile=None, certfile=None)
        self.assertEqual((True, None), utils.get_ssl_client_options(conf))

        # insecure=True overrides cafile
        conf = mock.Mock(insecure=True, cafile='spam',
                         keyfile=None, certfile=None)
        self.assertEqual((False, None), utils.get_ssl_client_options(conf))

        # cafile returned as verify when not insecure
        conf = mock.Mock(insecure=False, cafile='spam',
                         keyfile=None, certfile=None)
        self.assertEqual(('spam', None), utils.get_ssl_client_options(conf))

        # only both certfile and keyfile produce non-None result
        conf = mock.Mock(insecure=False, cafile=None,
                         keyfile=None, certfile='ham')
        self.assertEqual((True, None), utils.get_ssl_client_options(conf))

        conf = mock.Mock(insecure=False, cafile=None,
                         keyfile='ham', certfile=None)
        self.assertEqual((True, None), utils.get_ssl_client_options(conf))

        conf = mock.Mock(insecure=False, cafile=None,
                         keyfile='spam', certfile='ham')
        self.assertEqual((True, ('ham', 'spam')),
                         utils.get_ssl_client_options(conf))

    def test_device_extractor(self):
        self.assertEqual(
            'md0',
            utils.extract_device('md0p1')
        )
        self.assertEqual(
            '/dev/md0',
            utils.extract_device('/dev/md0p1')
        )
        self.assertEqual(
            'sda',
            utils.extract_device('sda12')
        )
        self.assertEqual(
            '/dev/sda',
            utils.extract_device('/dev/sda12')
        )
        self.assertEqual(
            'nvme0n1',
            utils.extract_device('nvme0n1p12')
        )
        self.assertEqual(
            '/dev/nvme0n1',
            utils.extract_device('/dev/nvme0n1p12')
        )
        self.assertEqual(
            '/dev/hello',
            utils.extract_device('/dev/hello42')
        )
        self.assertIsNone(
            utils.extract_device('/dev/sda')
        )
        self.assertIsNone(
            utils.extract_device('whatevernotmatchin12a')
        )

    def test_extract_capability_from_dict(self):
        expected_dict = {"hello": "world"}
        root = {"capabilities": expected_dict}

        self.assertDictEqual(
            expected_dict,
            utils.parse_capabilities(root))

    def test_extract_capability_from_json_string(self):
        root = {'capabilities': '{"test": "world"}'}
        self.assertDictEqual(
            {"test": "world"},
            utils.parse_capabilities(root))

    def test_extract_capability_from_old_format_caps(self):
        root = {'capabilities': 'test:world:2,hello:test1,badformat'}
        self.assertDictEqual(
            {'hello': 'test1'},
            utils.parse_capabilities(root))

    @mock.patch.object(os.path, 'isdir', return_value=True, autospec=True)
    def test_boot_mode_fallback_uefi(self, mock_os):
        node = {}
        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_boot_mode_fallback_bios(self, mock_os):
        node = {}
        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('bios', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_boot_mode_from_driver_internal_info(self, mock_os):
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'uefi'
            },
        }
        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_boot_mode_from_properties_str(self, mock_os):
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'bios'
            },
            'properties': {
                'capabilities': 'boot_mode:uefi'
            }
        }
        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_boot_mode_from_properties_dict(self, mock_os):
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'bios'
            },
            'properties': {
                'capabilities': {
                    'boot_mode': 'uefi'
                }
            }
        }
        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_boot_mode_from_properties_json_str(self, mock_os):
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'bios'
            },
            'properties': {
                'capabilities': '{"boot_mode": "uefi"}'
            }
        }
        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_boot_mode_override_with_instance_info(self, mock_os):
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'bios'
            },
            'properties': {
                'capabilities': {
                    'boot_mode': 'bios'
                }
            },
            'instance_info': {
                'deploy_boot_mode': 'uefi'
            }
        }

        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_boot_mode_implicit_with_secure_boot(self, mock_os):
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'bios'
            },
            'properties': {
                'capabilities': {
                    'boot_mode': 'bios',
                    'secure_boot': 'TrUe'
                }
            },
            'instance_info': {
                'deploy_boot_mode': 'bios'
            }
        }

        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_has_calls([])

    @mock.patch.object(os.path, 'isdir', return_value=False, autospec=True)
    def test_secure_boot_overriden_with_instance_info_caps(self, mock_os):
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'bios'
            },
            'properties': {
                'capabilities': {
                    'boot_mode': 'bios',
                    'secure_boot': 'false'
                }
            },
            'instance_info': {
                'deploy_boot_mode': 'bios',
                'capabilities': {
                    'secure_boot': 'true'
                }
            }
        }

        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_has_calls([])

    @mock.patch.object(os.path, 'isdir', return_value=True, autospec=True)
    def test_boot_mode_invalid_cap(self, mock_os):
        # In case of invalid boot mode specified we fallback to ramdisk boot
        # mode
        node = {
            'driver_internal_info': {
                'deploy_boot_mode': 'bios'
            },
            'properties': {
                'capabilities': {
                    'boot_mode': 'sfkshfks'
                }
            }
        }
        boot_mode = utils.get_node_boot_mode(node)
        self.assertEqual('uefi', boot_mode)
        mock_os.assert_called_once_with('/sys/firmware/efi')

    @mock.patch.object(utils, 'get_node_boot_mode', return_value='bios',
                       autospec=True)
    def test_specified_partition_table_type(self, mock_boot_mode):
        node = {}
        label = utils.get_partition_table_type_from_specs(node)
        self.assertEqual('msdos', label)
        mock_boot_mode.assert_called_once_with(node)

    @mock.patch.object(utils, 'get_node_boot_mode', return_value='uefi',
                       autospec=True)
    def test_specified_partition_table_type_gpt(self, mock_boot_mode):
        node = {}
        label = utils.get_partition_table_type_from_specs(node)
        self.assertEqual('gpt', label)
        mock_boot_mode.assert_called_once_with(node)

    @mock.patch.object(utils, 'get_node_boot_mode', return_value='bios',
                       autospec=True)
    def test_specified_partition_table_type_with_disk_label(self,
                                                            mock_boot_mode):
        node = {
            'properties': {
                'capabilities': 'disk_label:gpt'
            }
        }
        label = utils.get_partition_table_type_from_specs(node)
        self.assertEqual('gpt', label)
        mock_boot_mode.assert_has_calls([])

    @mock.patch.object(utils, 'get_node_boot_mode', return_value='bios',
                       autospec=True)
    def test_specified_partition_table_type_with_instance_disk_label(
            self, mock_boot_mode):
        # In case of invalid boot mode specified we fallback to ramdisk boot
        # mode
        node = {
            'instance_info': {
                'capabilities': 'disk_label:gpt'
            }
        }
        label = utils.get_partition_table_type_from_specs(node)
        self.assertEqual('gpt', label)
        mock_boot_mode.assert_has_calls([])

    @mock.patch.object(utils, 'get_node_boot_mode', return_value='uefi',
                       autospec=True)
    def test_specified_partition_table_type_disk_label_ignored_with_uefi(
            self, mock_boot_mode):
        # In case of invalid boot mode specified we fallback to ramdisk boot
        # mode
        node = {
            'instance_info': {
                'capabilities': 'disk_label:msdos'
            }
        }
        label = utils.get_partition_table_type_from_specs(node)
        self.assertEqual('gpt', label)
        mock_boot_mode.assert_has_calls([])


class TestRemoveKeys(testtools.TestCase):
    def test_remove_keys(self):
        value = {'system_logs': 'abcd',
                 'key': 'value',
                 'other': [{'configdrive': 'foo'}, 'string', 0]}
        expected = {'system_logs': '<...>',
                    'key': 'value',
                    'other': [{'configdrive': '<...>'}, 'string', 0]}
        self.assertEqual(expected, utils.remove_large_keys(value))


@mock.patch.object(utils, 'execute', autospec=True)
class TestClockSyncUtils(ironic_agent_base.IronicAgentTest):

    def test_determine_time_method_none(self, mock_execute):
        mock_execute.side_effect = OSError
        self.assertIsNone(utils.determine_time_method())

    def test_determine_time_method_ntpdate(self, mock_execute):
        mock_execute.side_effect = [
            OSError,  # No chronyd found
            ('', ''),  # Returns nothing on ntpdate call
        ]
        calls = [mock.call('chronyd', '-h'),
                 mock.call('ntpdate', '-v', check_exit_code=[0, 1])]
        return_value = utils.determine_time_method()
        self.assertEqual('ntpdate', return_value)
        mock_execute.assert_has_calls(calls)

    def test_determine_time_method_chronyd(self, mock_execute):
        mock_execute.side_effect = [
            ('', ''),  # Returns nothing on ntpdate call
        ]
        calls = [mock.call('chronyd', '-h')]
        return_value = utils.determine_time_method()
        self.assertEqual('chronyd', return_value)
        mock_execute.assert_has_calls(calls)

    @mock.patch.object(utils, 'determine_time_method', autospec=True)
    def test_sync_clock_ntp(self, mock_time_method, mock_execute):
        self.config(ntp_server='192.168.1.1')
        mock_time_method.return_value = 'ntpdate'
        utils.sync_clock()
        mock_execute.assert_has_calls([mock.call('ntpdate', '192.168.1.1')])

    @mock.patch.object(utils, 'determine_time_method', autospec=True)
    def test_sync_clock_ntp_raises_exception(self, mock_time_method,
                                             mock_execute):
        self.config(ntp_server='192.168.1.1')
        self.config(fail_if_clock_not_set=True)
        mock_time_method.return_value = 'ntpdate'
        mock_execute.side_effect = processutils.ProcessExecutionError()
        self.assertRaises(errors.CommandExecutionError, utils.sync_clock)

    @mock.patch.object(utils, 'determine_time_method', autospec=True)
    def test_sync_clock_chrony(self, mock_time_method, mock_execute):
        self.config(ntp_server='192.168.1.1')
        mock_time_method.return_value = 'chronyd'
        utils.sync_clock()
        mock_execute.assert_has_calls([
            mock.call('chronyc', 'shutdown', check_exit_code=[0, 1]),
            mock.call("chronyd -q 'server 192.168.1.1 iburst'", shell=True),
        ])

    @mock.patch.object(utils, 'determine_time_method', autospec=True)
    def test_sync_clock_chrony_failure(self, mock_time_method, mock_execute):
        self.config(ntp_server='192.168.1.1')
        self.config(fail_if_clock_not_set=True)
        mock_time_method.return_value = 'chronyd'
        mock_execute.side_effect = [
            ('', ''),
            processutils.ProcessExecutionError(stderr='time verboten'),
        ]
        self.assertRaisesRegex(errors.CommandExecutionError,
                               'Failed to sync time using chrony to ntp '
                               'server:', utils.sync_clock)

    @mock.patch.object(utils, 'determine_time_method', autospec=True)
    def test_sync_clock_none(self, mock_time_method, mock_execute):
        self.config(ntp_server='192.168.1.1')
        mock_time_method.return_value = None
        utils.sync_clock(ignore_errors=True)
        self.assertEqual(0, mock_execute.call_count)

    @mock.patch.object(utils, 'determine_time_method', autospec=True)
    def test_sync_clock_ntp_server_is_none(self, mock_time_method,
                                           mock_execute):
        self.config(ntp_server=None)
        mock_time_method.return_value = None
        utils.sync_clock()
        self.assertEqual(0, mock_execute.call_count)


@mock.patch.object(utils, '_booted_from_vmedia', autospec=True)
@mock.patch.object(utils, '_check_vmedia_device', autospec=True)
@mock.patch.object(utils, '_find_vmedia_device_by_labels', autospec=True)
@mock.patch.object(shutil, 'copy', autospec=True)
@mock.patch.object(ironic_utils, 'mounted', autospec=True)
@mock.patch.object(utils, 'execute', autospec=True)
class TestCopyConfigFromVmedia(testtools.TestCase):

    def test_vmedia_found_not_booted_from_vmedia(
            self, mock_execute, mock_mount, mock_copy,
            mock_find_device, mock_check_vmedia, mock_booted_from_vmedia):
        mock_booted_from_vmedia.return_value = False
        mock_find_device.return_value = '/dev/fake'
        utils.copy_config_from_vmedia()
        mock_mount.assert_not_called()
        mock_execute.assert_not_called()
        mock_copy.assert_not_called()
        mock_check_vmedia.assert_not_called()
        self.assertTrue(mock_booted_from_vmedia.called)

    def test_no_vmedia(
            self, mock_execute, mock_mount, mock_copy,
            mock_find_device, mock_check_vmedia, mock_booted_from_vmedia):
        mock_booted_from_vmedia.return_value = True
        mock_find_device.return_value = None
        utils.copy_config_from_vmedia()
        mock_mount.assert_not_called()
        mock_execute.assert_not_called()
        mock_copy.assert_not_called()
        mock_check_vmedia.assert_not_called()
        self.assertFalse(mock_booted_from_vmedia.called)

    def test_no_files(
            self, mock_execute, mock_mount, mock_copy,
            mock_find_device, mock_check_vmedia, mock_booted_from_vmedia):
        mock_booted_from_vmedia.return_value = True
        temp_path = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(temp_path))

        mock_execute.side_effect = processutils.ProcessExecutionError
        mock_find_device.return_value = '/dev/something'
        mock_mount.return_value.__enter__.return_value = temp_path
        utils.copy_config_from_vmedia()
        mock_mount.assert_called_once_with('/dev/something')
        mock_execute.assert_called_once_with('findmnt', '-n', '-oTARGET',
                                             '/dev/something')
        mock_copy.assert_not_called()
        self.assertTrue(mock_booted_from_vmedia.called)

    def test_mounted_no_files(
            self, mock_execute, mock_mount, mock_copy,
            mock_find_device, mock_check_vmedia, mock_booted_from_vmedia):

        mock_booted_from_vmedia.return_value = True
        mock_execute.return_value = '/some/path', ''
        mock_find_device.return_value = '/dev/something'
        utils.copy_config_from_vmedia()
        mock_execute.assert_called_once_with(
            'findmnt', '-n', '-oTARGET', '/dev/something')
        mock_copy.assert_not_called()
        mock_mount.assert_not_called()
        self.assertTrue(mock_booted_from_vmedia.called)

    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_copy(
            self, mock_makedirs, mock_execute, mock_mount, mock_copy,
            mock_find_device, mock_check_vmedia, mock_booted_from_vmedia):

        mock_booted_from_vmedia.return_value = True
        mock_find_device.return_value = '/dev/something'
        mock_execute.side_effect = processutils.ProcessExecutionError("")
        path = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(path))

        def _fake_mount(dev):
            self.assertEqual('/dev/something', dev)
            # NOTE(dtantsur): makedirs is mocked
            os.mkdir(os.path.join(path, 'etc'))
            os.mkdir(os.path.join(path, 'etc', 'ironic-python-agent'))
            os.mkdir(os.path.join(path, 'etc', 'ironic-python-agent.d'))
            with open(os.path.join(path, 'not copied'), 'wt') as fp:
                fp.write('not copied')
            with open(os.path.join(path, 'etc', 'ironic-python-agent',
                                   'ironic.crt'), 'wt') as fp:
                fp.write('I am a cert')
            with open(os.path.join(path, 'etc', 'ironic-python-agent.d',
                                   'ironic.conf'), 'wt') as fp:
                fp.write('I am a config')
            return mock.MagicMock(**{'__enter__.return_value': path})

        mock_find_device.return_value = '/dev/something'
        mock_mount.side_effect = _fake_mount

        utils.copy_config_from_vmedia()

        mock_makedirs.assert_has_calls([
            mock.call('/etc/ironic-python-agent', exist_ok=True),
            mock.call('/etc/ironic-python-agent.d', exist_ok=True),
        ], any_order=True)
        mock_mount.assert_called_once_with('/dev/something')
        mock_copy.assert_has_calls([
            mock.call(mock.ANY, '/etc/ironic-python-agent/ironic.crt'),
            mock.call(mock.ANY, '/etc/ironic-python-agent.d/ironic.conf'),
        ], any_order=True)
        self.assertTrue(mock_booted_from_vmedia.called)

    @mock.patch.object(os, 'makedirs', autospec=True)
    def test_copy_mounted(
            self, mock_makedirs, mock_execute, mock_mount,
            mock_copy, mock_find_device, mock_check_vmedia,
            mock_booted_from_vmedia):
        mock_booted_from_vmedia.return_value = True
        mock_find_device.return_value = '/dev/something'
        path = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(path))

        # NOTE(dtantsur): makedirs is mocked
        os.mkdir(os.path.join(path, 'etc'))
        os.mkdir(os.path.join(path, 'etc', 'ironic-python-agent'))
        os.mkdir(os.path.join(path, 'etc', 'ironic-python-agent.d'))
        with open(os.path.join(path, 'not copied'), 'wt') as fp:
            fp.write('not copied')
        with open(os.path.join(path, 'etc', 'ironic-python-agent',
                               'ironic.crt'), 'wt') as fp:
            fp.write('I am a cert')
        with open(os.path.join(path, 'etc', 'ironic-python-agent.d',
                               'ironic.conf'), 'wt') as fp:
            fp.write('I am a config')

        mock_execute.return_value = path, ''
        mock_find_device.return_value = '/dev/something'

        utils.copy_config_from_vmedia()

        mock_makedirs.assert_has_calls([
            mock.call('/etc/ironic-python-agent', exist_ok=True),
            mock.call('/etc/ironic-python-agent.d', exist_ok=True),
        ], any_order=True)
        mock_execute.assert_called_once_with(
            'findmnt', '-n', '-oTARGET', '/dev/something')
        mock_copy.assert_has_calls([
            mock.call(mock.ANY, '/etc/ironic-python-agent/ironic.crt'),
            mock.call(mock.ANY, '/etc/ironic-python-agent.d/ironic.conf'),
        ], any_order=True)
        mock_mount.assert_not_called()
        self.assertTrue(mock_booted_from_vmedia.called)


@mock.patch.object(requests, 'get', autospec=True)
class TestStreamingClient(ironic_agent_base.IronicAgentTest):

    def test_ok(self, mock_get):
        client = utils.StreamingClient()
        self.assertTrue(client.verify)
        self.assertIsNone(client.cert)

        with client("http://url") as result:
            response = mock_get.return_value.__enter__.return_value
            self.assertIs(result, response.iter_content.return_value)

        mock_get.assert_called_once_with("http://url", verify=True, cert=None,
                                         stream=True, timeout=60)
        response.iter_content.assert_called_once_with(1024 * 1024)

    def test_retries(self, mock_get):
        self.config(image_download_connection_retries=1,
                    image_download_connection_retry_interval=1)
        mock_get.side_effect = requests.ConnectionError

        client = utils.StreamingClient()
        self.assertRaises(errors.CommandExecutionError,
                          client("http://url").__enter__)

        mock_get.assert_called_with("http://url", verify=True, cert=None,
                                    stream=True, timeout=60)
        self.assertEqual(2, mock_get.call_count)


class TestCheckVirtualMedia(ironic_agent_base.IronicAgentTest):

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_vmedia_device(self, mock_execute):
        lsblk = 'KNAME="sdh" SIZE="1610612736" TYPE="disk" TRAN="usb"\n'
        mock_execute.return_value = (lsblk, '')
        self.assertTrue(utils._check_vmedia_device('/dev/sdh'))
        mock_execute.assert_called_with('lsblk', '-n', '-s', '-P', '-b',
                                        '-oKNAME,TRAN,TYPE,SIZE',
                                        '/dev/sdh')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_vmedia_device_rom(self, mock_execute):
        lsblk = 'KNAME="sr0" SIZE="1610612736" TYPE="rom" TRAN="usb"\n'
        mock_execute.return_value = (lsblk, '')
        self.assertTrue(utils._check_vmedia_device('/dev/sr0'))
        mock_execute.assert_called_with('lsblk', '-n', '-s', '-P', '-b',
                                        '-oKNAME,TRAN,TYPE,SIZE',
                                        '/dev/sr0')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_vmedia_device_too_large(self, mock_execute):
        lsblk = 'KNAME="sdh" SIZE="1610612736000" TYPE="disk" TRAN="usb"\n'
        mock_execute.return_value = (lsblk, '')
        self.assertFalse(utils._check_vmedia_device('/dev/sdh'))
        mock_execute.assert_called_with('lsblk', '-n', '-s', '-P', '-b',
                                        '-oKNAME,TRAN,TYPE,SIZE',
                                        '/dev/sdh')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_vmedia_device_part(self, mock_execute):
        lsblk = ('KNAME="sdh1" SIZE="1610612736" TYPE="part" TRAN=""\n'
                 'KNAME="sdh" SIZE="1610612736" TYPE="disk" TRAN="sata"\n')
        mock_execute.return_value = (lsblk, '')
        self.assertFalse(utils._check_vmedia_device('/dev/sdh1'))
        mock_execute.assert_called_with('lsblk', '-n', '-s', '-P', '-b',
                                        '-oKNAME,TRAN,TYPE,SIZE',
                                        '/dev/sdh1')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_vmedia_device_other(self, mock_execute):
        lsblk = 'KNAME="sdh" SIZE="1610612736" TYPE="other" TRAN="usb"\n'
        mock_execute.return_value = (lsblk, '')
        self.assertFalse(utils._check_vmedia_device('/dev/sdh'))
        mock_execute.assert_called_with('lsblk', '-n', '-s', '-P', '-b',
                                        '-oKNAME,TRAN,TYPE,SIZE',
                                        '/dev/sdh')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_vmedia_device_sata(self, mock_execute):
        lsblk = 'KNAME="sdh" SIZE="1610612736" TYPE="disk" TRAN="sata"\n'
        mock_execute.return_value = (lsblk, '')
        self.assertFalse(utils._check_vmedia_device('/dev/sdh'))
        mock_execute.assert_called_with('lsblk', '-n', '-s', '-P', '-b',
                                        '-oKNAME,TRAN,TYPE,SIZE',
                                        '/dev/sdh')

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_check_vmedia_device_scsi(self, mock_execute):
        lsblk = 'KNAME="sdh" SIZE="1610612736" TYPE="other" TRAN="scsi"\n'
        mock_execute.return_value = (lsblk, '')
        self.assertFalse(utils._check_vmedia_device('/dev/sdh'))
        mock_execute.assert_called_with('lsblk', '-n', '-s', '-P', '-b',
                                        '-oKNAME,TRAN,TYPE,SIZE',
                                        '/dev/sdh')


class TestCheckEarlyLogging(ironic_agent_base.IronicAgentTest):

    @mock.patch.object(utils, 'LOG', autospec=True)
    def test_early_logging_goes_to_logger(self, mock_log):
        info = mock.Mock()
        mock_log.info.side_effect = info
        # Reset the buffer to be empty.
        utils._EARLY_LOG_BUFFER = []
        # Store some data via _early_log
        utils._early_log('line 1.')
        utils._early_log('line 2 %s', 'message')
        expected_messages = ['line 1.',
                             'line 2 message']
        self.assertEqual(expected_messages, utils._EARLY_LOG_BUFFER)
        # Test we've got data in the buffer.
        info.assert_not_called()
        # Test the other half of this.
        utils.log_early_log_to_logger()
        expected_calls = [mock.call('Early logging: %s', 'line 1.'),
                          mock.call('Early logging: %s', 'line 2 message')]
        info.assert_has_calls(expected_calls)

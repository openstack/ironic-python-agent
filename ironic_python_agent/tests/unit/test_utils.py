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

import errno
import glob
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import testtools

from ironic_lib import utils as ironic_utils
import mock
from oslo_concurrency import processutils
from oslo_serialization import base64
from oslotest import base as test_base

from ironic_python_agent import errors
from ironic_python_agent import utils


class ExecuteTestCase(test_base.BaseTestCase):

    @mock.patch.object(ironic_utils, 'execute', autospec=True)
    def test_execute(self, mock_execute):
        utils.execute('/usr/bin/env', 'false', check_exit_code=False)
        mock_execute.assert_called_once_with('/usr/bin/env', 'false',
                                             check_exit_code=False)


class GetAgentParamsTestCase(test_base.BaseTestCase):

    @mock.patch('oslo_log.log.getLogger')
    @mock.patch('six.moves.builtins.open')
    def test__read_params_from_file_fail(self, logger_mock, open_mock):
        open_mock.side_effect = Exception
        params = utils._read_params_from_file('file-path')
        self.assertEqual({}, params)

    @mock.patch('six.moves.builtins.open')
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

    @mock.patch.object(utils, '_set_cached_params')
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(utils, '_get_cached_params')
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

    @mock.patch.object(utils, '_set_cached_params')
    @mock.patch.object(utils, '_get_vmedia_params')
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(utils, '_get_cached_params')
    def test_get_agent_params_vmedia(self, get_cache_mock,
                                     read_params_mock,
                                     get_vmedia_params_mock,
                                     set_cache_mock):
        get_cache_mock.return_value = {}
        kernel_params = {'boot_method': 'vmedia'}
        vmedia_params = {'a': 'b'}
        expected_params = dict(list(kernel_params.items()) +
                               list(vmedia_params.items()))
        read_params_mock.return_value = kernel_params
        get_vmedia_params_mock.return_value = vmedia_params

        returned_params = utils.get_agent_params()
        read_params_mock.assert_called_once_with('/proc/cmdline')
        self.assertEqual(expected_params, returned_params)
        # Make sure information is cached
        set_cache_mock.assert_called_once_with(expected_params)

    @mock.patch.object(utils, '_set_cached_params')
    @mock.patch.object(utils, '_get_cached_params')
    def test_get_agent_params_from_cache(self, get_cache_mock,
                                         set_cache_mock):
        get_cache_mock.return_value = {'a': 'b'}
        returned_params = utils.get_agent_params()
        expected_params = {'a': 'b'}
        self.assertEqual(expected_params, returned_params)
        self.assertEqual(0, set_cache_mock.call_count)

    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(glob, 'glob')
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

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_by_label_lower_case(
            self, execute_mock, mkdir_mock, exists_mock, read_params_mock,
            mkdtemp_mock, rmtree_mock):
        mkdtemp_mock.return_value = "/tempdir"

        null_output = ["", ""]
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        exists_mock.side_effect = [True, False]
        execute_mock.side_effect = [null_output, null_output]

        returned_params = utils._get_vmedia_params()

        execute_mock.assert_any_call('mount', "/dev/disk/by-label/ir-vfd-dev",
                                     "/tempdir")
        read_params_mock.assert_called_once_with("/tempdir/parameters.txt")
        exists_mock.assert_called_once_with("/dev/disk/by-label/ir-vfd-dev")
        execute_mock.assert_any_call('umount', "/tempdir")
        self.assertEqual(expected_params, returned_params)
        mkdtemp_mock.assert_called_once_with()
        rmtree_mock.assert_called_once_with("/tempdir")

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_by_label_upper_case(
            self, execute_mock, mkdir_mock, exists_mock, read_params_mock,
            mkdtemp_mock, rmtree_mock):
        mkdtemp_mock.return_value = "/tempdir"

        null_output = ["", ""]
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        exists_mock.side_effect = [False, True]
        execute_mock.side_effect = [null_output, null_output]

        returned_params = utils._get_vmedia_params()

        execute_mock.assert_any_call('mount', "/dev/disk/by-label/IR-VFD-DEV",
                                     "/tempdir")
        read_params_mock.assert_called_once_with("/tempdir/parameters.txt")
        exists_mock.assert_has_calls(
            [mock.call("/dev/disk/by-label/ir-vfd-dev"),
             mock.call("/dev/disk/by-label/IR-VFD-DEV")])
        execute_mock.assert_any_call('umount', "/tempdir")
        self.assertEqual(expected_params, returned_params)
        mkdtemp_mock.assert_called_once_with()
        rmtree_mock.assert_called_once_with("/tempdir")

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_device')
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_by_device(self, execute_mock, mkdir_mock,
                                          exists_mock, read_params_mock,
                                          get_device_mock, mkdtemp_mock,
                                          rmtree_mock):
        mkdtemp_mock.return_value = "/tempdir"

        null_output = ["", ""]
        expected_params = {'a': 'b'}
        read_params_mock.return_value = expected_params
        exists_mock.side_effect = [False, False]
        execute_mock.side_effect = [null_output, null_output]
        get_device_mock.return_value = "sda"

        returned_params = utils._get_vmedia_params()

        exists_mock.assert_has_calls(
            [mock.call("/dev/disk/by-label/ir-vfd-dev"),
             mock.call("/dev/disk/by-label/IR-VFD-DEV")])
        execute_mock.assert_any_call('mount', "/dev/sda",
                                     "/tempdir")
        read_params_mock.assert_called_once_with("/tempdir/parameters.txt")
        execute_mock.assert_any_call('umount', "/tempdir")
        self.assertEqual(expected_params, returned_params)
        mkdtemp_mock.assert_called_once_with()
        rmtree_mock.assert_called_once_with("/tempdir")

    @mock.patch.object(utils, '_get_vmedia_device')
    @mock.patch.object(os.path, 'exists')
    def test__get_vmedia_params_cannot_find_dev(self, exists_mock,
                                                get_device_mock):
        get_device_mock.return_value = None
        exists_mock.return_value = False
        self.assertRaises(errors.VirtualMediaBootError,
                          utils._get_vmedia_params)

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_device')
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_mount_fails(self, execute_mock,
                                            mkdir_mock, exists_mock,
                                            read_params_mock,
                                            get_device_mock, mkdtemp_mock,
                                            rmtree_mock):
        mkdtemp_mock.return_value = "/tempdir"

        expected_params = {'a': 'b'}
        exists_mock.return_value = True
        read_params_mock.return_value = expected_params
        get_device_mock.return_value = "sda"

        execute_mock.side_effect = processutils.ProcessExecutionError()

        self.assertRaises(errors.VirtualMediaBootError,
                          utils._get_vmedia_params)

        execute_mock.assert_any_call('mount', "/dev/disk/by-label/ir-vfd-dev",
                                     "/tempdir")
        mkdtemp_mock.assert_called_once_with()
        rmtree_mock.assert_called_once_with("/tempdir")

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_device')
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_umount_fails(self, execute_mock, mkdir_mock,
                                             exists_mock, read_params_mock,
                                             get_device_mock, mkdtemp_mock,
                                             rmtree_mock):
        mkdtemp_mock.return_value = "/tempdir"

        null_output = ["", ""]
        expected_params = {'a': 'b'}
        exists_mock.return_value = True
        read_params_mock.return_value = expected_params
        get_device_mock.return_value = "sda"

        execute_mock.side_effect = [null_output,
                                    processutils.ProcessExecutionError()]

        returned_params = utils._get_vmedia_params()

        execute_mock.assert_any_call('mount', "/dev/disk/by-label/ir-vfd-dev",
                                     "/tempdir")
        read_params_mock.assert_called_once_with("/tempdir/parameters.txt")
        execute_mock.assert_any_call('umount', "/tempdir")
        self.assertEqual(expected_params, returned_params)
        mkdtemp_mock.assert_called_once_with()
        rmtree_mock.assert_called_once_with("/tempdir")

    @mock.patch.object(shutil, 'rmtree', autospec=True)
    @mock.patch.object(tempfile, 'mkdtemp', autospec=True)
    @mock.patch.object(utils, '_get_vmedia_device')
    @mock.patch.object(utils, '_read_params_from_file')
    @mock.patch.object(os.path, 'exists')
    @mock.patch.object(os, 'mkdir')
    @mock.patch.object(utils, 'execute')
    def test__get_vmedia_params_rmtree_fails(self, execute_mock, mkdir_mock,
                                             exists_mock, read_params_mock,
                                             get_device_mock, mkdtemp_mock,
                                             rmtree_mock):
        mkdtemp_mock.return_value = "/tempdir"
        rmtree_mock.side_effect = Exception

        null_output = ["", ""]
        expected_params = {'a': 'b'}
        exists_mock.return_value = True
        read_params_mock.return_value = expected_params
        get_device_mock.return_value = "sda"

        execute_mock.return_value = null_output

        returned_params = utils._get_vmedia_params()

        execute_mock.assert_any_call('mount', "/dev/disk/by-label/ir-vfd-dev",
                                     "/tempdir")
        read_params_mock.assert_called_once_with("/tempdir/parameters.txt")
        execute_mock.assert_any_call('umount', "/tempdir")
        self.assertEqual(expected_params, returned_params)
        mkdtemp_mock.assert_called_once_with()
        rmtree_mock.assert_called_once_with("/tempdir")


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


class TestUtils(testtools.TestCase):

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

        res = io.BytesIO(base64.decode_as_bytes(data))
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

    @mock.patch.object(subprocess, 'check_call')
    def test_is_journalctl_present(self, mock_call):
        self.assertTrue(utils.is_journalctl_present())

    @mock.patch.object(subprocess, 'check_call')
    def test_is_journalctl_present_false(self, mock_call):
        os_error = OSError()
        os_error.errno = errno.ENOENT
        mock_call.side_effect = os_error
        self.assertFalse(utils.is_journalctl_present())

    @mock.patch.object(utils, 'gzip_and_b64encode')
    @mock.patch.object(utils, 'is_journalctl_present')
    @mock.patch.object(utils, 'get_command_output')
    @mock.patch.object(utils, 'get_journalctl_output')
    def test_collect_system_logs_journald(
            self, mock_logs, mock_outputs, mock_journalctl, mock_gzip_b64):
        mock_journalctl.return_value = True
        ret = 'Patrick Star'
        mock_gzip_b64.return_value = ret

        logs_string = utils.collect_system_logs()
        self.assertEqual(ret, logs_string)
        mock_logs.assert_called_once_with(lines=None)
        calls = [mock.call(['ps', 'au']), mock.call(['df', '-a']),
                 mock.call(['iptables', '-L']), mock.call(['ip', 'addr'])]
        mock_outputs.assert_has_calls(calls, any_order=True)
        mock_gzip_b64.assert_called_once_with(
            file_list=[],
            io_dict={'journal': mock.ANY, 'ip_addr': mock.ANY, 'ps': mock.ANY,
                     'df': mock.ANY, 'iptables': mock.ANY})

    @mock.patch.object(utils, 'gzip_and_b64encode')
    @mock.patch.object(utils, 'is_journalctl_present')
    @mock.patch.object(utils, 'get_command_output')
    def test_collect_system_logs_non_journald(
            self, mock_outputs, mock_journalctl, mock_gzip_b64):
        mock_journalctl.return_value = False
        ret = 'SpongeBob SquarePants'
        mock_gzip_b64.return_value = ret

        logs_string = utils.collect_system_logs()
        self.assertEqual(ret, logs_string)
        calls = [mock.call(['dmesg']), mock.call(['ps', 'au']),
                 mock.call(['df', '-a']), mock.call(['iptables', '-L']),
                 mock.call(['ip', 'addr'])]
        mock_outputs.assert_has_calls(calls, any_order=True)
        mock_gzip_b64.assert_called_once_with(
            file_list=['/var/log'],
            io_dict={'iptables': mock.ANY, 'ip_addr': mock.ANY, 'ps': mock.ANY,
                     'dmesg': mock.ANY, 'df': mock.ANY})

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

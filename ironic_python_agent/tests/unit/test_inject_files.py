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
import shutil
import stat
import tempfile
from unittest import mock

from ironic_python_agent import errors
from ironic_python_agent import inject_files
from ironic_python_agent.tests.unit import base


@mock.patch('ironic_lib.utils.mounted', autospec=True)
@mock.patch('ironic_lib.disk_utils.list_partitions', autospec=True)
@mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
            lambda _call: '/dev/fake')
class TestFindPartitionWithPath(base.IronicAgentTest):

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tempdir))

    def test_found(self, mock_list_parts, mock_mount):
        mock_list_parts.return_value = [
            {'number': 1, 'flags': 'lvm'},
            {'number': 2, 'flags': 'boot'},
        ]
        mock_mount.return_value.__enter__.return_value = self.tempdir
        expected = os.path.join(self.tempdir, "some/path")
        os.makedirs(expected)

        with inject_files.find_partition_with_path("/some/path") as path:
            self.assertEqual(expected, path)

        mock_mount.assert_called_once_with('/dev/fake2')

    def test_found_with_dev(self, mock_list_parts, mock_mount):
        mock_list_parts.return_value = [
            {'number': 1, 'flags': 'lvm'},
            {'number': 2, 'flags': 'boot'},
        ]
        mock_mount.return_value.__enter__.return_value = self.tempdir
        expected = os.path.join(self.tempdir, "some/path")
        os.makedirs(expected)

        with inject_files.find_partition_with_path("/some/path",
                                                   "/dev/nvme0n1") as path:
            self.assertEqual(expected, path)

        mock_mount.assert_called_once_with('/dev/nvme0n1p2')

    def test_not_found(self, mock_list_parts, mock_mount):
        mock_list_parts.return_value = [
            {'number': 1, 'flags': 'lvm'},
            {'number': 2, 'flags': 'boot'},
            {'number': 3, 'flags': ''},
        ]
        mock_mount.return_value.__enter__.return_value = self.tempdir

        self.assertRaises(
            errors.DeviceNotFound,
            inject_files.find_partition_with_path("/some/path").__enter__)

        mock_mount.assert_has_calls([
            mock.call('/dev/fake2'),
            mock.call('/dev/fake3'),
        ], any_order=True)


class TestFindAndMountPath(base.IronicAgentTest):

    @mock.patch.object(inject_files, 'find_partition_with_path', autospec=True)
    def test_without_on(self, mock_find_part):
        mock_find_part.return_value.__enter__.return_value = '/mount/path'
        with inject_files._find_and_mount_path('/etc/sysctl.d/my.conf',
                                               None, '/dev/fake') as result:
            # "etc" is included in a real result of find_partition_with_path
            self.assertEqual('/mount/path/sysctl.d/my.conf', result)
        mock_find_part.assert_called_once_with('etc', '/dev/fake')

    def test_without_on_wrong_path(self):
        self.assertRaises(
            errors.InvalidCommandParamsError,
            inject_files._find_and_mount_path('/etc', None,
                                              '/dev/fake').__enter__)

    @mock.patch('ironic_lib.utils.mounted', autospec=True)
    def test_with_on_as_path(self, mock_mount):
        mock_mount.return_value.__enter__.return_value = '/mount/path'
        with inject_files._find_and_mount_path('/etc/sysctl.d/my.conf',
                                               '/dev/on',
                                               '/dev/fake') as result:
            self.assertEqual('/mount/path/etc/sysctl.d/my.conf', result)
        mock_mount.assert_called_once_with('/dev/on')

    @mock.patch('ironic_lib.utils.mounted', autospec=True)
    def test_with_on_as_number(self, mock_mount):
        mock_mount.return_value.__enter__.return_value = '/mount/path'
        with inject_files._find_and_mount_path('/etc/sysctl.d/my.conf',
                                               2, '/dev/fake') as result:
            self.assertEqual('/mount/path/etc/sysctl.d/my.conf', result)
        mock_mount.assert_called_once_with('/dev/fake2')

    @mock.patch('ironic_lib.utils.mounted', autospec=True)
    def test_with_on_as_number_nvme(self, mock_mount):
        mock_mount.return_value.__enter__.return_value = '/mount/path'
        with inject_files._find_and_mount_path('/etc/sysctl.d/my.conf',
                                               2, '/dev/nvme0n1') as result:
            self.assertEqual('/mount/path/etc/sysctl.d/my.conf', result)
        mock_mount.assert_called_once_with('/dev/nvme0n1p2')


@mock.patch.object(inject_files, '_find_and_mount_path', autospec=True)
class TestInjectOne(base.IronicAgentTest):

    def setUp(self):
        super().setUp()
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tempdir))
        self.dirpath = os.path.join(self.tempdir, 'dir1', 'dir2')
        self.path = os.path.join(self.dirpath, 'file.name')

        self.http_get = mock.MagicMock()
        self.http_get.return_value.__enter__.return_value = iter(
            [b'con', b'tent', b''])

        self.node = {'uuid': '1234'}
        self.ports = [{'address': 'aabb'}]

    def test_delete(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'deleted': True}
        os.makedirs(self.dirpath)
        with open(self.path, 'wb') as fp:
            fp.write(b'content')

        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.isdir(self.dirpath))
        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        self.http_get.assert_not_called()

    def test_delete_not_exists(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'deleted': True}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(os.path.isdir(self.dirpath))
        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        self.http_get.assert_not_called()

    def test_plain_content(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'content': 'Y29udGVudA=='}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())
        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        self.http_get.assert_not_called()

    def test_plain_content_with_on(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'content': 'Y29udGVudA==',
              'partition': '/dev/sda1'}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())
        mock_find_and_mount.assert_called_once_with(fl['path'], '/dev/sda1',
                                                    '/dev/root')
        self.http_get.assert_not_called()

    def test_plain_content_with_modes(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'content': 'Y29udGVudA==',
              'mode': 0o602, 'dirmode': 0o703}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())
        self.assertEqual(0o602, stat.S_IMODE(os.stat(self.path).st_mode))
        self.assertEqual(0o703, stat.S_IMODE(os.stat(self.dirpath).st_mode))

        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        self.http_get.assert_not_called()

    def test_plain_content_with_modes_exists(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'content': 'Y29udGVudA==',
              'mode': 0o602, 'dirmode': 0o703}
        os.makedirs(self.dirpath)
        with open(self.path, 'wb') as fp:
            fp.write(b"I'm not a cat, I'm a lawyer")

        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())
        self.assertEqual(0o602, stat.S_IMODE(os.stat(self.path).st_mode))
        # Exising directories do not change their permissions
        self.assertNotEqual(0o703, stat.S_IMODE(os.stat(self.dirpath).st_mode))

        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        self.http_get.assert_not_called()

    @mock.patch.object(os, 'chown', autospec=True)
    def test_plain_content_with_owner(self, mock_chown, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'content': 'Y29udGVudA==',
              'owner': 42}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())

        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        mock_chown.assert_called_once_with(self.path, 42, -1)
        self.http_get.assert_not_called()

    @mock.patch.object(os, 'chown', autospec=True)
    def test_plain_content_with_owner_and_group(self, mock_chown,
                                                mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name', 'content': 'Y29udGVudA==',
              'owner': 0, 'group': 0}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())

        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        mock_chown.assert_called_once_with(self.path, 0, 0)
        self.http_get.assert_not_called()

    def test_url(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name',
              'content': 'http://example.com/path'}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())

        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        self.http_get.assert_called_once_with('http://example.com/path')

    def test_url_formatting(self, mock_find_and_mount):
        mock_find_and_mount.return_value.__enter__.return_value = self.path

        fl = {'path': '/etc/dir1/dir2/file.name',
              'content': 'http://example.com/{node[uuid]}/{ports[0][address]}'}
        inject_files._inject_one(self.node, self.ports, fl,
                                 '/dev/root', self.http_get)

        with open(self.path, 'rb') as fp:
            self.assertEqual(b'content', fp.read())

        mock_find_and_mount.assert_called_once_with(fl['path'], None,
                                                    '/dev/root')
        self.http_get.assert_called_once_with('http://example.com/1234/aabb')


@mock.patch('ironic_python_agent.hardware.dispatch_to_managers',
            lambda _call: '/dev/root')
@mock.patch.object(inject_files, '_inject_one', autospec=True)
class TestInjectFiles(base.IronicAgentTest):

    def test_empty(self, mock_inject):
        node = {
            'properties': {}
        }

        inject_files.inject_files(node, [mock.sentinel.port], [])
        mock_inject.assert_not_called()

    def test_ok(self, mock_inject):
        node = {
            'properties': {
                'inject_files': [
                    {'path': '/etc/default/grub', 'content': 'abcdef'},
                    {'path': '/etc/default/bluetooth', 'deleted': True},
                ]
            }
        }
        files = [
            {'path': '/boot/special.conf',
             'content': 'http://example.com/data',
             'mode': 0o600, 'dirmode': 0o750, 'owner': 0, 'group': 0},
            {'path': 'service.conf', 'partition': '/dev/disk/by-label/OPT'},
        ]

        inject_files.inject_files(node, [mock.sentinel.port], files)

        mock_inject.assert_has_calls([
            mock.call(node, [mock.sentinel.port], fl, '/dev/root', mock.ANY)
            for fl in node['properties']['inject_files'] + files
        ])
        http_get = mock_inject.call_args_list[0][0][4]
        self.assertTrue(http_get.verify)
        self.assertIsNone(http_get.cert)

    def test_verify_false(self, mock_inject):
        node = {
            'properties': {
                'inject_files': [
                    {'path': '/etc/default/grub', 'content': 'abcdef'},
                    {'path': '/etc/default/bluetooth', 'deleted': True},
                ]
            }
        }
        files = [
            {'path': '/boot/special.conf',
             'content': 'http://example.com/data',
             'mode': 0o600, 'dirmode': 0o750, 'owner': 0, 'group': 0},
            {'path': 'service.conf', 'partition': '/dev/disk/by-label/OPT'},
        ]

        inject_files.inject_files(node, [mock.sentinel.port], files, False)

        mock_inject.assert_has_calls([
            mock.call(node, [mock.sentinel.port], fl, '/dev/root', mock.ANY)
            for fl in node['properties']['inject_files'] + files
        ])
        http_get = mock_inject.call_args_list[0][0][4]
        self.assertFalse(http_get.verify)
        self.assertIsNone(http_get.cert)

    def test_invalid_type_on_node(self, mock_inject):
        node = {
            'properties': {
                'inject_files': 42
            }
        }
        self.assertRaises(errors.InvalidCommandParamsError,
                          inject_files.inject_files, node, [], [])
        mock_inject.assert_not_called()

    def test_invalid_type_in_param(self, mock_inject):
        node = {
            'properties': {}
        }
        self.assertRaises(errors.InvalidCommandParamsError,
                          inject_files.inject_files, node, [], 42)
        mock_inject.assert_not_called()


class TestValidateFiles(base.IronicAgentTest):

    def test_missing_path(self):
        fl = {'deleted': True}
        self.assertRaisesRegex(errors.InvalidCommandParamsError, 'path',
                               inject_files._validate_files, [fl], [])

    def test_unknown_fields(self):
        fl = {'path': '/etc/passwd', 'cat': 'meow'}
        self.assertRaisesRegex(errors.InvalidCommandParamsError, 'cat',
                               inject_files._validate_files, [fl], [])

    def test_root_without_on(self):
        fl = {'path': '/something', 'content': 'abcd'}
        self.assertRaisesRegex(errors.InvalidCommandParamsError, 'partition',
                               inject_files._validate_files, [fl], [])

    def test_no_directories(self):
        fl = {'path': '/something/else/', 'content': 'abcd'}
        self.assertRaisesRegex(errors.InvalidCommandParamsError, 'directories',
                               inject_files._validate_files, [fl], [])

    def test_content_and_deleted(self):
        fl = {'path': '/etc/password', 'content': 'abcd', 'deleted': True}
        self.assertRaisesRegex(errors.InvalidCommandParamsError,
                               'content .* with deleted',
                               inject_files._validate_files, [fl], [])

    def test_numeric_fields(self):
        for field in ('owner', 'group', 'mode', 'dirmode'):
            fl = {'path': '/etc/password', 'content': 'abcd', field: 'name'}
            self.assertRaisesRegex(errors.InvalidCommandParamsError,
                                   'must be a number',
                                   inject_files._validate_files, [fl], [])

"""
Copyright 2013 Rackspace, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import unicode_literals

import base64
import json
import mock
import unittest

from teeth_agent import configdrive
from teeth_agent import utils


class ConfigDriveWriterTestCase(unittest.TestCase):
    def setUp(self):
        self.writer = configdrive.ConfigDriveWriter()
        self.maxDiff = None

    def test_add_metadata(self):
        self.writer.add_metadata('admin_pass', 'password')
        metadata = self.writer.metadata
        self.assertEqual(metadata, {'admin_pass': 'password'})

    def test_add_file(self):
        self.writer.add_file('/etc/filename', 'contents')
        files = self.writer.files
        self.assertEqual(files, {'/etc/filename': 'contents'})

    @mock.patch('os.makedirs', autospec=True)
    @mock.patch('__builtin__.open', autospec=True)
    def test_write_no_files(self, open_mock, makedirs_mock):
        metadata = {'admin_pass': 'password', 'hostname': 'test'}
        json_metadata = json.dumps(metadata)
        metadata_path = '/lol/teeth/latest/meta_data.json'
        for k, v in metadata.iteritems():
            self.writer.add_metadata(k, v)

        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        write_mock = open_mock.return_value.write

        self.writer.write('/lol', prefix='teeth', version='latest')
        open_mock.assert_called_once_with(metadata_path, 'wb')
        write_mock.assert_called_once_with(json_metadata)
        makedirs_calls = [
            mock.call('/lol/teeth/latest'),
            mock.call('/lol/teeth/content')
        ]
        self.assertEqual(makedirs_calls, makedirs_mock.call_args_list)

    @mock.patch('os.makedirs', autospec=True)
    @mock.patch('__builtin__.open', autospec=True)
    def test_write_with_files(self, open_mock, makedirs_mock):
        metadata = {'admin_pass': 'password', 'hostname': 'test'}
        for k, v in metadata.iteritems():
            self.writer.add_metadata(k, v)
        files = utils.get_ordereddict([
            ('/etc/conf0', 'contents0'),
            ('/etc/conf1', 'contents1'),
        ])
        for path, contents in files.iteritems():
            self.writer.add_file(path, contents)

        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        write_mock = open_mock.return_value.write

        metadata = self.writer.metadata
        metadata['files'] = [
            {'content_path': '/content/0000', 'path': '/etc/conf0'},
            {'content_path': '/content/0001', 'path': '/etc/conf1'},
        ]

        self.writer.write('/lol', prefix='openstack', version='latest')

        # have to pull out the JSON passed to write and parse it
        # because arbitrary dictionary ordering, etc
        calls = write_mock.mock_calls
        json_data = calls[-1][1][0]
        data = json.loads(json_data)
        self.assertEqual(data, metadata)

        open_calls = [
            mock.call('/lol/openstack/content/0000', 'wb'),
            mock.call().write('contents0'),
            mock.call().__exit__(None, None, None),
            mock.call('/lol/openstack/content/0001', 'wb'),
            mock.call().write('contents1'),
            mock.call().__exit__(None, None, None),
            mock.call('/lol/openstack/latest/meta_data.json', 'wb'),
            # already checked
            mock.call().write(mock.ANY),
            mock.call().__exit__(None, None, None),
        ]
        self.assertEqual(open_mock.mock_calls, open_calls)

        makedirs_calls = [
            mock.call('/lol/openstack/latest'),
            mock.call('/lol/openstack/content')
        ]
        self.assertEqual(makedirs_calls, makedirs_mock.call_args_list)

    @mock.patch('os.makedirs', autospec=True)
    @mock.patch('__builtin__.open', autospec=True)
    def test_write_configdrive(self, open_mock, makedirs_mock):
        metadata = {'admin_pass': 'password', 'hostname': 'test'}
        files = utils.get_ordereddict([
            ('/etc/conf0', base64.b64encode('contents0')),
            ('/etc/conf1', base64.b64encode('contents1')),
        ])
        metadata['files'] = [
            {'content_path': '/content/0000', 'path': '/etc/conf0'},
            {'content_path': '/content/0001', 'path': '/etc/conf1'},
        ]

        open_mock.return_value.__enter__ = lambda s: s
        open_mock.return_value.__exit__ = mock.Mock()
        write_mock = open_mock.return_value.write

        configdrive.write_configdrive('/lol',
                                      metadata,
                                      files,
                                      prefix='openstack',
                                      version='latest')

        # have to pull out the JSON passed to write and parse it
        # because arbitrary dictionary ordering, etc
        calls = write_mock.mock_calls
        json_data = calls[-1][1][0]
        data = json.loads(json_data)
        self.assertEqual(data, metadata)

        open_calls = [
            mock.call('/lol/openstack/content/0000', 'wb'),
            mock.call().write('contents0'),
            mock.call().__exit__(None, None, None),
            mock.call('/lol/openstack/content/0001', 'wb'),
            mock.call().write('contents1'),
            mock.call().__exit__(None, None, None),
            mock.call('/lol/openstack/latest/meta_data.json', 'wb'),
            # already checked
            mock.call().write(mock.ANY),
            mock.call().__exit__(None, None, None),
        ]
        self.assertEqual(open_mock.mock_calls, open_calls)

        makedirs_calls = [
            mock.call('/lol/openstack/latest'),
            mock.call('/lol/openstack/content')
        ]
        self.assertEqual(makedirs_calls, makedirs_mock.call_args_list)

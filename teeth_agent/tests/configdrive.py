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

import base64
import json
import unittest

from teeth_agent import configdrive


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

    def test_serialize_no_files(self):
        self.writer.add_metadata('admin_pass', 'password')
        self.writer.add_metadata('hostname', 'test')

        metadata = self.writer.metadata
        metadata = base64.b64encode(json.dumps(metadata))
        expected = {'openstack/latest/meta_data.json': metadata}

        data = self.writer.serialize()
        self.assertEqual(data, expected)

    def test_serialize_with_prefix(self):
        self.writer.add_metadata('admin_pass', 'password')
        self.writer.add_metadata('hostname', 'test')

        metadata = self.writer.metadata
        metadata = base64.b64encode(json.dumps(metadata))
        expected = {'teeth/latest/meta_data.json': metadata}

        data = self.writer.serialize(prefix='teeth')
        self.assertEqual(data, expected)

    def test_serialize_with_files(self):
        self.writer.add_metadata('admin_pass', 'password')
        self.writer.add_metadata('hostname', 'test')
        self.writer.add_file('/etc/conf0', 'contents0')
        self.writer.add_file('/etc/conf1', 'contents1')

        metadata = self.writer.metadata
        metadata['files'] = [
            {'content_path': '/content/0000', 'path': '/etc/conf0'},
            {'content_path': '/content/0001', 'path': '/etc/conf1'},
        ]
        metadata = base64.b64encode(json.dumps(metadata))
        expected = {
            'openstack/latest/meta_data.json': metadata,
            'openstack/content/0000': 'contents0',
            'openstack/content/0001': 'contents1'
        }

        data = self.writer.serialize()
        self.assertEqual(len(data.keys()), len(expected.keys()))
        for k, v in expected.items():
            if '.json' in k:
                _actual = json.loads(base64.b64decode(data[k]))
                _expected = json.loads(base64.b64decode(v))
                self.assertEqual(_actual, _expected)
            else:
                self.assertEqual(data[k], v)

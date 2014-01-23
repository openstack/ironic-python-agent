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
import collections
import json
import os


class ConfigDriveWriter(object):
    def __init__(self):
        self.metadata = {}
        self.files = collections.OrderedDict()

    def add_metadata(self, key, value):
        self.metadata[key] = value

    def add_file(self, filepath, contents):
        self.files[filepath] = contents

    def write(self, location, prefix='openstack', version='latest'):
        os.makedirs(os.path.join(location, prefix, version))
        os.makedirs(os.path.join(location, 'content'))

        metadata = {}
        for k, v in self.metadata.iteritems():
            metadata[k] = v

        if self.files:
            metadata['files'] = []
        filenumber = 0
        for filepath, contents in self.files.iteritems():
            content_path = '/content/{:04}'.format(filenumber)
            file_info = {
                'content_path': content_path,
                'path': filepath
            }
            metadata['files'].append(file_info)

            content_path = os.path.join(location, content_path[1:])
            with open(content_path, 'wb') as f:
                f.write(contents)

            filenumber += 1

        json_metadata = json.dumps(metadata)
        metadata_path = '{}/{}/meta_data.json'.format(prefix, version)
        metadata_path = os.path.join(location, metadata_path)
        with open(metadata_path, 'wb') as f:
            f.write(json_metadata)


def write_configdrive(location, metadata, files, prefix='openstack',
                      version='latest'):
    """Generates and writes a valid configdrive to `location`.
    `files` are passed in as a dict {path: base64_contents}.
    """
    writer = ConfigDriveWriter()

    for k, v in metadata.iteritems():
        writer.add_metadata(k, v)

    for path, b64_contents in files.iteritems():
        contents = base64.b64decode(b64_contents)
        writer.add_file(path, contents)

    writer.write(location, prefix=prefix, version=version)

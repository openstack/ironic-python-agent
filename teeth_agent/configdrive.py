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


class ConfigDriveWriter(object):
    def __init__(self):
        self.metadata = {}
        self.files = collections.OrderedDict()

    def add_metadata(self, key, value):
        self.metadata[key] = value

    def add_file(self, filepath, contents):
        self.files[filepath] = contents

    def serialize(self, prefix='openstack'):
        out = {}

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

            metadata_path = prefix + content_path
            out[metadata_path] = contents
            filenumber += 1

        json_metadata = json.dumps(metadata)
        metadata_path = '{}/latest/meta_data.json'.format(prefix)
        out[metadata_path] = base64.b64encode(json_metadata)

        return out

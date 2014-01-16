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

import json
import requests
import time
import uuid


def main():
    headers = {'Content-Type': 'application/json'}

    data = {
        'name': 'prepare_image',
        'params': {
            'image_info': {
                'id': str(uuid.uuid4()),
                'name': 'saucy-patched',
                'urls': [
                    ('http://ad0aa5dd3337e66b1480-' +
                     'a8edc52000ffb652c3d7c76d3a4040f6.r98.cf2.rackcdn.com/' +
                     'saucy-server-cloudimg-amd64-disk1-patched-cloud-init' +
                     '.img')
                ],
                'hashes': {
                    'sha1': '5bf64ef426a9d79e03df1832816529cb969d0944'
                }
            },
            'configdrive': {
                'location': '/tmp/configdrive',
                'data': {
                    'uuid': str(uuid.uuid4()),
                    'admin_pass': 'password',
                    'name': 'teeth',
                    'random_seed': str(uuid.uuid4()).encode('base64'),
                    'hostname': str(uuid.uuid4()),
                    'availability_zone': 'teeth',
                    'launch_index': 0
                }
            },
            'device': '/dev/sda'
        }
    }

    res = requests.post('http://localhost:9999/v1.0/commands',
                        data=json.dumps(data),
                        headers=headers)

    print(res.json())

    job_id = res.json()['id']
    while res.json()['command_status'] == 'RUNNING':
        time.sleep(1)
        url = 'http://localhost:9999/v1.0/commands/{}'.format(job_id)
        res = requests.get(url)
        print(res.json())

if __name__ == '__main__':
    main()

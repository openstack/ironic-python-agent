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

import argparse

from teeth_agent import agent


def run():
    parser = argparse.ArgumentParser(
        description=('An agent that handles decomissioning and provisioning'
                     ' on behalf of teeth-overlord.'))

    parser.add_argument('--api-url',
                        required=True,
                        help='URL of the Teeth agent API')

    parser.add_argument('--listen-host',
                        default='0.0.0.0',
                        type=str,
                        help=('The IP address to listen on.'))

    parser.add_argument('--listen-port',
                        default=9999,
                        type=int,
                        help='The port to listen on')

    parser.add_argument('--ipaddr',
                        required=True,
                        help='The external IP address to advertise to ironic')

    args = parser.parse_args()
    agent.build_agent(args.api_url,
                      args.listen_host,
                      args.listen_port,
                      args.ipaddr).run()

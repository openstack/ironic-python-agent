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

from ironic_python_agent import agent


def run():
    parser = argparse.ArgumentParser(
        description=('An agent that handles decomissioning and provisioning'
                     ' on behalf of Ironic.'))

    parser.add_argument('--api-url',
                        required=True,
                        help='URL of the Ironic API')

    parser.add_argument('--listen-host',
                        default='0.0.0.0',
                        type=str,
                        help='The IP address to listen on.')

    parser.add_argument('--listen-port',
                        default=9999,
                        type=int,
                        help='The port to listen on')
    parser.add_argument('--advertise-host',
                        default='0.0.0.0',
                        type=str,
                        help='The host to tell Ironic to reply and send '
                             'commands to.')
    parser.add_argument('--advertise-port',
                        default=9999,
                        type=int,
                        help='The port to tell Ironic to reply and send '
                             'commands to.')
    parser.add_argument('--lookup-timeout',
                        default=300,
                        type=int,
                        help='The amount of time to retry the initial lookup '
                             'call to Ironic. After the timeout, the agent '
                             'will exit with a non-zero exit code.')
    parser.add_argument('--lookup-interval',
                        default=1,
                        type=int,
                        help='The initial interval for retries on the initial '
                             'lookup call to Ironic. The interval will be '
                             'doubled after each failure until timeout is '
                             'exceeded.')
    args = parser.parse_args()
    agent.build_agent(args.api_url,
                      args.advertise_host,
                      args.advertise_port,
                      args.listen_host,
                      args.listen_port,
                      args.lookup_timeout,
                      args.lookup_interval).run()

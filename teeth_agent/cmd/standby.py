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

from teeth_agent import logging
from teeth_agent import standby


def run():
    parser = argparse.ArgumentParser(
        description='Run the teeth-agent in standby mode')

    parser.add_argument('--api-url',
                        required=True,
                        help='URL of the Teeth agent API')

    parser.add_argument('--listen-port',
                        default=9999,
                        type=int,
                        help='The port to listen on')

    parser.add_argument('--listen-host',
                        type=str,
                        help=('The IP address to listen on. Leave this blank'
                              ' to auto-detect. Even when this is specified,'
                              ' a public-facing address to advertise will be'
                              ' auto-detected by establishing a connection to'
                              ' the agent API.'))

    parser.add_argument('--advertise-port',
                        type=int,
                        help=('The port to advertise. Defaults to listen-port.'
                              ' Useful when running behind a proxy.'))

    args = parser.parse_args()
    logging.configure()
    advertise_port = args.advertise_port or args.listen_port
    standby.StandbyAgent(args.listen_host,
                         args.listen_port,
                         advertise_port,
                         args.api_url).run()

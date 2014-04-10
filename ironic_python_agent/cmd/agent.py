# Copyright 2013 Rackspace, Inc.
#
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

import argparse

from ironic_python_agent import agent
from ironic_python_agent.openstack.common import log


log.setup('ironic-python-agent')
LOG = log.getLogger(__name__)


def _get_kernel_params():
    try:
        with open('/proc/cmdline') as f:
            cmdline = f.read()
    except Exception as e:
        LOG.exception('Could not read /proc/cmdline: {e}'.format(e=e))
        return {}

    options = cmdline.split()
    params = {}
    for option in options:
        if '=' not in option:
            continue
        k, v = option.split('=', 1)
        params[k] = v

    return params


def run():
    kparams = _get_kernel_params()

    parser = argparse.ArgumentParser(
        description=('An agent that handles decomissioning and provisioning'
                     ' on behalf of Ironic.'))

    api_url = kparams.get('ipa-api-url')
    if api_url is None:
        parser.add_argument('--api-url',
                            required=True,
                            help='URL of the Ironic API')

    parser.add_argument('--listen-host',
                        default=kparams.get('ipa-listen-host', '0.0.0.0'),
                        type=str,
                        help='The IP address to listen on.')

    parser.add_argument('--listen-port',
                        default=int(kparams.get('ipa-listen-port', 9999)),
                        type=int,
                        help='The port to listen on')

    parser.add_argument('--advertise-host',
                        default=kparams.get('ipa-advertise-host', '0.0.0.0'),
                        type=str,
                        help='The host to tell Ironic to reply and send '
                             'commands to.')

    parser.add_argument('--advertise-port',
                        default=int(kparams.get('ipa-advertise-port', 9999)),
                        type=int,
                        help='The port to tell Ironic to reply and send '
                             'commands to.')

    parser.add_argument('--lookup-timeout',
                        default=int(kparams.get('ipa-lookup-timeout', 300)),
                        type=int,
                        help='The amount of time to retry the initial lookup '
                             'call to Ironic. After the timeout, the agent '
                             'will exit with a non-zero exit code.')

    parser.add_argument('--lookup-interval',
                        default=int(kparams.get('ipa-lookup-timeout', 1)),
                        type=int,
                        help='The initial interval for retries on the initial '
                             'lookup call to Ironic. The interval will be '
                             'doubled after each failure until timeout is '
                             'exceeded.')

    parser.add_argument('--driver-name',
                        default=kparams.get('ipa-driver-name',
                                            'agent_ipmitool'),
                        type=str,
                        help='The Ironic driver in use for this node')

    args = parser.parse_args()

    agent.IronicPythonAgent(api_url or args.api_url,
                            (args.advertise_host, args.advertise_port),
                            (args.listen_host, args.listen_port),
                            args.lookup_timeout,
                            args.lookup_interval,
                            args.driver_name).run()

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

from oslo.config import cfg

from ironic_python_agent import agent
from ironic_python_agent.openstack.common import log

CONF = cfg.CONF


def _get_kernel_params():
    with open('/proc/cmdline') as f:
        cmdline = f.read()

    options = cmdline.split()
    params = {}
    for option in options:
        if '=' not in option:
            continue
        k, v = option.split('=', 1)
        params[k] = v

    return params

KPARAMS = _get_kernel_params()

cli_opts = [
    cfg.StrOpt('api-url',
                  required=('ipa-api-url' not in KPARAMS),
                  default=KPARAMS.get('ipa-api-url'),
                  help='URL of the Ironic API'),

    cfg.StrOpt('listen-host',
                  default=KPARAMS.get('ipa-listen-host', '0.0.0.0'),
                  help='The IP address to listen on.'),

    cfg.IntOpt('listen-port',
               default=int(KPARAMS.get('ipa-listen-port', 9999)),
               help='The port to listen on'),

    cfg.StrOpt('advertise-host',
                  default=KPARAMS.get('ipa-advertise-host', '0.0.0.0'),
                  help='The host to tell Ironic to reply and send '
                       'commands to.'),

    cfg.IntOpt('advertise-port',
               default=int(KPARAMS.get('ipa-advertise-port', 9999)),
               help='The port to tell Ironic to reply and send '
                    'commands to.'),

    cfg.IntOpt('lookup-timeout',
               default=int(KPARAMS.get('ipa-lookup-timeout', 300)),
               help='The amount of time to retry the initial lookup '
                    'call to Ironic. After the timeout, the agent '
                    'will exit with a non-zero exit code.'),

    cfg.IntOpt('lookup-interval',
               default=int(KPARAMS.get('ipa-lookup-timeout', 1)),
               help='The initial interval for retries on the initial '
                    'lookup call to Ironic. The interval will be '
                    'doubled after each failure until timeout is '
                    'exceeded.'),

    cfg.StrOpt('driver-name',
                  default=KPARAMS.get('ipa-driver-name', 'agent_ipmitool'),
                  help='The Ironic driver in use for this node')
]

CONF.register_cli_opts(cli_opts)


def run():
    CONF()
    log.setup('ironic-python-agent')

    agent.IronicPythonAgent(CONF.api_url,
                            (CONF.advertise_host, CONF.advertise_port),
                            (CONF.listen_host, CONF.listen_port),
                            CONF.lookup_timeout,
                            CONF.lookup_interval,
                            CONF.driver_name).run()

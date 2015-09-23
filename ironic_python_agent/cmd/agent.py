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

import sys

from oslo_config import cfg
from oslo_log import log

from ironic_python_agent import agent
from ironic_python_agent import inspector
from ironic_python_agent import utils

CONF = cfg.CONF


APARAMS = utils.get_agent_params()

cli_opts = [
    cfg.StrOpt('api_url',
                  default=APARAMS.get('ipa-api-url', 'http://127.0.0.1:6385'),
                  deprecated_name='api-url',
                  help='URL of the Ironic API'),

    cfg.StrOpt('listen_host',
                  default=APARAMS.get('ipa-listen-host', '0.0.0.0'),
                  deprecated_name='listen-host',
                  help='The IP address to listen on.'),

    cfg.IntOpt('listen_port',
               default=int(APARAMS.get('ipa-listen-port', 9999)),
               deprecated_name='listen-port',
               help='The port to listen on'),

    cfg.StrOpt('advertise_host',
                  default=APARAMS.get('ipa-advertise-host', None),
                  deprecated_name='advertise_host',
                  help='The host to tell Ironic to reply and send '
                       'commands to.'),

    cfg.IntOpt('advertise_port',
               default=int(APARAMS.get('ipa-advertise-port', 9999)),
               deprecated_name='advertise-port',
               help='The port to tell Ironic to reply and send '
                    'commands to.'),

    cfg.IntOpt('ip_lookup_attempts',
               default=int(APARAMS.get('ipa-ip-lookup-attempts', 3)),
               deprecated_name='ip-lookup-attempts',
               help='The number of times to try and automatically'
                    'determine the agent IPv4 address.'),

    cfg.IntOpt('ip_lookup_sleep',
               default=int(APARAMS.get('ipa-ip-lookup-timeout', 10)),
               deprecated_name='ip-lookup-sleep',
               help='The amaount of time to sleep between attempts'
                    'to determine IP address.'),

    cfg.StrOpt('network_interface',
               default=APARAMS.get('ipa-network-interface', None),
               deprecated_name='network-interface',
               help='The interface to use when looking for an IP'
               'address.'),

    cfg.IntOpt('lookup_timeout',
               default=int(APARAMS.get('ipa-lookup-timeout', 300)),
               deprecated_name='lookup-timeout',
               help='The amount of time to retry the initial lookup '
                    'call to Ironic. After the timeout, the agent '
                    'will exit with a non-zero exit code.'),

    cfg.IntOpt('lookup_interval',
               default=int(APARAMS.get('ipa-lookup-timeout', 1)),
               deprecated_name='lookup-interval',
               help='The initial interval for retries on the initial '
                    'lookup call to Ironic. The interval will be '
                    'doubled after each failure until timeout is '
                    'exceeded.'),

    cfg.StrOpt('driver_name',
                  default=APARAMS.get('ipa-driver-name', 'agent_ipmitool'),
                  deprecated_name='driver-name',
                  help='The Ironic driver in use for this node'),

    cfg.FloatOpt('lldp_timeout',
                 default=APARAMS.get('lldp-timeout', 30.0),
                 help='The amount of seconds to wait for LLDP packets.'),

    cfg.BoolOpt('standalone',
                default=APARAMS.get('ipa-standalone', False),
                help='Note: for debugging only. Start the Agent but suppress '
                     'any calls to Ironic API.'),

    cfg.StrOpt('inspection_callback_url',
               default=APARAMS.get('ipa-inspection-callback-url'),
               help='Endpoint of ironic-inspector. If set, hardware inventory '
                    'will be collected and sent to ironic-inspector '
                    'on start up.'),

    cfg.StrOpt('inspection_collectors',
               default=APARAMS.get('ipa-inspection-collectors',
                                   inspector.DEFAULT_COLLECTOR),
               help='Comma-separated list of plugins providing additional '
                    'hardware data for inspection, empty value gives '
                    'a minimum required set of plugins.'),
]

CONF.register_cli_opts(cli_opts)


def run():
    """Entrypoint for IronicPythonAgent."""
    log.register_options(CONF)
    CONF(args=sys.argv[1:])
    log.setup(CONF, 'ironic-python-agent')
    agent.IronicPythonAgent(CONF.api_url,
                            (CONF.advertise_host, CONF.advertise_port),
                            (CONF.listen_host, CONF.listen_port),
                            CONF.ip_lookup_attempts,
                            CONF.ip_lookup_sleep,
                            CONF.network_interface,
                            CONF.lookup_timeout,
                            CONF.lookup_interval,
                            CONF.driver_name,
                            CONF.standalone).run()

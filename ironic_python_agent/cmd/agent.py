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
from oslo_utils import strutils

from ironic_python_agent import agent
from ironic_python_agent import config

CONF = cfg.CONF


def run():
    """Entrypoint for IronicPythonAgent."""
    log.register_options(CONF)
    CONF(args=sys.argv[1:])
    # Debug option comes from oslo.log, allow overriding it via kernel cmdline
    ipa_debug = config.APARAMS.get('ipa-debug')
    if ipa_debug is not None:
        ipa_debug = strutils.bool_from_string(ipa_debug)
        CONF.set_override('debug', ipa_debug)
    log.setup(CONF, 'ironic-python-agent')
    agent.IronicPythonAgent(CONF.api_url,
                            agent.Host(hostname=CONF.advertise_host,
                                       port=CONF.advertise_port),
                            agent.Host(hostname=CONF.listen_host,
                                       port=CONF.listen_port),
                            CONF.ip_lookup_attempts,
                            CONF.ip_lookup_sleep,
                            CONF.network_interface,
                            CONF.lookup_timeout,
                            CONF.lookup_interval,
                            CONF.standalone,
                            CONF.hardware_initialization_delay).run()

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
from ironic_python_agent import utils

CONF = cfg.CONF


def run():
    """Entrypoint for IronicPythonAgent."""
    # NOTE(dtantsur): this must happen very early of the files from
    # /etc/ironic-python-agent.d won't be loaded
    utils.copy_config_from_vmedia()

    log.register_options(CONF)
    CONF(args=sys.argv[1:])
    # Debug option comes from oslo.log, allow overriding it via kernel cmdline
    ipa_debug = config.APARAMS.get('ipa-debug')
    if ipa_debug is not None:
        ipa_debug = strutils.bool_from_string(ipa_debug)
        CONF.set_override('debug', ipa_debug)
    log.setup(CONF, 'ironic-python-agent')

    logger = log.getLogger(__name__)
    logger.debug("Configuration:")
    CONF.log_opt_values(logger, log.DEBUG)
    utils.log_early_log_to_logger()
    agent.IronicPythonAgent.from_config(CONF).run()

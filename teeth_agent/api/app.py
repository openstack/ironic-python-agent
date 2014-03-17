"""
Copyright 2014 Rackspace, Inc.

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

import pecan
from pecan import hooks

from teeth_agent.api import config


class AgentHook(hooks.PecanHook):
    def __init__(self, agent, *args, **kwargs):
        super(AgentHook, self).__init__(*args, **kwargs)
        self.agent = agent

    def before(self, state):
        state.request.agent = self.agent


def get_pecan_config():
    # Set up the pecan configuration
    filename = config.__file__.replace('.pyc', '.py')
    return pecan.configuration.conf_from_file(filename)


def setup_app(agent, pecan_config=None, extra_hooks=None):
    app_hooks = [AgentHook(agent)]

    if not pecan_config:
        pecan_config = get_pecan_config()

    pecan.configuration.set_config(dict(pecan_config), overwrite=True)

    app = pecan.make_app(
        pecan_config.app.root,
        static_root=pecan_config.app.static_root,
        debug=pecan_config.app.debug,
        force_canonical=getattr(pecan_config.app, 'force_canonical', True),
        hooks=app_hooks,
    )

    return app


class VersionSelectorApplication(object):
    def __init__(self, agent):
        pc = get_pecan_config()
        self.v1 = setup_app(agent, pecan_config=pc)

    def __call__(self, environ, start_response):
        return self.v1(environ, start_response)

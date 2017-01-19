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

from ironic_python_agent import netutils

# Server Specific Configurations
# See https://pecan.readthedocs.org/en/latest/configuration.html#server-configuration # noqa
server = {
    'port': '9999',
    'host': netutils.get_wildcard_address()
}

# Pecan Application Configurations
# See https://pecan.readthedocs.org/en/latest/configuration.html#application-configuration # noqa
app = {
    'root': 'ironic_python_agent.api.controllers.root.RootController',
    'modules': ['ironic_python_agent.api'],
    'static_root': '%(confdir)s/public',
    'debug': False,
    'enable_acl': True,
    'acl_public_routes': ['/', '/v1'],
}

# WSME Configurations
# See https://wsme.readthedocs.org/en/latest/integrate.html#configuration
wsme = {
    'debug': False,
}

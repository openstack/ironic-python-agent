# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import crypt

from oslo_log import log

from ironic_python_agent.extensions import base

LOG = log.getLogger()

PASSWORD_FILE = '/etc/ipa-rescue-config/ipa-rescue-password'


class RescueExtension(base.BaseAgentExtension):

    def write_rescue_password(self, rescue_password="", hashed=False):
        """Write rescue password to a file for use after IPA exits.

        :param rescue_password: Rescue password.
        :param hashed: Boolean default False indicating if the password
                       being provided is hashed or not. This will be changed
                       in a future version of ironic.
        """
        # DEPRECATED(TheJulia): In a future version of the ramdisk, we need
        # change the default such that a password is the default and that
        # if it is not, then the operation fails. Providing a default and
        # an override now that matches the present state allows us to
        # maintain our n-1, n, and n+1 theoretical support. Change
        # in the V or W cycles.
        LOG.debug('Writing hashed rescue password to %s', PASSWORD_FILE)
        password = str(rescue_password)
        hashed_password = None
        if hashed:
            hashed_password = password
        else:
            hashed_password = crypt.crypt(rescue_password)
        try:
            with open(PASSWORD_FILE, 'w') as f:
                f.write(hashed_password)
        except IOError as e:
            msg = ("Rescue Operation failed when writing the hashed rescue "
                   "password to the password file. Error %s") % e
            LOG.exception(msg)
            raise IOError(msg)

    @base.sync_command('finalize_rescue')
    def finalize_rescue(self, rescue_password="", hashed=False):
        """Sets the rescue password for the rescue user."""
        self.write_rescue_password(rescue_password, hashed)
        # IPA will terminate after the result of finalize_rescue is returned to
        # ironic to avoid exposing the IPA API to a tenant or public network
        self.agent.serve_api = False
        return

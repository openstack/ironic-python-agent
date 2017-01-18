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
import random
import string

from oslo_log import log

from ironic_python_agent.extensions import base

LOG = log.getLogger()

PASSWORD_FILE = '/etc/ipa-rescue-config/ipa-rescue-password'


class RescueExtension(base.BaseAgentExtension):

    def make_salt(self):
        """Generate a random salt for hashing the rescue password.

        Salt should be a two-character string from the set [a-zA-Z0-9].

        :returns: a valid salt for use with crypt.crypt
        """
        allowed_chars = string.ascii_letters + string.digits
        return random.choice(allowed_chars) + random.choice(allowed_chars)

    def write_rescue_password(self, rescue_password=""):
        """Write rescue password to a file for use after IPA exits.

        :param rescue_password: Rescue password.
        """
        LOG.debug('Writing hashed rescue password to %s', PASSWORD_FILE)
        salt = self.make_salt()
        hashed_password = crypt.crypt(rescue_password, salt)
        try:
            with open(PASSWORD_FILE, 'w') as f:
                f.write(hashed_password)
        except IOError as e:
            msg = ("Rescue Operation failed when writing the hashed rescue "
                   "password to the password file. Error %s") % e
            LOG.exception(msg)
            raise IOError(msg)

    @base.sync_command('finalize_rescue')
    def finalize_rescue(self, rescue_password=""):
        """Sets the rescue password for the rescue user."""
        self.write_rescue_password(rescue_password)
        # IPA will terminate after the result of finalize_rescue is returned to
        # ironic to avoid exposing the IPA API to a tenant or public network
        self.agent.serve_api = False
        return

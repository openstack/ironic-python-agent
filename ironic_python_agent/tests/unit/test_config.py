# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

from ironic_python_agent import config
# Imported for its side effect of registering the [mdns] option group.
from ironic_python_agent import mdns  # noqa: F401
from ironic_python_agent.tests.unit.base import IronicAgentTest

CONF = cfg.CONF


class TestOverride(IronicAgentTest):
    def test_empty(self):
        CONF.set_override('disk_wait_attempts', 0)
        config.override({})
        self.assertEqual(0, CONF.disk_wait_attempts)

    def test_unknown_prefix_skipped(self):
        config.override({'not_ipa_prefixed': '42'})
        # No exception, and nothing matching this bogus key exists to check.

    def test_default_allowlist(self):
        self.assertEqual(['inspection_callback_url', 'ntp_server'],
                         CONF.mdns.allowed_overrides)

    def test_default_allowlist_allows_ntp_server(self):
        config.override({'ipa_ntp_server': 'pool.ntp.org'})
        self.assertEqual('pool.ntp.org', CONF.ntp_server)

    def test_default_allowlist_blocks_unlisted_option(self):
        CONF.set_override('insecure', False)

        config.override({'ipa_insecure': 'True'})

        self.assertFalse(CONF.insecure)

    def test_no_allowlist_allows_anything_recognized(self):
        CONF.set_override('disk_wait_attempts', 0)
        CONF.set_override('allowed_overrides', None,
                          group='mdns')

        config.override({'ipa_disk_wait_attempts': '42'})

        self.assertEqual(42, CONF.disk_wait_attempts)

    def test_allowlist_allows_listed_option(self):
        CONF.set_override('disk_wait_attempts', 0)
        CONF.set_override('allowed_overrides', ['disk_wait_attempts'],
                          group='mdns')

        config.override({'ipa_disk_wait_attempts': '42'})

        self.assertEqual(42, CONF.disk_wait_attempts)

    def test_allowlist_blocks_unlisted_option(self):
        CONF.set_override('insecure', False)
        CONF.set_override('allowed_overrides', ['disk_wait_attempts'],
                          group='mdns')

        config.override({'ipa_insecure': 'True'})

        self.assertFalse(CONF.insecure)

    def test_allowlist_cannot_be_changed_via_mdns(self):
        # Options that live in the [mdns] group (like use_mdns and
        # allowed_overrides itself) can never be set via mDNS:
        # override() only calls CONF.set_override() without a
        # group, which only ever touches DEFAULT-group options.
        CONF.set_override('allowed_overrides', None,
                          group='mdns')

        config.override({'ipa_allowed_overrides': "['insecure']",
                         'ipa_use_mdns': 'True'})

        self.assertIsNone(CONF.mdns.allowed_overrides)
        self.assertFalse(CONF.mdns.use_mdns)

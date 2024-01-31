# Copyright 2020 Red Hat, Inc.
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

import datetime
import ipaddress
import os
import tempfile
from unittest import mock

from cryptography.hazmat import backends
from cryptography import x509

from ironic_python_agent.tests.unit import base as ironic_agent_base
from ironic_python_agent import tls_utils


class GenerateTestCase(ironic_agent_base.IronicAgentTest):

    def setUp(self):
        super().setUp()
        tempdir = tempfile.mkdtemp()
        self.crt_file = os.path.join(tempdir, 'localhost.crt')
        self.key_file = os.path.join(tempdir, 'localhost.key')

    def test__generate(self):
        result = tls_utils._generate_tls_certificate(self.crt_file,
                                                     self.key_file,
                                                     'localhost', '127.0.0.1')
        now = datetime.datetime.now(
            tz=datetime.timezone.utc).replace(tzinfo=None)
        self.assertTrue(result.startswith("-----BEGIN CERTIFICATE-----\n"),
                        result)
        self.assertTrue(result.endswith("\n-----END CERTIFICATE-----\n"),
                        result)
        self.assertTrue(os.path.exists(self.key_file))
        with open(self.crt_file, 'rt') as fp:
            self.assertEqual(result, fp.read())

        cert = x509.load_pem_x509_certificate(result.encode(),
                                              backends.default_backend())
        self.assertEqual([(x509.NameOID.COMMON_NAME, 'localhost')],
                         [(item.oid, item.value) for item in cert.subject])
        # Sanity check for validity range
        # FIXME(dtantsur): use timezone-aware properties and drop the replace()
        # call above when we're ready to bump to cryptography 42.0.
        self.assertLess(cert.not_valid_before,
                        now - datetime.timedelta(seconds=1800))
        self.assertGreater(cert.not_valid_after,
                           now + datetime.timedelta(seconds=1800))
        subject_alt_name = cert.extensions.get_extension_for_oid(
            x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        self.assertTrue(subject_alt_name.critical)
        self.assertEqual(
            [ipaddress.IPv4Address('127.0.0.1')],
            subject_alt_name.value.get_values_for_type(x509.IPAddress))
        self.assertEqual(
            [], subject_alt_name.value.get_values_for_type(x509.DNSName))

    @mock.patch('ironic_python_agent.netutils.get_hostname', autospec=True)
    @mock.patch('os.makedirs', autospec=True)
    @mock.patch.object(tls_utils, '_generate_tls_certificate', autospec=True)
    def test_generate(self, mock_generate, mock_makedirs, mock_hostname):
        result = tls_utils.generate_tls_certificate('127.0.0.1')
        mock_generate.assert_called_once_with(result.path,
                                              result.private_key_path,
                                              mock_hostname.return_value,
                                              '127.0.0.1')

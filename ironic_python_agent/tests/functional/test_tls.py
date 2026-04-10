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

import multiprocessing
import os
import ssl
import tempfile
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslotest import base as test_base
import requests

from ironic_python_agent import agent
from ironic_python_agent import config  # noqa
from ironic_python_agent import netutils
from ironic_python_agent import tls_utils

CONF = cfg.CONF


def _start_agent_with_tls(api_url, advertise_address, listen_address,
                          ip_lookup_attempts, ip_lookup_sleep,
                          network_interface, lookup_timeout,
                          lookup_interval, standalone, agent_token,
                          tls_cert_file, tls_key_file):
    """Create and run an agent instance with TLS in a subprocess.

    This function is used by multiprocessing to avoid pickling the agent
    object, which contains unpicklable threading locks.
    """
    # Configure TLS settings in the CONF object for the subprocess
    CONF.set_override('listen_tls', True)
    CONF.set_override('tls_cert_file', tls_cert_file)
    CONF.set_override('tls_key_file', tls_key_file)
    CONF.set_override('tls_min_version', '1.2')

    ipa = agent.IronicPythonAgent(
        api_url=api_url,
        advertise_address=advertise_address,
        listen_address=listen_address,
        ip_lookup_attempts=ip_lookup_attempts,
        ip_lookup_sleep=ip_lookup_sleep,
        network_interface=network_interface,
        lookup_timeout=lookup_timeout,
        lookup_interval=lookup_interval,
        standalone=standalone,
        agent_token=agent_token)
    ipa.run()


class TestTLSEnforcement(test_base.BaseTestCase):
    """Tests TLS version enforcement on the IPA API server.

    These tests are structured monolithically as one test with multiple
    steps to avoid parallel execution that would cause port conflicts.
    """

    def setUp(self):
        """Start the agent with TLS and wait for it to start."""
        super(TestTLSEnforcement, self).setUp()
        mpl = multiprocessing.log_to_stderr()
        mpl.setLevel(logging.INFO)
        self.test_port = os.environ.get('TEST_PORT_TLS', '9998')

        # Generate test certificates
        self.tempdir = tempfile.mkdtemp()
        self.cert_file = os.path.join(self.tempdir, 'test.crt')
        self.key_file = os.path.join(self.tempdir, 'test.key')

        # Generate a self-signed certificate for 127.0.0.1
        tls_utils._generate_tls_certificate(
            self.cert_file,
            self.key_file,
            'localhost',
            '127.0.0.1'
        )

        # Start agent with TLS enabled
        self.process = multiprocessing.Process(
            target=_start_agent_with_tls,
            args=('http://127.0.0.1:6835',
                  agent.Host('localhost', 9999),
                  agent.Host(netutils.get_wildcard_address(),
                             int(self.test_port)),
                  3,
                  10,
                  None,
                  300,
                  1,
                  True,
                  '678123',
                  self.cert_file,
                  self.key_file))
        self.process.start()
        self.addCleanup(self.process.terminate)

        # Wait for process to start
        sleep_time = 0.1
        tries = 0
        max_tries = int(os.environ.get('IPA_WAIT_TRIES', '150'))
        while tries < max_tries:
            try:
                # Try to connect with TLS 1.2 to verify server is up
                self._request_tls('get', 'commands',
                                  min_tls_version=ssl.TLSVersion.TLSv1_2)
                return
            except (requests.ConnectionError, ssl.SSLError,
                    requests.exceptions.RequestException):
                time.sleep(sleep_time)
                tries += 1

        raise IOError('Agent did not start after %s seconds.'
                      % (max_tries * sleep_time))

    def _request_tls(self, method, path, min_tls_version,
                     max_tls_version=None, expect_error=None,
                     expect_json=True, **kwargs):
        """Send a request with specific TLS version constraints.

        :param method: type of request to send as a string
        :param path: desired API endpoint to request
        :param min_tls_version: minimum TLS version (ssl.TLSVersion enum)
        :param max_tls_version: maximum TLS version (ssl.TLSVersion enum)
        :param expect_error: error code to expect, if an error is expected
        :param expect_json: whether to expect a JSON response
        :param kwargs: keyword args to pass to the request method
        :raises: HTTPError if an error is returned that was not expected
        :raises: SSLError if TLS handshake fails
        :returns: the response object or JSON dict
        """
        # Create custom SSL context with specific TLS version
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = min_tls_version
        if max_tls_version:
            ctx.maximum_version = max_tls_version

        # Disable certificate verification for test certificates
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Create a custom adapter that uses our SSL context
        class SSLContextAdapter(requests.adapters.HTTPAdapter):
            def __init__(self, ssl_context, **kwargs):
                self.ssl_context = ssl_context
                super().__init__(**kwargs)

            def init_poolmanager(self, *args, **pool_kwargs):
                pool_kwargs['ssl_context'] = self.ssl_context
                return super().init_poolmanager(*args, **pool_kwargs)

        adapter = SSLContextAdapter(ctx)
        session = requests.Session()
        session.mount('https://', adapter)

        # Disable cert verification at the requests level as well
        res = session.request(
            method,
            'https://localhost:%s/v1/%s' % (self.test_port, path),
            verify=False,
            **kwargs
        )

        if expect_error is not None:
            self.assertEqual(expect_error, res.status_code)
        else:
            res.raise_for_status()

        if expect_json:
            return res.json()
        else:
            return res

    def step_1_test_tls_1_2_allowed(self):
        """Verify that TLS 1.2 connections are allowed by the server."""
        response = self._request_tls('get', 'commands',
                                     min_tls_version=ssl.TLSVersion
                                     .TLSv1_2)
        self.assertEqual({'commands': []}, response)

    def step_2_test_tls_1_3_allowed(self):
        """Verify that TLS 1.3 connections are allowed by the server."""
        # This should succeed (if the system supports TLS 1.3)
        try:
            response = self._request_tls('get', 'commands',
                                         min_tls_version=ssl.TLSVersion
                                         .TLSv1_3)
            self.assertEqual({'commands': []}, response)
        except ssl.SSLError as e:
            # If TLS 1.3 is not available on this system, skip
            if 'protocol' in str(e).lower():
                self.skipTest('TLS 1.3 not available on this system')
            raise

    def step_3_test_tls_1_1_blocked(self):
        """Verify that TLS 1.1 connections are blocked by the server."""
        # Attempt to connect with TLS 1.1 only
        # This should fail with an SSL error
        with self.assertRaises((ssl.SSLError,
                                requests.exceptions.SSLError)) as context:
            self._request_tls('get', 'commands',
                              min_tls_version=ssl.TLSVersion.TLSv1_1,
                              max_tls_version=ssl.TLSVersion.TLSv1_1)

        # Verify the error is related to protocol version
        error_msg = str(context.exception).lower()
        self.assertTrue(
            'protocol' in error_msg or 'version' in error_msg
            or 'handshake' in error_msg or 'alert' in error_msg
            or 'no protocols available' in error_msg,
            'Expected SSL protocol error, got: %s' % context.exception
        )

    def step_4_test_tls_1_0_blocked(self):
        """Verify that TLS 1.0 connections are blocked by the server."""
        # Attempt to connect with TLS 1.0 only
        # This should fail with an SSL error
        with self.assertRaises((ssl.SSLError,
                                requests.exceptions.SSLError)) as context:
            self._request_tls('get', 'commands',
                              min_tls_version=ssl.TLSVersion.TLSv1,
                              max_tls_version=ssl.TLSVersion.TLSv1)

        # Verify the error is related to protocol version
        error_msg = str(context.exception).lower()
        self.assertTrue(
            'protocol' in error_msg or 'version' in error_msg
            or 'handshake' in error_msg or 'alert' in error_msg
            or 'no protocols available' in error_msg,
            'Expected SSL protocol error, got: %s' % context.exception
        )

    def tls_enforcement_steps(self):
        """Returns generator with test steps sorted by step number."""
        steps_unsorted = [step for step in dir(self)
                          if step.startswith('step_')]
        steps = sorted(
            steps_unsorted, key=lambda s: int(s.split('_', 2)[1]))
        for name in steps:
            yield getattr(self, name)

    def test_tls_version_enforcement(self):
        """Test TLS version enforcement in sequential steps."""
        for step in self.tls_enforcement_steps():
            step()

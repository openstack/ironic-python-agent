# Copyright 2015 Rackspace, Inc.
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

import multiprocessing
import os
import time

from oslo_log import log as logging
from oslotest import base as test_base
import requests

from ironic_python_agent import agent
# NOTE(lucasagomes): This import is needed so we can register the
# configuration options prior to IPA prior to starting the service
from ironic_python_agent import config  # noqa
from ironic_python_agent import netutils


def _start_agent(api_url, advertise_address, listen_address,
                 ip_lookup_attempts, ip_lookup_sleep, network_interface,
                 lookup_timeout, lookup_interval, standalone, agent_token):
    """Create and run an agent instance in a subprocess.

    This function is used by multiprocessing to avoid pickling the agent
    object, which contains unpicklable threading locks.
    """
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


class FunctionalBase(test_base.BaseTestCase):

    def setUp(self):
        """Start the agent and wait for it to start"""
        super(FunctionalBase, self).setUp()
        mpl = multiprocessing.log_to_stderr()
        mpl.setLevel(logging.INFO)
        self.test_port = os.environ.get('TEST_PORT', '9999')
        # Build a basic standalone agent using the config option defaults.
        # 127.0.0.1:6835 is the fake Ironic client.

        self.process = multiprocessing.Process(
            target=_start_agent,
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
                  '678123'))
        self.process.start()
        self.addCleanup(self.process.terminate)

        # Wait for process to start, otherwise we have a race for tests
        sleep_time = 0.1
        tries = 0
        max_tries = int(os.environ.get('IPA_WAIT_TRIES', '100'))
        while tries < max_tries:
            try:
                return self.request('get', 'commands')
            except requests.ConnectionError:
                time.sleep(sleep_time)
                tries += 1

        raise IOError('Agent did not start after %s seconds.'
                      % (max_tries * sleep_time))

    def request(self, method, path, expect_error=None, expect_json=True,
                **kwargs):
        """Send a request to the agent and verifies response.

        :param method: type of request to send as a string
        :param path: desired API endpoint to request, for example 'commands'
        :param expect_error: error code to expect, if an error is expected
        :param expect_json: whether to expect a JSON response. if True, convert
                            it to a dict before returning, otherwise return the
                            Response object
        :param kwargs: keyword args to pass to the request method
        :raises: HTTPError if an error is returned that was not expected
        :raises: AssertionError if a received HTTP status code does not match
                 expect_error
        :returns: the response object
        """
        res = requests.request(method, 'http://localhost:%s/v1/%s' %
                               (self.test_port, path), **kwargs)
        if expect_error is not None:
            self.assertEqual(expect_error, res.status_code)
        else:
            res.raise_for_status()
        if expect_json:
            return res.json()
        else:
            return res

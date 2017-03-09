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

from ironic_python_agent.tests.functional import base


class TestCommands(base.FunctionalBase):

    """Tests the commands API.

    These tests are structured monolithically as one test with multiple steps
    to preserve ordering and ensure IPA state remains consistent across
    different test runs.
    """

    node = {'uuid': '1', 'properties': {}}

    def step_1_get_empty_commands(self):
        response = self.request('get', 'commands')
        self.assertEqual({'commands': []}, response)

    def step_2_run_command(self):
        # NOTE(mariojv): get_clean_steps always returns the default
        # HardwareManager clean steps if there's not a more specific HWM. So,
        # this command succeeds even with an empty node and port. This test's
        # success is required for steps 3 and 4 to succeed.
        command = {'name': 'clean.get_clean_steps',
                   'params': {'node': self.node, 'ports': {}}}
        response = self.request('post', 'commands', json=command,
                                headers={'Content-Type': 'application/json'})
        self.assertIsNone(response['command_error'])

    def step_3_get_commands(self):
        # This test relies on step 2 to succeed since step 2 runs the command
        # we're checking for
        response = self.request('get', 'commands')
        self.assertEqual(1, len(response['commands']))
        self.assertEqual(
            'get_clean_steps', response['commands'][0]['command_name'])

    def step_4_get_command_by_id(self):
        # First, we have to query the commands API to retrieve the ID. Make
        # sure this API call succeeds again, just in case it fails for some
        # reason after the last test. This test relies on step 2 to succeed
        # since step 2 runs the command we're checking for.
        response = self.request('get', 'commands')
        command_id = response['commands'][0]['id']

        command_from_id = self.request(
            'get', 'commands/%s' % command_id)
        self.assertEqual('get_clean_steps', command_from_id['command_name'])

    def step_5_run_non_existent_command(self):
        fake_command = {'name': 'bad_extension.fake_command', 'params': {}}
        self.request('post', 'commands', expect_error=404, json=fake_command)

    def positive_get_post_command_steps(self):
        """Returns generator with test steps sorted by step number."""
        steps_unsorted = [step for step in dir(self)
                          if step.startswith('step_')]
        # The lambda retrieves the step number from the function name and casts
        # it to an integer. This is necessary, otherwise a lexicographic sort
        # would return ['step_1', 'step_12', 'step_3'] after sorting instead of
        # ['step_1', 'step_3', 'step_12'].
        steps = sorted(steps_unsorted, key=lambda s: int(s.split('_', 2)[1]))
        for name in steps:
            yield getattr(self, name)

    def test_positive_get_post_commands(self):
        for step in self.positive_get_post_command_steps():
            step()

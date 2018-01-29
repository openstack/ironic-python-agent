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

import string

import mock
from oslotest import base as test_base

from ironic_python_agent.extensions import rescue
from ironic_python_agent.tests.unit.extensions.test_base import FakeAgent


class TestRescueExtension(test_base.BaseTestCase):

    def setUp(self):
        super(TestRescueExtension, self).setUp()
        self.agent_extension = rescue.RescueExtension()
        self.agent_extension.agent = FakeAgent()

    def test_make_salt(self):
        salt = self.agent_extension.make_salt()
        self.assertEqual(2, len(salt))
        for char in salt:
            self.assertIn(char, string.ascii_letters + string.digits)

    @mock.patch('ironic_python_agent.extensions.rescue.crypt.crypt',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.rescue.RescueExtension.'
                'make_salt', autospec=True)
    def test_write_rescue_password(self, mock_salt, mock_crypt):
        mock_salt.return_value = '12'
        mock_crypt.return_value = '12deadbeef'
        mock_open = mock.mock_open()
        with mock.patch('ironic_python_agent.extensions.rescue.open',
                        mock_open):
            self.agent_extension.write_rescue_password('password')

        mock_crypt.assert_called_once_with('password', '12')
        mock_open.assert_called_once_with(
            '/etc/ipa-rescue-config/ipa-rescue-password', 'w')
        file_handle = mock_open()
        file_handle.write.assert_called_once_with('12deadbeef')

    @mock.patch('ironic_python_agent.extensions.rescue.crypt.crypt',
                autospec=True)
    @mock.patch('ironic_python_agent.extensions.rescue.RescueExtension.'
                'make_salt', autospec=True)
    def test_write_rescue_password_ioerror(self, mock_salt, mock_crypt):
        mock_salt.return_value = '12'
        mock_crypt.return_value = '12deadbeef'
        mock_open = mock.mock_open()
        with mock.patch('ironic_python_agent.extensions.rescue.open',
                        mock_open):
            mock_open.side_effect = IOError
            # Make sure IOError gets reraised for caller to handle
            self.assertRaises(
                IOError, self.agent_extension.write_rescue_password,
                'password')

    @mock.patch('ironic_python_agent.extensions.rescue.RescueExtension.'
                'write_rescue_password', autospec=True)
    def test_finalize_rescue(self, mock_write_rescue_password):
        self.agent_extension.agent.serve_api = True
        self.agent_extension.finalize_rescue(rescue_password='password')
        mock_write_rescue_password.assert_called_once_with(
            mock.ANY,
            rescue_password='password')
        self.assertFalse(self.agent_extension.agent.serve_api)

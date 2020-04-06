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

from unittest import mock

from oslotest import base as test_base

from ironic_python_agent.extensions import rescue
from ironic_python_agent.tests.unit.extensions.test_base import FakeAgent


class TestRescueExtension(test_base.BaseTestCase):

    def setUp(self):
        super(TestRescueExtension, self).setUp()
        self.agent_extension = rescue.RescueExtension()
        self.agent_extension.agent = FakeAgent()

    @mock.patch('ironic_python_agent.extensions.rescue.crypt.crypt',
                autospec=True)
    def test_write_rescue_password(self, mock_crypt):
        mock_crypt.return_value = '12deadbeef'
        mock_open = mock.mock_open()
        with mock.patch('ironic_python_agent.extensions.rescue.open',
                        mock_open):
            self.agent_extension.write_rescue_password('password')

        mock_crypt.assert_called_once_with('password')
        mock_open.assert_called_once_with(
            '/etc/ipa-rescue-config/ipa-rescue-password', 'w')
        file_handle = mock_open()
        file_handle.write.assert_called_once_with('12deadbeef')

    @mock.patch('ironic_python_agent.extensions.rescue.crypt.crypt',
                autospec=True)
    def test_write_rescue_password_ioerror(self, mock_crypt):
        mock_crypt.return_value = '12deadbeef'
        mock_open = mock.mock_open()
        with mock.patch('ironic_python_agent.extensions.rescue.open',
                        mock_open):
            mock_open.side_effect = IOError
            # Make sure IOError gets reraised for caller to handle
            self.assertRaises(
                IOError, self.agent_extension.write_rescue_password,
                'password')

    @mock.patch('ironic_python_agent.extensions.rescue.crypt.crypt',
                autospec=True)
    def _write_password_hashed_test(self, password, mock_crypt):
        mock_open = mock.mock_open()
        with mock.patch('ironic_python_agent.extensions.rescue.open',
                        mock_open):
            self.agent_extension.write_rescue_password(password,
                                                       hashed=True)
            self.assertFalse(mock_crypt.called)
            mock_open.assert_called_once_with(
                '/etc/ipa-rescue-config/ipa-rescue-password', 'w')
            file_handle = mock_open()
            file_handle.write.assert_called_once_with(password)

    def test_hashed_passwords(self):
        # NOTE(TheJulia): Sort of redundant in that we're not actually
        # verifying content here, but these are semi-realistic values
        # that may be passed in, so best to just keep it regardless.
        passwds = ['$1$1234567890234567890123456789001',
                   '$2a$012345678901234566789012345678901234567890123'
                   '45678901234',
                   '$5$1234567890123456789012345678901234567890123456'
                   '789012',
                   '$6$1234567890123456789012345678901234567890123456'
                   '7890123456789012345678901234567890123456789012345']
        for passwd in passwds:
            self._write_password_hashed_test(passwd)

    @mock.patch('ironic_python_agent.extensions.rescue.RescueExtension.'
                'write_rescue_password', autospec=True)
    def test_finalize_rescue(self, mock_write_rescue_password):
        self.agent_extension.agent.serve_api = True
        self.agent_extension.finalize_rescue(rescue_password='password')
        mock_write_rescue_password.assert_called_once_with(
            mock.ANY,
            rescue_password='password', hashed=False)
        self.assertFalse(self.agent_extension.agent.serve_api)

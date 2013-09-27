"""
Copyright 2013 Rackspace, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""


from twisted.internet import defer
from twisted.internet import main
from twisted.internet.address import IPv4Address
from twisted.python import failure
from twisted.test.proto_helpers import StringTransportWithDisconnection
from twisted.trial import unittest
import simplejson as json
from mock import Mock

from teeth_agent.protocol import RPCError, RPCProtocol, TeethAgentProtocol
from teeth_agent import __version__ as AGENT_VERSION


class FakeTCPTransport(StringTransportWithDisconnection, object):
    _aborting = False
    disconnected = False

    setTcpKeepAlive = Mock(return_value=None)
    setTcpNoDelay = Mock(return_value=None)
    setTcpNoDelay = Mock(return_value=None)

    def connectionLost(self, reason):
        self.protocol.connectionLost(reason)

    def abortConnection(self):
        if self.disconnected or self._aborting:
            return
        self._aborting = True
        self.connectionLost(failure.Failure(main.CONNECTION_DONE))


class RPCProtocolTest(unittest.TestCase):
    """RPC Protocol tests."""

    def setUp(self):
        self.tr = FakeTCPTransport()
        self.proto = RPCProtocol(json.JSONEncoder(), IPv4Address('TCP', '127.0.0.1', 0))
        self.proto.makeConnection(self.tr)
        self.tr.protocol = self.proto

    def test_timeout(self):
        d = defer.Deferred()
        called = []
        orig = self.proto.connectionLost

        def lost(arg):
            orig()
            called.append(True)
            d.callback(True)

        self.proto.connectionLost = lost
        self.proto.timeoutConnection()

        def check(ignore):
            self.assertEqual(called, [True])

        d.addCallback(check)
        return d

    def test_recv_command_no_params(self):
        self.tr.clear()
        self.proto.lineReceived(json.dumps({'id': '1', 'version': 'v1', 'method': 'BOGUS_STUFF'}))
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['fatal_error'], 'protocol violation: missing message params.')

    def test_recv_bogus_command(self):
        self.tr.clear()
        self.proto.lineReceived(
            json.dumps({'id': '1', 'version': 'v1', 'method': 'BOGUS_STUFF', 'params': {'d': '1'}}))
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['fatal_error'], 'protocol violation: unsupported command.')

    def test_recv_valid_json_no_id(self):
        self.tr.clear()
        self.proto.lineReceived(json.dumps({'version': 'v913'}))
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['fatal_error'], 'protocol violation: missing message id.')

    def test_recv_valid_json_no_version(self):
        self.tr.clear()
        self.proto.lineReceived(json.dumps({'version': None, 'id': 'foo'}))
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['fatal_error'], 'protocol violation: missing message version.')

    def test_recv_invalid_data(self):
        self.tr.clear()
        self.proto.lineReceived('')
        self.proto.lineReceived('invalid json!')
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['fatal_error'], 'protocol error: unable to decode message.')

    def test_recv_missing_key_parts(self):
        self.tr.clear()
        self.proto.lineReceived(json.dumps(
            {'id': '1', 'version': 'v1'}))
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['fatal_error'], 'protocol error: malformed message.')

    def test_recv_error_to_unknown_id(self):
        self.tr.clear()
        self.proto.lineReceived(json.dumps(
            {'id': '1', 'version': 'v1', 'error': {'msg': 'something is wrong'}}))
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['fatal_error'], 'protocol violation: unknown message id referenced.')

    def _send_command(self):
        self.tr.clear()
        d = self.proto.send_command('test_command', {'body': 42})
        req = json.loads(self.tr.io.getvalue().strip())
        self.tr.clear()
        return (d, req)

    def test_recv_result(self):
        dout = defer.Deferred()
        d, req = self._send_command()
        self.proto.lineReceived(json.dumps(
            {'id': req['id'], 'version': 'v1', 'result': {'duh': req['params']['body']}}))
        self.assertEqual(len(self.tr.io.getvalue()), 0)

        def check(resp):
            self.assertEqual(resp.result['duh'], 42)
            dout.callback(True)

        d.addCallback(check)

        return dout

    def test_recv_error(self):
        d, req = self._send_command()
        self.proto.lineReceived(json.dumps(
            {'id': req['id'], 'version': 'v1', 'error': {'msg': 'something is wrong'}}))
        self.assertEqual(len(self.tr.io.getvalue()), 0)
        return self.assertFailure(d, RPCError)

    def test_recv_fatal_error(self):
        d = defer.Deferred()
        called = []
        orig = self.proto.connectionLost

        def lost(arg):
            self.failUnless(isinstance(arg, failure.Failure))
            orig()
            called.append(True)
            d.callback(True)

        self.proto.connectionLost = lost

        def check(ignore):
            self.assertEqual(called, [True])

        d.addCallback(check)

        self.tr.clear()
        self.proto.lineReceived(json.dumps({'fatal_error': 'you be broken'}))
        return d


class TeethAgentProtocolTest(unittest.TestCase):
    """Teeth Agent Protocol tests."""

    def setUp(self):
        self.tr = FakeTCPTransport()
        self.proto = TeethAgentProtocol(json.JSONEncoder(), IPv4Address('TCP', '127.0.0.1', 0), None)
        self.proto.makeConnection(self.tr)
        self.tr.protocol = self.proto

    def test_on_connect(self):
        obj = json.loads(self.tr.io.getvalue().strip())
        self.assertEqual(obj['version'], 'v1')
        self.assertEqual(obj['method'], 'handshake')
        self.assertEqual(obj['method'], 'handshake')
        self.assertEqual(obj['params']['id'], 'a:b:c:d')
        self.assertEqual(obj['params']['version'], AGENT_VERSION)

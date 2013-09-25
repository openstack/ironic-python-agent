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

import simplejson as json
import uuid

from twisted.internet import defer
from twisted.protocols import policies
from twisted.protocols.basic import LineReceiver
from teeth_agent import __version__ as AGENT_VERSION
from teeth_agent.events import EventEmitter
from teeth_agent.logging import get_logger
log = get_logger()


DEFAULT_PROTOCOL_VERSION = 'v1'

__all__ = ['RPCMessage', 'RPCCommand', 'RPCProtocol', 'TeethAgentProtocol']


class RPCMessage(object):
    """
    Wraps all RPC messages.
    """
    def __init__(self, protocol, message):
        super(RPCMessage, self).__init__()
        self.protocol = protocol
        self.id = message['id']
        self.version = message['version']


class RPCCommand(RPCMessage):
    """
    Wraps incoming RPC Commands.
    """
    def __init__(self, protocol, message):
        super(RPCCommand, self).__init__(protocol, message)
        self.method = message['method']
        self.params = message['params']


class RPCResponse(RPCMessage):
    """
    Wraps incoming RPC Responses.
    """
    def __init__(self, protocol, message):
        super(RPCResponse, self).__init__(protocol, message)
        self.result = message.get('result', None)


class RPCError(RPCMessage, RuntimeError):
    """
    Wraps incoming RPC Errors Responses.
    """
    def __init__(self, protocol, message):
        super(RPCError, self).__init__(protocol, message)
        self.error = message.get('error', 'unknown error')
        self._raw_message = message


class RPCProtocol(LineReceiver,
                  EventEmitter,
                  policies.TimeoutMixin):
    """
    Twisted Protocol handler for the RPC Protocol of the Teeth
    Agent <-> Endpoint communication.

    The protocol is a simple JSON newline based system.  Client or server
    can request methods with a message id.  The recieving party
    responds to this message id.

    The low level details are in C{RPCProtocol} while the higher level
    functions are in C{TeethAgentProtocol}
    """

    delimiter = '\n'
    MAX_LENGTH = 1024 * 512

    def __init__(self, encoder, address):
        super(RPCProtocol, self).__init__()
        self.encoder = encoder
        self.address = address
        self._pending_command_deferreds = {}
        self._fatal_error = False
        self._log = log.bind(host=address.host, port=address.port)
        self._timeOut = 60

    def timeoutConnection(self):
        """Action called when the connection has hit a timeout."""
        self.transport.abortConnection()

    def connectionMade(self):
        """TCP hard. We made it. Maybe."""
        super(RPCProtocol, self).connectionMade()
        self._log.msg('Connection established.')
        self.transport.setTcpKeepAlive(True)
        self.transport.setTcpNoDelay(True)
        self.emit('connect')

    def sendLine(self, line):
        """Send a line of content to our peer."""
        self.resetTimeout()
        super(RPCProtocol, self).sendLine(line)

    def lineReceived(self, line):
        """Process a line of data."""
        self.resetTimeout()
        line = line.strip()

        if not line:
            return

        self._log.msg('Got Line', line=line)

        try:
            message = json.loads(line)
        except Exception:
            return self.fatal_error('protocol error: unable to decode message.')

        if 'fatal_error' in message:
            # TODO: Log what happened?
            self.transport.abortConnection()
            return

        if not message.get('version', None):
            return self.fatal_error("protocol violation: missing message version.")

        if not message.get('id', None):
            return self.fatal_error("protocol violation: missing message id.")

        if 'method' in message:
            if not message.get('params', None):
                return self.fatal_error("protocol violation: missing message params.")

            msg = RPCCommand(self, message)
            self._handle_command(msg)

        elif 'error' in message:
            msg = RPCError(self, message)
            self._handle_response(msg)

        elif 'result' in message:

            msg = RPCResponse(self, message)
            self._handle_response(msg)
        else:
            return self.fatal_error('protocol error: malformed message.')

    def fatal_error(self, message):
        """Send a fatal error message, and disconnect."""
        self._log.msg('sending a fatal error', message=message)
        if not self._fatal_error:
            self._fatal_error = True
            self.sendLine(self.encoder.encode({
                'fatal_error': message
            }))
            self.transport.abortConnection()

    def send_command(self, method, params, timeout=60):
        """Send a new command."""
        message_id = str(uuid.uuid4())
        d = defer.Deferred()
        # d.setTimeout(timeout)
        # TODO: cleanup _pending_command_deferreds on timeout.
        self._pending_command_deferreds[message_id] = d
        self.sendLine(self.encoder.encode({
            'id': message_id,
            'version': DEFAULT_PROTOCOL_VERSION,
            'method': method,
            'params': params,
        }))
        return d

    def send_response(self, result, responding_to):
        """Send a result response."""
        self.sendLine(self.encoder.encode({
            'id': responding_to.id,
            'version': responding_to.version,
            'result': result,
        }))

    def send_error_response(self, error, responding_to):
        """Send an error response."""
        self.sendLine(self.encoder.encode({
            'id': responding_to.id,
            'version': responding_to.version,
            'error': error,
        }))

    def _handle_response(self, message):
        d = self._pending_command_deferreds.pop(message.id, None)

        if not d:
            return self.fatal_error("protocol violation: unknown message id referenced.")

        if isinstance(message, RPCError):
            d.errback(message)
        else:
            d.callback(message)

    def _handle_command(self, message):
        d = self.emit('command', message)

        if len(d) == 0:
            return self.fatal_error("protocol violation: unsupported command.")

        # TODO: do we need to wait on anything here?
        pass


class TeethAgentProtocol(RPCProtocol):
    """
    Handles higher level logic of the RPC protocol like authentication and handshakes.
    """

    def __init__(self, encoder, address, parent):
        super(TeethAgentProtocol, self).__init__(encoder, address)
        self.encoder = encoder
        self.address = address
        self.parent = parent
        self.once('connect', self._once_connect)

    def _once_connect(self, event):

        def _response(result):
            self._log.msg('Handshake successful', connection_id=result['id'])

        return self.send_command('handshake',
                                 {'id': 'a:b:c:d', 'version': AGENT_VERSION}).addCallback(_response)

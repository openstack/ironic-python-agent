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

import time
import simplejson as json

from twisted.application.service import MultiService
from twisted.application.internet import TCPClient
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet.defer import maybeDeferred
from twisted.internet.defer import DeferredList
from twisted.python.failure import Failure

from teeth_agent.protocol import TeethAgentProtocol
from teeth_agent.logging import get_logger
log = get_logger()


__all__ = ["TeethClientFactory", "TeethClient"]


class TeethClientFactory(ReconnectingClientFactory, object):
    """
    Protocol Factory for the Teeth Client.
    """
    protocol = TeethAgentProtocol
    initialDelay = 1.0
    maxDelay = 120

    def __init__(self, encoder, parent):
        super(TeethClientFactory, self).__init__()
        self._encoder = encoder
        self._parent = parent

    def buildProtocol(self, addr):
        """Create protocol for an address."""
        self.resetDelay()
        proto = self.protocol(self._encoder, addr, self._parent)
        self._parent.add_protocol_instance(proto)
        return proto

    def clientConnectionFailed(self, connector, reason):
        """clientConnectionFailed"""
        log.err('Failed to connect, re-trying', delay=self.delay)
        super(TeethClientFactory, self).clientConnectionFailed(connector, reason)

    def clientConnectionLost(self, connector, reason):
        """clientConnectionLost"""
        log.err('Lost connection, re-connecting', delay=self.delay)
        super(TeethClientFactory, self).clientConnectionLost(connector, reason)


class TeethClient(MultiService, object):
    """
    High level Teeth Client.
    """
    client_factory_cls = TeethClientFactory
    client_encoder_cls = json.JSONEncoder

    def __init__(self, addrs):
        super(TeethClient, self).__init__()
        self.setName('teeth-agent')
        self._client_encoder = self.client_encoder_cls()
        self._client_factory = self.client_factory_cls(self._client_encoder, self)
        self._start_time = time.time()
        self._clients = []
        self._outmsg = []
        self._connectaddrs = addrs
        self._running = False
        self._handlers = {
            'v1': {
                'status': self._handle_status,
            }
        }

    def startService(self):
        """Start the Service."""
        super(TeethClient, self).startService()
        self._running = True
        self.start()

    def stopService(self):
        """Stop the Service."""
        super(TeethClient, self).stopService()
        self._running = False
        dl = []
        for client in self._clients:
            dl.append(client.loseConnectionSoon(timeout=0.05))
        return DeferredList(dl)

    def remove_endpoint(self, host, port):
        """Remove an Agent Endpoint from the active list."""

        def op(client):
            if client.address.host == host and client.address.port == port:
                client.loseConnectionSoon()
                return True
            return False
        self._clients[:] = [client for client in self._clients if not op(client)]

    def add_endpoint(self, host, port):
        """Add an agent endpoint to the """
        self._connectaddrs.append([host, port])
        self.start()

    def add_protocol_instance(self, client):
        """Add a running protocol to the parent."""
        client.on('command', self._on_command)
        self._clients.append(client)

    def start(self):
        """Start the agent, if running."""

        if not self._running:
            return

        for host, port in self._connectaddrs:
            service = TCPClient(host, port, self._client_factory)
            service.setName("teeth-agent[%s:%d]".format(host, port))
            self.addService(service)
        self._connectaddrs = []

    def _on_command(self, topic, message):
        if message.version not in self._handlers:
            message.protocol.fatal_error('unknown message version')
            return

        if message.method not in self._handlers[message.version]:
            message.protocol.fatal_error('unknown message method')
            return

        handler = self._handlers[message.version][message.method]
        d = maybeDeferred(handler, message=message)
        d.addBoth(self._send_response, message)

    def send_response(self, result, message):
        """Send a response to a message."""
        if isinstance(result, Failure):
            # TODO: log, cleanup
            message.protocol.send_error_response('error running command', message)
        else:
            message.protocol.send_response(result, message)

    def _handle_status(self, message):
        running = time.time() - self._start_time
        return {'running': running}

    def _addHandler(self, version, command, func):
        self._handlers[version][command] = func

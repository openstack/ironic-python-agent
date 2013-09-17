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

from twisted.protocols.basic import LineReceiver
from twisted.internet.defer import maybeDeferred
from twisted.internet import defer


DEFAULT_PROTOCOL_VERSION = 'v1'


class TeethAgentProtocol(LineReceiver):
    def __init__(self, encoder):
        self.encoder = encoder
        self.handlers = {}
        self.pending_command_deferreds = {}

    def lineReceived(self, line):
        line = line.strip()
        if not line:
            return

        message = json.loads(line)
        if 'method' in message:
            self.handle_command(message)
        elif 'result' in message:
            self.handle_response(message)

    def send_command(self, command):
        message_id = str(uuid.uuid4())
        d = defer.Deferred()
        self.pending_command_deferreds[message_id] = d
        self.sendLine(self.encoder.encode({
            'id': message_id,
            'version': DEFAULT_PROTOCOL_VERSION,
            'method': command['method'],
            'args': command.get('args', []),
            'kwargs': command.get('kwargs', {}),
        }))
        return d

    def handle_command(self, message):
        message_id = message['id']
        version = message['version']
        args = message.get('args', [])
        kwargs = message.get('kwargs', {})
        d = maybeDeferred(self.handlers[version][message['method']], *args, **kwargs)
        d.addCallback(self.send_response, version, message_id)

    def send_response(self, result, version, message_id):
        self.sendLine(self.encoder.encode({
            'id': message_id,
            'version': version,
            'result': result,
        }))

    def handle_response(self, message):
        d = self.pending_command_deferreds.pop(message['id'])
        error = message.get('error', None)
        if error:
            d.errback(error)
        else:
            d.callback(message.get('result', None))

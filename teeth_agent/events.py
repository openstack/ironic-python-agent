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

from collections import defaultdict
from twisted.internet.defer import maybeDeferred

__all__ = ['EventEmitter', 'EventEmitterUnhandledError']


class EventEmitterUnhandledError(RuntimeError):
    """
    Error caused by no subscribers to an `error` event.
    """
    pass


class EventEmitter(object):
    """

    Extremely simple pubsub style things in-process.

    Styled after the Node.js EventEmitter class

    """
    __slots__ = ['_subs']

    def __init__(self):
        self._subs = defaultdict(list)

    def emit(self, topic, *args):
        """
        Emit an event to a specific topic with a payload.
        """
        ds = []
        if topic == "error":
            if len(self._subs[topic]) == 0:
                raise EventEmitterUnhandledError("No Subscribers to an error event found")
        for s in self._subs[topic]:
            ds.append(maybeDeferred(s, topic, *args))
        return ds

    def on(self, topic, callback):
        """
        Add a handler for a specific topic.
        """
        self.emit("newListener", topic, callback)
        self._subs[topic].append(callback)

    def once(self, topic, callback):
        """
        Execute a specific handler just once.
        """
        def oncecb(*args):
            self.removeListener(topic, oncecb)
            callback(*args)
        self.on(topic, oncecb)

    def removeListener(self, topic, callback):
        """
        Remove a handler from a topic.
        """
        self._subs[topic] = filter(lambda x: x != callback, self._subs[topic])

    def removeAllListeners(self, topic):
        """
        Remove all listeners from a specific topic.
        """
        del self._subs[topic]

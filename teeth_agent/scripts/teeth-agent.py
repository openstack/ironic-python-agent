#!/usr/bin/env python
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

import os
import sys
from os.path import dirname

sys.path.append(dirname(dirname(dirname(os.path.realpath(__file__)))))

from twisted.python import usage
from twisted.internet import reactor
from teeth_agent.logging import configure as configureLogging
from teeth_agent.agent import StandbyAgent


class Options(usage.Options):
    synopsis = """%s [options]
    """ % (
        os.path.basename(sys.argv[0]),)

    optParameters = [["mode", "m", "standbye", "Mode to run Agent in, standbye or decom."]]


def run():
    if len(sys.argv) == 1:
        sys.argv.append("--help")

    config = Options()
    try:
        config.parseOptions()
    except usage.error, ue:
        raise SystemExit("%s: %s" % (sys.argv[0], ue))

    configureLogging()

    if config['mode'] == "standbye":
        agent = StandbyAgent([['localhost', 8081]])
        agent.start()
    else:
        raise SystemExit("Invalid mode")
    reactor.run()

if __name__ == "__main__":
    run()

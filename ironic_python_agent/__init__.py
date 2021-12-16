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

import os

import eventlet

# NOTE(TheJulia): Eventlet, when monkey patching occurs, replaces the base
# dns resolver methods. This can lead to compatibility issues,
# and un-expected exceptions being raised during the process
# of monkey patching. Such as one if there are no resolvers.
os.environ['EVENTLET_NO_GREENDNS'] = "yes"

# NOTE(JayF) Without monkey_patching socket, API requests will hang with TLS
# enabled. Enabling more than just socket for monkey patching causes failures
# in image streaming. In an ideal world, we track down all those errors and
# monkey patch everything as suggested in eventlet documentation.
eventlet.monkey_patch(all=False, socket=True)

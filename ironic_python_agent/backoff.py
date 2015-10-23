# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import random

from oslo_log import log
from oslo_service import loopingcall


LOG = log.getLogger(__name__)


# TODO(JoshNang) move to oslo, i18n
class LoopingCallTimeOut(Exception):
    """Exception for a timed out LoopingCall.

    The LoopingCall will raise this exception when a timeout is provided
    and it is exceeded.
    """
    pass


class BackOffLoopingCall(loopingcall.LoopingCallBase):
    """Run a method in a loop with backoff on error.

    The passed in function should return True (no error, return to
    initial_interval),
    False (error, start backing off), or raise LoopingCallDone(retvalue=None)
    (quit looping, return retvalue if set).

    When there is an error, the call will backoff on each failure. The
    backoff will be equal to double the previous base interval times some
    jitter. If a backoff would put it over the timeout, it halts immediately,
    so the call will never take more than timeout, but may and likely will
    take less time.

    When the function return value is True or False, the interval will be
    multiplied by a random jitter. If min_jitter or max_jitter is None,
    there will be no jitter (jitter=1). If min_jitter is below 0.5, the code
    may not backoff and may increase its retry rate.

    If func constantly returns True, this function will not return.

    To run a func and wait for a call to finish (by raising a LoopingCallDone):

        timer = BackOffLoopingCall(func)
        response = timer.start().wait()

    :param initial_delay: delay before first running of function
    :param starting_interval: initial interval in seconds between calls to
                              function. When an error occurs and then a
                              success, the interval is returned to
                              starting_interval
    :param timeout: time in seconds before a LoopingCallTimeout is raised.
                    The call will never take longer than timeout, but may quit
                    before timeout.
    :param max_interval: The maximum interval between calls during errors
    :param jitter: Used to vary when calls are actually run to avoid group of
                   calls all coming at the exact same time. Uses
                   random.gauss(jitter, 0.1), with jitter as the mean for the
                   distribution. If set below .5, it can cause the calls to
                   come more rapidly after each failure.
    :raises: LoopingCallTimeout if time spent doing error retries would exceed
             timeout.
    """

    _RNG = random.SystemRandom()
    _KIND = 'Dynamic backoff interval looping call'
    _RUN_ONLY_ONE_MESSAGE = ("A dynamic backoff interval looping call can"
                             " only run one function at a time")

    def __init__(self, f=None, *args, **kw):
        super(BackOffLoopingCall, self).__init__(f=f, *args, **kw)
        self._error_time = 0
        self._interval = 1

    def start(self, initial_delay=None, starting_interval=1, timeout=300,
              max_interval=300, jitter=0.75):
        if self._thread is not None:
            raise RuntimeError(self._RUN_ONLY_ONE_MESSAGE)

        # Reset any prior state.
        self._error_time = 0
        self._interval = starting_interval

        def _idle_for(success, _elapsed):
            random_jitter = self._RNG.gauss(jitter, 0.1)
            if success:
                # Reset error state now that it didn't error...
                self._interval = starting_interval
                self._error_time = 0
                return self._interval * random_jitter
            else:
                # Perform backoff
                self._interval = idle = min(
                    self._interval * 2 * random_jitter, max_interval)
                # Don't go over timeout, end early if necessary. If
                # timeout is 0, keep going.
                if timeout > 0 and self._error_time + idle > timeout:
                    raise LoopingCallTimeOut(
                        'Looping call timed out after %.02f seconds'
                        % self._error_time)
                self._error_time += idle
                return idle

        return self._start(_idle_for, initial_delay=initial_delay)

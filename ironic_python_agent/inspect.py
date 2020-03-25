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
import random
import select
import threading

from ironic_lib import exception
from oslo_config import cfg
from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent import inspector

LOG = log.getLogger(__name__)


class IronicInspection(threading.Thread):
    """Class for manual inspection functionality."""

    # If we could wait at most N seconds between heartbeats (or in case of an
    # error) we will instead wait r x N seconds, where r is a random value
    # between these multipliers.
    min_jitter_multiplier = 0.7
    max_jitter_multiplier = 1.2

    # Exponential backoff values used in case of an error. In reality we will
    # only wait a portion of either of these delays based on the jitter
    # multipliers.
    max_delay = 4 * cfg.CONF.introspection_daemon_post_interval
    backoff_factor = 2.7

    def __init__(self):
        super(IronicInspection, self).__init__()
        if bool(cfg.CONF.keyfile) != bool(cfg.CONF.certfile):
            LOG.warning("Only one of 'keyfile' and 'certfile' options is "
                        "defined in config file. Its value will be ignored.")

    def _run(self):
        try:
            daemon_mode = cfg.CONF.introspection_daemon
            interval = cfg.CONF.introspection_daemon_post_interval

            inspector.inspect()
            if not daemon_mode:
                # No reason to continue unless we're in daemon mode.
                return

            self.reader, self.writer = os.pipe()
            p = select.poll()
            p.register(self.reader)
            exception_encountered = False

            try:
                while daemon_mode:
                    interval_multiplier = random.uniform(
                        self.min_jitter_multiplier,
                        self.max_jitter_multiplier)
                    interval = interval * interval_multiplier
                    log_msg = 'sleeping before next inspection, interval: %s'
                    LOG.info(log_msg, interval)

                    if p.poll(interval * 1000):
                        if os.read(self.reader, 1).decode() == 'a':
                            break
                    try:
                        inspector.inspect()
                        if exception_encountered:
                            interval = min(
                                interval,
                                cfg.CONF.introspection_daemon_post_interval)
                            exception_encountered = False
                    except errors.InspectionError as e:
                        # Failures happen, no reason to exit as
                        # the failure could be intermittent.
                        LOG.warning('Error reporting introspection '
                                    'data: %(err)s',
                                    {'err': e})
                        exception_encountered = True
                        interval = min(interval * self.backoff_factor,
                                       self.max_delay)

                    except exception.ServiceLookupFailure as e:
                        # Likely a mDNS lookup failure. We should
                        # keep retrying.
                        LOG.error('Error looking up introspection '
                                  'endpoint: %(err)s',
                                  {'err': e})
                        exception_encountered = True
                        interval = min(interval * self.backoff_factor,
                                       self.max_delay)
                    except Exception as e:
                        # General failure such as requests ConnectionError
                        LOG.error('Error occured attempting to connect to '
                                  'connect to the introspection service. '
                                  'Error: %(err)s',
                                  {'err': e})
                        exception_encountered = True
                        interval = min(interval * self.backoff_factor,
                                       self.max_delay)

            finally:
                os.close(self.reader)
                os.close(self.writer)
                self.reader = None
                self.writer = None
        except errors.InspectionError as e:
            msg = "Inspection failed: %s" % e
            raise errors.InspectionError(msg)

    def run(self):
        """Run Inspection."""
        if not cfg.CONF.inspection_callback_url:
            cfg.CONF.set_override('inspection_callback_url', 'mdns')
        self._run()

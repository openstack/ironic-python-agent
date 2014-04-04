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

import collections

from ironic_python_agent.openstack.common import gettextutils as gtu
from ironic_python_agent.openstack.common import log as logging
from ironic_python_agent.openstack.common import processutils

LOG = logging.getLogger(__name__)


def get_ordereddict(*args, **kwargs):
    """A fix for py26 not having ordereddict."""
    try:
        return collections.OrderedDict(*args, **kwargs)
    except AttributeError:
        import ordereddict
        return ordereddict.OrderedDict(*args, **kwargs)


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method."""
    result = processutils.execute(*cmd, **kwargs)
    LOG.debug(gtu._('Execution completed, command line is "%s"'),
              ' '.join(cmd))
    LOG.debug(gtu._('Command stdout is: "%s"') % result[0])
    LOG.debug(gtu._('Command stderr is: "%s"') % result[1])
    return result

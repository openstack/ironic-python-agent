# Copyright 2013 Rackspace, Inc.
#
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

import collections
import glob
import os

from oslo_concurrency import processutils

from ironic_python_agent import errors
from ironic_python_agent.openstack.common import _i18n as gtu
from ironic_python_agent.openstack.common import log as logging

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


def _read_params_from_file(filepath):
    """Extract key=value pairs from a file.

    :param filepath: path to a file containing key=value pairs separated by
                     whitespace or newlines.
    :returns: a dictionary representing the content of the file
    """
    with open(filepath) as f:
        cmdline = f.read()

    options = cmdline.split()
    params = {}
    for option in options:
        if '=' not in option:
            continue
        k, v = option.split('=', 1)
        params[k] = v

    return params


def _get_vmedia_device():
    """Finds the device filename of the virtual media device using sysfs.

    :returns: a string containing the filename of the virtual media device
    """
    sysfs_device_models = glob.glob("/sys/class/block/*/device/model")
    vmedia_device_model = "virtual media"
    for model_file in sysfs_device_models:
        try:
            with open(model_file) as model_file_fobj:
                if vmedia_device_model in model_file_fobj.read().lower():
                    vmedia_device = model_file.split('/')[4]
                    return vmedia_device
        except Exception:
            pass


def _get_vmedia_params():
    """This method returns the parameters passed to the agent through virtual
    media floppy.

    :returns: a partial dict of potential agent configuration parameters
    :raises: VirtualMediaBootError when it cannot find the virtual media device
    """
    vmedia_mount_point = "/vmedia_mnt"
    parameters_file = "parameters.txt"

    vmedia_device_file = "/dev/disk/by-label/ir-vfd-dev"
    if not os.path.exists(vmedia_device_file):

        # TODO(rameshg87): This block of code is there only for compatibility
        # reasons (so that newer agent can work with older Ironic). Remove
        # this after Liberty release.
        vmedia_device = _get_vmedia_device()
        if not vmedia_device:
            msg = "Unable to find virtual media device"
            raise errors.VirtualMediaBootError(msg)

        vmedia_device_file = os.path.join("/dev", vmedia_device)

    os.mkdir(vmedia_mount_point)

    try:
        stdout, stderr = execute("mount", vmedia_device_file,
                                 vmedia_mount_point)
    except processutils.ProcessExecutionError as e:
        msg = ("Unable to mount virtual media device %(device)s: %(error)s" %
              {'device': vmedia_device_file, 'error': e})
        raise errors.VirtualMediaBootError(msg)

    parameters_file_path = os.path.join(vmedia_mount_point, parameters_file)
    params = _read_params_from_file(parameters_file_path)

    try:
        stdout, stderr = execute("umount", vmedia_mount_point)
    except processutils.ProcessExecutionError as e:
        pass

    return params


def get_agent_params():
    """Gets parameters passed to the agent via kernel cmdline or vmedia.

    Parameters can be passed using either the kernel commandline or through
    virtual media. If boot_method is vmedia, merge params provided via vmedia
    with those read from the kernel command line.

    Although it should never happen, if a variable is both set by vmedia and
    kernel command line, the setting in vmedia will take precedence.

    :returns: a dict of potential configuration parameters for the agent
    """
    params = _read_params_from_file('/proc/cmdline')

    # If the node booted over virtual media, the parameters are passed
    # in a text file within the virtual media floppy.
    if params.get('boot_method', None) == 'vmedia':
        vmedia_params = _get_vmedia_params()
        params.update(vmedia_params)

    return params

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

import copy
import glob
import os
import shutil
import tempfile

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import units
from six.moves.urllib import parse

from ironic_python_agent import errors

LOG = logging.getLogger(__name__)


SUPPORTED_ROOT_DEVICE_HINTS = set(('size', 'model', 'wwn', 'serial', 'vendor'))

# Agent parameters can be passed by kernel command-line arguments and/or
# by virtual media. Virtual media parameters passed would be available
# when the agent is started, but might not be available for re-reading
# later on because:
# * Virtual media might be exposed from Swift and swift temp url might
#   expire.
# * Ironic might have removed the floppy image from Swift after starting
#   the deploy.
#
# Even if it's available, there is no need to re-read from the device and
# /proc/cmdline again, because it is never going to change.  So we cache the
# agent parameters that was passed (by proc/cmdline and/or virtual media)
# when we read it for the first time, and then use this cache.
AGENT_PARAMS_CACHED = dict()


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    :param *cmd: positional arguments to pass to processutils.execute()
    :param log_stdout: keyword-only argument: whether to log the output
    :param **kwargs: keyword arguments to pass to processutils.execute()
    :raises: UnknownArgumentError on receiving unknown arguments
    :raises: ProcessExecutionError
    :raises: OSError
    :returns: tuple of (stdout, stderr)
    """
    log_stdout = kwargs.pop('log_stdout', True)
    result = processutils.execute(*cmd, **kwargs)
    LOG.debug('Execution completed, command line is "%s"', ' '.join(cmd))
    if log_stdout:
        LOG.debug('Command stdout is: "%s"', result[0])
    LOG.debug('Command stderr is: "%s"', result[1])
    return result


def try_execute(*cmd, **kwargs):
    """The same as execute but returns None on error.

    Executes and logs results from a system command. See docs for
    oslo_concurrency.processutils.execute for usage.

    Instead of raising an exception on failure, this method simply
    returns None in case of failure.

    :param *cmd: positional arguments to pass to processutils.execute()
    :param log_stdout: keyword-only argument: whether to log the output
    :param **kwargs: keyword arguments to pass to processutils.execute()
    :raises: UnknownArgumentError on receiving unknown arguments
    :returns: tuple of (stdout, stderr) or None in some error cases
    """
    try:
        return execute(*cmd, **kwargs)
    except (processutils.ProcessExecutionError, OSError) as e:
        LOG.debug('Command failed: %s', e)


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
    """This method returns the parameters passed through virtual media floppy.

    :returns: a partial dict of potential agent configuration parameters
    :raises: VirtualMediaBootError when it cannot find the virtual media device
    """
    parameters_file = "parameters.txt"

    vmedia_device_file_lower_case = "/dev/disk/by-label/ir-vfd-dev"
    vmedia_device_file_upper_case = "/dev/disk/by-label/IR-VFD-DEV"
    if os.path.exists(vmedia_device_file_lower_case):
        vmedia_device_file = vmedia_device_file_lower_case
    elif os.path.exists(vmedia_device_file_upper_case):
        vmedia_device_file = vmedia_device_file_upper_case
    else:

        # TODO(rameshg87): This block of code is there only for compatibility
        # reasons (so that newer agent can work with older Ironic). Remove
        # this after Liberty release.
        vmedia_device = _get_vmedia_device()
        if not vmedia_device:
            msg = "Unable to find virtual media device"
            raise errors.VirtualMediaBootError(msg)

        vmedia_device_file = os.path.join("/dev", vmedia_device)

    vmedia_mount_point = tempfile.mkdtemp()
    try:
        try:
            stdout, stderr = execute("mount", vmedia_device_file,
                                     vmedia_mount_point)
        except processutils.ProcessExecutionError as e:
            msg = ("Unable to mount virtual media device %(device)s: "
                   "%(error)s" % {'device': vmedia_device_file, 'error': e})
            raise errors.VirtualMediaBootError(msg)

        parameters_file_path = os.path.join(vmedia_mount_point,
                                            parameters_file)
        params = _read_params_from_file(parameters_file_path)

        try:
            stdout, stderr = execute("umount", vmedia_mount_point)
        except processutils.ProcessExecutionError as e:
            pass
    finally:
        try:
            shutil.rmtree(vmedia_mount_point)
        except Exception as e:
            pass

    return params


def _get_cached_params():
    """Helper method to get cached params to ease unit testing."""
    return AGENT_PARAMS_CACHED


def _set_cached_params(params):
    """Helper method to set cached params to ease unit testing."""
    global AGENT_PARAMS_CACHED
    AGENT_PARAMS_CACHED = params


def get_agent_params():
    """Gets parameters passed to the agent via kernel cmdline or vmedia.

    Parameters can be passed using either the kernel commandline or through
    virtual media. If boot_method is vmedia, merge params provided via vmedia
    with those read from the kernel command line.

    Although it should never happen, if a variable is both set by vmedia and
    kernel command line, the setting in vmedia will take precedence.

    :returns: a dict of potential configuration parameters for the agent
    """

    # Check if we have the parameters cached
    params = _get_cached_params()
    if not params:
        params = _read_params_from_file('/proc/cmdline')

        # If the node booted over virtual media, the parameters are passed
        # in a text file within the virtual media floppy.
        if params.get('boot_method') == 'vmedia':
            vmedia_params = _get_vmedia_params()
            params.update(vmedia_params)

        # Cache the parameters so that it can be used later on.
        _set_cached_params(params)

    return copy.deepcopy(params)


def normalize(string):
    """Return a normalized string.

    Take a urlencoded value from Ironic and urldecode it.

    :param string: a urlencoded string
    :returns: a normalized version of passed in string
    """
    return parse.unquote(string).lower().strip()


def parse_root_device_hints():
    """Parse the root device hints.

    Parse the root device hints given by Ironic via kernel cmdline
    or vmedia.

    :returns: A dict with the hints or an empty dict if no hints are
              passed.
    :raises: DeviceNotFound if there are unsupported hints.

    """
    root_device = get_agent_params().get('root_device')
    if not root_device:
        return {}

    hints = dict((item.split('=') for item in root_device.split(',')))

    # Find invalid hints for logging
    not_supported = set(hints) - SUPPORTED_ROOT_DEVICE_HINTS
    if not_supported:
        error_msg = ('No device can be found because the following hints: '
                     '"%(not_supported)s" are not supported by this version '
                     'of IPA. Supported hints are: "%(supported)s"',
                     {'not_supported': ', '.join(not_supported),
                      'supported': ', '.join(SUPPORTED_ROOT_DEVICE_HINTS)})
        raise errors.DeviceNotFound(error_msg)

    # Normalise the values
    hints = {k: normalize(v) for k, v in hints.items()}

    if 'size' in hints:
        # NOTE(lucasagomes): Ironic should validate before passing to
        # the deploy ramdisk
        hints['size'] = int(hints['size'])

    return hints


class AccumulatedFailures(object):
    """Object to accumulate failures without raising exception."""

    def __init__(self, exc_class=RuntimeError):
        self._failures = []
        self._exc_class = exc_class

    def add(self, fail, *fmt):
        """Add failure with optional formatting.

        :param fail: exception or error string
        :param fmt: formatting arguments (only if fail is a string)
        """
        if fmt:
            fail = fail % fmt
        LOG.error('%s', fail)
        self._failures.append(fail)

    def get_error(self):
        """Get error string or None."""
        if not self._failures:
            return

        msg = ('The following errors were encountered:\n%s'
               % '\n'.join('* %s' % item for item in self._failures))
        return msg

    def raise_if_needed(self):
        """Raise exception if error list is not empty.

        :raises: RuntimeError
        """
        if self._failures:
            raise self._exc_class(self.get_error())

    def __nonzero__(self):
        return bool(self._failures)

    __bool__ = __nonzero__

    def __repr__(self):  # pragma: no cover
        # This is for tests
        if self:
            return '<%s: %s>' % (self.__class__.__name__,
                                 ', '.join(self._failures))
        else:
            return '<%s: success>' % self.__class__.__name__


def guess_root_disk(block_devices, min_size_required=4 * units.Gi):
    """Find suitable disk provided that root device hints are not given.

    If no hints are passed find the first device larger than min_size_required,
    assume it is the OS disk
    """
    # TODO(russellhaering): This isn't a valid assumption in
    # all cases, is there a more reasonable default behavior?
    block_devices.sort(key=lambda device: device.size)
    if not block_devices or block_devices[-1].size < min_size_required:
        raise errors.DeviceNotFound(
            "No suitable device was found "
            "for deployment - root device hints were not provided "
            "and all found block devices are smaller than %iB."
            % min_size_required)
    for device in block_devices:
        if device.size >= min_size_required:
            return device

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

"""Implementation of the inject_files deploy step."""

import base64
import contextlib
import os

from ironic_lib import utils as ironic_utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log

from ironic_python_agent import disk_utils
from ironic_python_agent import errors
from ironic_python_agent import hardware
from ironic_python_agent import utils


CONF = cfg.CONF
LOG = log.getLogger(__name__)


ARGSINFO = {
    "files": {
        "description": (
            "Files to inject, a list of file structures with keys: 'path' "
            "(path to the file), 'partition' (partition specifier), "
            "'content' (base64 encoded string), 'mode' (new file mode) and "
            "'dirmode' (mode for the leaf directory, if created). "
            "Merged with the values from node.properties[inject_files]."
        ),
        "required": False,
    },
    "verify_ca": {
        "description": (
            "Whether to verify TLS certificates. Global agent options "
            "are used by default."
        ),
        "required": False,
    }
}


def inject_files(node, ports, files, verify_ca=True):
    """A deploy step to inject arbitrary files.

    :param node: A dictionary of the node object
    :param ports: A list of dictionaries containing information
                  of ports for the node
    :param files: See ARGSINFO.
    :param verify_ca: Whether to verify TLS certificate.
    :raises: InvalidCommandParamsError
    """
    files = _validate_files(
        node['properties'].get('inject_files') or [],
        files or [])
    if not files:
        LOG.info('No files to inject')
        return

    http_get = utils.StreamingClient(verify_ca)
    root_dev = hardware.dispatch_to_managers('get_os_install_device')

    for fl in files:
        _inject_one(node, ports, fl, root_dev, http_get)


def _inject_one(node, ports, fl, root_dev, http_get):
    """Inject one file.

    :param node: A dictionary of the node object
    :param ports: A list of dictionaries containing information
                  of ports for the node
    :param fl: File information.
    :param root_dev: Root device used for the current node.
    :param http_get: Context manager to get HTTP URLs.
    """
    with _find_and_mount_path(fl['path'], fl.get('partition'),
                              root_dev) as path:
        if fl.get('deleted'):
            ironic_utils.unlink_without_raise(path)
            return

        try:
            dirpath = os.path.dirname(path)
            try:
                os.makedirs(dirpath)
            except FileExistsError:
                pass
            else:
                # Use chmod here and below to avoid relying on umask
                if fl.get('dirmode'):
                    os.chmod(dirpath, fl['dirmode'])

            content = fl['content']
            with open(path, 'wb') as fp:
                if '://' in content:
                    # Allow node-specific URLs to be used in a deploy template
                    url = content.format(node=node, ports=ports)
                    with http_get(url) as resp:
                        for chunk in resp:
                            fp.write(chunk)
                else:
                    fp.write(base64.b64decode(content))

            if fl.get('mode'):
                os.chmod(path, fl['mode'])

            if fl.get('owner') is not None or fl.get('group') is not None:
                # -1 means do not change
                os.chown(path, fl.get('owner', -1), fl.get('group', -1))
        except Exception as exc:
            LOG.exception('Failed to process file %s', fl)
            raise errors.CommandExecutionError(
                'Failed to process file %s. %s: %s'
                % (fl, type(exc).__class__, exc))


@contextlib.contextmanager
def _find_and_mount_path(path, partition, root_dev):
    """Find the specified path on a device.

    Tries to find the suitable device for the file based on the ``path`` and
    ``partition``, mount the device and provides the actual full path.

    :param path: Path to the file to find.
    :param partition: Device to find the file on or None.
    :param root_dev: Root device from the hardware manager.
    :return: Context manager that yields the full path to the file.
    """
    path = os.path.normpath(path.strip('/'))  # to make path joining work
    if partition:
        try:
            part_num = int(partition)
        except ValueError:
            with ironic_utils.mounted(partition) as part_path:
                yield os.path.join(part_path, path)
        else:
            # TODO(dtantsur): switch to ironic-lib instead:
            # https://review.opendev.org/c/openstack/ironic-lib/+/774502
            part_template = '%s%s'
            if 'nvme' in root_dev:
                part_template = '%sp%s'
            part_dev = part_template % (root_dev, part_num)

            with ironic_utils.mounted(part_dev) as part_path:
                yield os.path.join(part_path, path)
    else:
        try:
            # This turns e.g. etc/sysctl.d/my.conf into etc + sysctl.d/my.conf
            detect_dir, rest_dir = path.split('/', 1)
        except ValueError:
            # Validation ensures that files in / have "partition" present,
            # checking here just in case.
            raise errors.InvalidCommandParamsError(
                "Invalid path %s, must be an absolute path to a file" % path)

        with find_partition_with_path(detect_dir, root_dev) as part_path:
            yield os.path.join(part_path, rest_dir)


@contextlib.contextmanager
def find_partition_with_path(path, device=None):
    """Find a partition with the given path.

    :param path: Expected path.
    :param device: Target device. If None, the root device is used.
    :returns: A context manager that will unmount and delete the temporary
        mount point on exit.
    """
    if device is None:
        device = hardware.dispatch_to_managers('get_os_install_device')
    partitions = disk_utils.list_partitions(device)
    # Make os.path.join work as expected
    lookup_path = path.lstrip('/')

    for part in partitions:
        if 'lvm' in part['flags']:
            LOG.debug('Skipping LVM partition %s', part)
            continue

        # TODO(dtantsur): switch to ironic-lib instead:
        # https://review.opendev.org/c/openstack/ironic-lib/+/774502
        part_template = '%s%s'
        if 'nvme' in device:
            part_template = '%sp%s'
        part_path = part_template % (device, part['number'])

        LOG.debug('Inspecting partition %s for path %s', part, path)
        try:
            with ironic_utils.mounted(part_path) as local_path:
                found_path = os.path.join(local_path, lookup_path)
                if not os.path.isdir(found_path):
                    continue

                LOG.info('Path %s has been found on partition %s', path, part)
                yield found_path
                return
        except processutils.ProcessExecutionError as exc:
            LOG.warning('Failure when inspecting partition %s: %s', part, exc)

    raise errors.DeviceNotFound("No partition found with path %s, scanned: %s"
                                % (path, partitions))


def _validate_files(from_properties, from_args):
    """Sanity check for files."""
    if not isinstance(from_properties, list):
        raise errors.InvalidCommandParamsError(
            "The `inject_files` node property must be a list, got %s"
            % type(from_properties).__name__)
    if not isinstance(from_args, list):
        raise errors.InvalidCommandParamsError(
            "The `files` argument must be a list, got %s"
            % type(from_args).__name__)

    files = from_properties + from_args
    failures = []

    for fl in files:
        unknown = set(fl) - {'path', 'partition', 'content', 'deleted', 'mode',
                             'dirmode', 'owner', 'group'}
        if unknown:
            failures.append('unexpected fields in %s: %s'
                            % (fl, ', '.join(unknown)))

        if not fl.get('path'):
            failures.append('expected a path in %s' % fl)
        elif os.path.dirname(fl['path']) == '/' and not fl.get('partition'):
            failures.append('%s in root directory requires "partition"' % fl)
        elif fl['path'].endswith('/'):
            failures.append('directories not supported for %s' % fl)

        if fl.get('content') and fl.get('deleted'):
            failures.append('content cannot be used with deleted in %s' % fl)

        for field in ('owner', 'group', 'mode', 'dirmode'):
            if field in fl and type(fl[field]) is not int:
                failures.append('%s must be a number in %s' % (field, fl))

    if failures:
        raise errors.InvalidCommandParamsError(
            "Validation of files failed: %s" % '; '.join(failures))

    return files

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

import time

from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_log import log

from ironic_python_agent import errors
from ironic_python_agent import hardware

LOG = log.getLogger(__name__)

NETWORK_BURNIN_ROLES = frozenset(['writer', 'reader'])
NETWORK_READER_CYCLE = 30


def stress_ng_cpu(node):
    """Burn-in the CPU with stress-ng

    Run stress-ng on a configurable number of CPUs for
    a configurable amount of time. Without config use
    all CPUs and stress them for 24 hours.

    :param node: Ironic node object
    :raises: CommandExecutionError if the execution of stress-ng fails.
    """
    info = node.get('driver_info', {})
    cpu = info.get('agent_burnin_cpu_cpu', 0)
    timeout = info.get('agent_burnin_cpu_timeout', 86400)

    args = ('stress-ng', '--cpu', cpu, '--timeout', timeout,
            '--metrics-brief')
    LOG.debug('Burn-in stress_ng_cpu command: %s', args)

    try:
        _, err = utils.execute(*args)
        # stress-ng reports on stderr only
        LOG.info(err)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = ("stress-ng (cpu) failed with error %(err)s",
                     {'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def stress_ng_vm(node):
    """Burn-in the memory with the vm stressor in stress-ng

    Run stress-ng with a configurable number of workers on
    a configurable amount of the available memory for
    a configurable amount of time. Without config use
    as many workers as CPUs, 98% of the memory and stress
    it for 24 hours.

    :param node: Ironic node object
    :raises: CommandExecutionError if the execution of stress-ng fails.
    """
    info = node.get('driver_info', {})
    vm = info.get('agent_burnin_vm_vm', 0)
    vm_bytes = info.get('agent_burnin_vm_vm-bytes', '98%')
    timeout = info.get('agent_burnin_vm_timeout', 86400)

    args = ('stress-ng', '--vm', vm, '--vm-bytes', vm_bytes,
            '--timeout', timeout, '--metrics-brief')
    LOG.debug('Burn-in stress_ng_vm command: %s', args)

    try:
        _, err = utils.execute(*args)
        # stress-ng reports on stderr only
        LOG.info(err)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = ("stress-ng (vm) failed with error %(err)s",
                     {'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def fio_disk(node):
    """Burn-in the disks with fio

    Run an fio randrw job for a configurable number of iterations
    or a given amount of time.

    :param node: Ironic node object
    :raises: CommandExecutionError if the execution of fio fails.
    """
    info = node.get('driver_info', {})
    # 4 iterations, same as badblock's default
    loops = info.get('agent_burnin_fio_disk_loops', 4)
    runtime = info.get('agent_burnin_fio_disk_runtime', 0)

    args = ['fio', '--rw', 'readwrite', '--bs', '4k', '--direct', 1,
            '--ioengine', 'libaio', '--iodepth', '32', '--verify',
            'crc32c', '--verify_dump', 1, '--continue_on_error', 'verify',
            '--loops', loops, '--runtime', runtime, '--time_based']

    devices = hardware.list_all_block_devices()
    for device in devices:
        args.extend(['--name', device.name])

    LOG.debug('Burn-in fio disk command: %s', ' '.join(map(str, args)))

    try:
        out, _ = utils.execute(*args)
        # fio reports on stdout
        LOG.info(out)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = ("fio (disk) failed with error %(err)s",
                     {'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def _do_fio_network(writer, runtime, partner):

    args = ['fio', '--ioengine', 'net', '--port', '9000', '--fill_device', 1,
            '--group_reporting', '--gtod_reduce', 1, '--numjobs', 16]
    if writer:
        xargs = ['--name', 'writer', '--rw', 'write', '--runtime', runtime,
                 '--time_based', '--listen']
    else:
        xargs = ['--name', 'reader', '--rw', 'read', '--hostname', partner]
    args.extend(xargs)

    while True:
        LOG.info('Burn-in fio network command: %s', ' '.join(map(str, args)))
        try:
            out, err = utils.execute(*args)
            # fio reports on stdout
            LOG.info(out)
            break
        except (processutils.ProcessExecutionError, OSError) as e:
            error_msg = ("fio (network) failed with error %(err)s",
                         {'err': e})
            LOG.error(error_msg)
            # while the writer blocks in fio, the reader fails with
            # 'Connection {refused, timeout}' errors if the partner
            # is not ready, so we need to wait explicitly
            if not writer and 'Connection' in str(e):
                LOG.info("fio (network): reader retrying in %s seconds ...",
                         NETWORK_READER_CYCLE)
                time.sleep(NETWORK_READER_CYCLE)
            else:
                raise errors.CommandExecutionError(error_msg)


def fio_network(node):
    """Burn-in the network with fio

    Run an fio network job for a pair of nodes for a configurable
    amount of time. The pair is statically defined in driver_info
    via 'agent_burnin_fio_network_config'.
    The writer will wait for the reader to connect, then write to the
    network. Upon completion, the roles are swapped.

    Note (arne_wiebalck): Initial version. The plan is to make the
                          match making dynamic by posting availability
                          on a distributed backend, e.g. via tooz.

    :param node: Ironic node object
    :raises: CommandExecutionError if the execution of fio fails.
    :raises: CleaningError if the configuration is incomplete.
    """

    info = node.get('driver_info', {})
    runtime = info.get('agent_burnin_fio_network_runtime', 21600)

    # get our role and identify our partner
    config = info.get('agent_burnin_fio_network_config')
    if not config:
        error_msg = ("fio (network) failed to find "
                     "'agent_burnin_fio_network_config' in driver_info")
        raise errors.CleaningError(error_msg)
    LOG.debug("agent_burnin_fio_network_config is %s", str(config))

    role = config.get('role')
    if role not in NETWORK_BURNIN_ROLES:
        error_msg = ("fio (network) found an unknown role: %s", role)
        raise errors.CleaningError(error_msg)

    partner = config.get('partner')
    if not partner:
        error_msg = ("fio (network) failed to find partner")
        raise errors.CleaningError(error_msg)

    _do_fio_network(role == 'writer', runtime, partner)
    LOG.debug("fio (network): first direction done, swapping roles ...")
    _do_fio_network(not role == 'writer', runtime, partner)

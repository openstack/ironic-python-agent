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

import json
import socket
import time

from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_log import log
from tooz import coordination

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
    outputfile = info.get('agent_burnin_cpu_outputfile', None)

    args = ('stress-ng', '--cpu', cpu, '--timeout', timeout,
            '--metrics-brief')
    if outputfile:
        args += ('--log-file', outputfile,)

    LOG.debug('Burn-in stress_ng_cpu command: %s', args)

    try:
        _, err = utils.execute(*args)
        # stress-ng reports on stderr only
        LOG.info(err)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = "stress-ng (cpu) failed with error %s" % e
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
    outputfile = info.get('agent_burnin_vm_outputfile', None)

    args = ('stress-ng', '--vm', vm, '--vm-bytes', vm_bytes,
            '--timeout', timeout, '--metrics-brief')
    if outputfile:
        args += ('--log-file', outputfile,)

    LOG.debug('Burn-in stress_ng_vm command: %s', args)

    try:
        _, err = utils.execute(*args)
        # stress-ng reports on stderr only
        LOG.info(err)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = "stress-ng (vm) failed with error %s" % e
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def _smart_test_status(device):
    """Get the SMART test status of a device

    :param device: The device to check.
    :raises: CommandExecutionError if the execution of smartctl fails.
    :returns: A string with the SMART test status of the device and
              None if the status is not available.
    """
    args = ['smartctl', '-ja', device.name]
    try:
        out, _ = utils.execute(*args)
        smart_info = json.loads(out)
        if smart_info:
            return smart_info['ata_smart_data'][
                'self_test']['status']['string']
    except (processutils.ProcessExecutionError, OSError, KeyError) as e:
        LOG.error('SMART test on %(device)s failed with '
                  '%(err)s', {'device': device.name, 'err': e})
    return None


def _run_smart_test(devices):
    """Launch a SMART test on the passed devices

    :param devices: A list of device objects to check.
    :raises: CommandExecutionError if the execution of smartctl fails.
    :raises: CleaningError if the SMART test on any of the devices fails.
    """
    failed_devices = []
    for device in devices:
        args = ['smartctl', '-t', 'long', device.name]
        LOG.info('SMART self test command: %s',
                 ' '.join(map(str, args)))
        try:
            utils.execute(*args)
        except (processutils.ProcessExecutionError, OSError) as e:
            LOG.error("Starting SMART test on %(device)s failed with: "
                      "%(err)s", {'device': device.name, 'err': e})
            failed_devices.append(device.name)
    if failed_devices:
        error_msg = ("fio (disk) failed to start SMART self test on %s",
                     ', '.join(failed_devices))
        raise errors.CleaningError(error_msg)

    # wait for the test to finish and report the test results
    failed_devices = []
    while True:
        for device in list(devices):
            status = _smart_test_status(device)
            if status is None:
                devices.remove(device)
                continue
            if "in progress" in status:
                msg = "SMART test still running on %s ..." % device.name
                LOG.debug(msg)
                continue
            if "completed without error" in status:
                msg = "%s passed SMART test" % device.name
                LOG.info(msg)
                devices.remove(device)
                continue
            failed_devices.append(device.name)
            LOG.warning("%(device)s failed SMART test with: %(err)s",
                        {'device': device.name, 'err': status})
            devices.remove(device)
        if not devices:
            break
        LOG.info("SMART tests still running ...")
        time.sleep(30)

    # fail the clean step if the SMART test has failed
    if failed_devices:
        msg = ('fio (disk) SMART test failed for %s' % ' '.join(
            map(str, failed_devices)))
        raise errors.CleaningError(msg)


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
    outputfile = info.get('agent_burnin_fio_disk_outputfile', None)

    args = ['fio', '--rw', 'readwrite', '--bs', '4k', '--direct', 1,
            '--ioengine', 'libaio', '--iodepth', '32', '--verify',
            'crc32c', '--verify_dump', 1, '--continue_on_error', 'verify',
            '--loops', loops, '--runtime', runtime, '--time_based']
    if outputfile:
        args.extend(['--output-format', 'json', '--output', outputfile])

    devices = hardware.list_all_block_devices()
    for device in devices:
        args.extend(['--name', device.name])

    LOG.debug('Burn-in fio disk command: %s', ' '.join(map(str, args)))

    try:
        out, _ = utils.execute(*args)
        # fio reports on stdout
        LOG.info(out)
    except (processutils.ProcessExecutionError, OSError) as e:
        error_msg = "fio (disk) failed with error %s" % e
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)

    # if configured, run a smart self test on all devices and fail the
    # step if any of the devices reports an error
    smart_test = info.get('agent_burnin_fio_disk_smart_test', False)
    if smart_test:
        _run_smart_test(devices)


def _do_fio_network(writer, runtime, partner, outputfile):

    args = ['fio', '--ioengine', 'net', '--port', '9000', '--fill_device', 1,
            '--group_reporting', '--gtod_reduce', 1, '--numjobs', 16]
    if writer:
        xargs = ['--name', 'writer', '--rw', 'write', '--runtime', runtime,
                 '--time_based', '--listen']
    else:
        xargs = ['--name', 'reader', '--rw', 'read', '--hostname', partner]
    args.extend(xargs)
    if outputfile:
        args.extend(['--output-format', 'json', '--output', outputfile])

    while True:
        LOG.info('Burn-in fio network command: %s', ' '.join(map(str, args)))
        try:
            out, err = utils.execute(*args)
            # fio reports on stdout
            LOG.info(out)
            break
        except processutils.ProcessExecutionError as e:
            error_msg = "fio (network) failed with error %s" % e
            LOG.error(error_msg)
            if writer:
                raise errors.CommandExecutionError(error_msg)
            # While the writer blocks in fio, the reader fails with
            # 'Connection {refused, timeout}' errors if the partner
            # is not ready, so we need to wait explicitly. Using the
            # exit code accounts for both, logging to stderr as well
            # as to a file.
            if e.exit_code == 16:
                LOG.info("fio (network): reader retrying in %s seconds ...",
                         NETWORK_READER_CYCLE)
                time.sleep(NETWORK_READER_CYCLE)
            else:
                raise errors.CommandExecutionError(error_msg)


def _find_network_burnin_partner_and_role(backend_url, group_name, timeout):
    """Find a partner node for network burn-in and get our role.

    :param backend_url: The tooz backend url.
    :param group_name: The tooz group name for pairing.
    :param timeout:Timeout in seconds for a node to wait for a partner.
    :returns: A set with the partner node and the role of the local node.
    """

    member_id = socket.gethostname()
    coordinator = coordination.get_coordinator(backend_url, member_id)
    coordinator.start(start_heart=True)

    groups = coordinator.get_groups()
    for group in groups.get():
        if group_name == group.decode('utf-8'):
            LOG.debug("Found group %s", group_name)
            break
    else:
        LOG.info("Creating group %s", group_name)
        coordinator.create_group(group_name)

    def join_group(group_name):
        request = coordinator.join_group(group_name)
        request.get()

    def leave_group(group_name):
        request = coordinator.leave_group(group_name)
        request.get()

    # Attempt to get the pairing lock. The lock is released when:
    # a) a node enters the group and is the first to join, or
    # b) a node enters second, finished pairing, sees
    #    the pairing node exiting, and left itself.
    # The lock 'walls' all nodes willing to pair.
    group_lock = coordinator.get_lock("group_lock")
    with group_lock:
        # we need the initial members in order to know the first
        # node (which may leave quickly when we join)
        init_members = coordinator.get_members(group_name)
        LOG.info("Original group members are %s", init_members.get())
        members_cnt = len(init_members.get())

        join_group(group_name)

        # we assign the first node the writer role since it will
        # leave the group first, it may be ready once the second
        # node leaves the group, and we save one wait cycle
        if not members_cnt:
            first = True
            role = "writer"
            group_lock.release()  # allow second node to enter
        else:
            first = False
            role = "reader"

        partner = None
        start_pairing = time.time()
        while time.time() - start_pairing < timeout:
            if first:
                # we are the first and therefore need to wait
                # for another node to join
                members = coordinator.get_members(group_name)
                members_cnt = len(members.get())
            else:
                # use the initial members in case the other
                # node leaves before we get an updated list
                members = init_members

            assert members_cnt < 3

            if members_cnt == 2 or not first:
                LOG.info("Two members, start pairing...")
                for member in members.get():
                    node = member.decode('utf-8')
                    if node != member_id:
                        partner = node
                if not partner:
                    error_msg = ("fio (network) no partner to pair found")
                    raise errors.CleaningError(error_msg)

                # if you are the second to enter, wait for the first to exit
                if not first:
                    members = coordinator.get_members(group_name)
                    while (len(members.get()) == 2):
                        time.sleep(0.2)
                        members = coordinator.get_members(group_name)
                    leave_group(group_name)
                    group_lock.release()
                else:
                    leave_group(group_name)
                break
            else:
                LOG.info("One member, waiting for second node to join ...")
            time.sleep(1)
        else:
            leave_group(group_name)
            error_msg = ("fio (network) timed out to find partner")
            raise errors.CleaningError(error_msg)

    return (partner, role)


def fio_network(node):
    """Burn-in the network with fio

    Run an fio network job for a pair of nodes for a configurable
    amount of time. The pair is either statically defined in
    driver_info via 'agent_burnin_fio_network_config' or the role
    and partner is found dynamically via a tooz backend.

    The writer will wait for the reader to connect, then write to the
    network. Upon completion, the roles are swapped.

    :param node: Ironic node object
    :raises: CommandExecutionError if the execution of fio fails.
    :raises: CleaningError if the configuration is incomplete.
    """
    info = node.get('driver_info', {})
    runtime = info.get('agent_burnin_fio_network_runtime', 21600)
    outputfile = info.get('agent_burnin_fio_network_outputfile', None)

    # get our role and identify our partner
    config = info.get('agent_burnin_fio_network_config')
    if config:
        LOG.debug("static agent_burnin_fio_network_config is %s",
                  config)
        role = config.get('role')
        partner = config.get('partner')
    else:
        timeout = info.get(
            'agent_burnin_fio_network_pairing_timeout', 900)
        group_name = info.get(
            'agent_burnin_fio_network_pairing_group_name',
            'ironic.network-burnin')
        backend_url = info.get(
            'agent_burnin_fio_network_pairing_backend_url', None)
        if not backend_url:
            msg = ('fio (network): dynamic pairing config is missing '
                   'agent_burnin_fio_network_pairing_backend_url')
            raise errors.CleaningError(msg)
        LOG.info("dynamic pairing for network burn-in ...")
        (partner, role) = _find_network_burnin_partner_and_role(
            backend_url=backend_url,
            group_name=group_name,
            timeout=timeout)

    if role not in NETWORK_BURNIN_ROLES:
        error_msg = "fio (network) found an unknown role: %s" % role
        raise errors.CleaningError(error_msg)
    if not partner:
        error_msg = "fio (network) failed to find partner"
        raise errors.CleaningError(error_msg)
    LOG.info("fio (network): partner %s, role is %s", partner, role)

    logfilename = None
    if outputfile:
        logfilename = outputfile + '.' + role
    _do_fio_network(role == 'writer', runtime, partner, logfilename)

    LOG.debug("fio (network): first direction done, swapping roles ...")

    if outputfile:
        irole = "reader" if (role == "writer") else "writer"
        logfilename = outputfile + '.' + irole
    _do_fio_network(not role == 'writer', runtime, partner, logfilename)

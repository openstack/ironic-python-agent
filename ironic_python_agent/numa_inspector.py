# Copyright 2017 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from oslo_log import log
import pint

from ironic_python_agent import errors

LOG = log.getLogger(__name__)

UNIT_CONVERTER = pint.UnitRegistry(filename=None)
UNIT_CONVERTER.define('kB = []')
UNIT_CONVERTER.define('KB = []')
UNIT_CONVERTER.define('MB = 1024 KB')
UNIT_CONVERTER.define('GB = 1048576 KB')


def get_numa_node_id(numa_node_dir):
    """Provides the NUMA node id from NUMA node directory

    :param numa_node_dir: NUMA node directory
    :raises: IncompatibleNumaFormatError: when unexpected format data
             in NUMA node dir

    :return: NUMA node id
    """
    try:
        return int(os.path.basename(numa_node_dir)[4:])
    except (IOError, ValueError, IndexError) as exc:
        msg = ('Failed to get NUMA node id for %(node)s: '
               '%(error)s' % {'node': numa_node_dir, 'error': exc})
        raise errors.IncompatibleNumaFormatError(msg)


def get_nodes_memory_info(numa_node_dirs):
    """Collect the NUMA nodes memory information.

    "ram": [{"numa_node": <numa_node_id>, "size_kb": <memory_in_kb>}, ...]

    :param numa_node_dirs: A list of NUMA node directories
    :raises: IncompatibleNumaFormatError: when unexpected format data
             in NUMA node

    :return: A list of memory information with NUMA node id
    """
    ram = []
    for numa_node_dir in numa_node_dirs:
        numa_node_memory = {}
        numa_node_id = get_numa_node_id(numa_node_dir)
        try:
            with open(os.path.join(numa_node_dir,
                      'meminfo')) as meminfo_file:
                for line in meminfo_file:
                    if 'MemTotal' in line:
                        break
                else:
                    msg = ('Memory information is not available for '
                           '%(node)s' % {'node': numa_node_dir})
                    raise errors.IncompatibleNumaFormatError(msg)
        except IOError as exc:
            msg = ('Failed to get memory information '
                   'for %(node)s: %(error)s' %
                   {'node': numa_node_dir, 'error': exc})
            raise errors.IncompatibleNumaFormatError(msg)
        try:
            # To get memory size with unit from memory info line
            # Memory info sample line format 'Node 0 MemTotal: 1560000 kB'
            value = line.split(":")[1].strip()
            memory_kb = int(UNIT_CONVERTER(value).to_base_units())
        except (ValueError, IndexError, pint.UndefinedUnitError) as exc:
            msg = ('Failed to get memory information for %(node)s: '
                   '%(error)s' % {'node': numa_node_dir, 'error': exc})
            raise errors.IncompatibleNumaFormatError(msg)
        numa_node_memory['numa_node'] = numa_node_id
        numa_node_memory['size_kb'] = memory_kb
        LOG.debug('Found memory available %d KB in NUMA node %d',
                  memory_kb, numa_node_id)
        ram.append(numa_node_memory)
    return ram


def get_nodes_cores_info(numa_node_dirs):
    """Collect the NUMA nodes cpu's and thread's information.

    "cpus": [
          {
            "cpu": <cpu_id>, "numa_node": <numa_node_id>,
            "thread_siblings": [<list of sibling threads>]
          },
          ...,
        ]
    NUMA nodes path: /sys/devices/system/node/node<node_id>

    Thread dirs path: /sys/devices/system/node/node<node_id>/cpu<thread_id>

    CPU id file path: /sys/devices/system/node/node<node_id>/cpu<thread_id>/
                      topology/core_id

    :param numa_node_dirs: A list of NUMA node directories
    :raises: IncompatibleNumaFormatError: when unexpected format data
             in NUMA node

    :return: A list of cpu information with NUMA node id and thread siblings
    """
    dict_cpus = {}
    for numa_node_dir in numa_node_dirs:
        numa_node_id = get_numa_node_id(numa_node_dir)
        try:
            thread_dirs = os.listdir(numa_node_dir)
        except OSError as exc:
            msg = ('Failed to get list of threads for %(node)s: '
                   '%(error)s' % {'node': numa_node_dir, 'error': exc})
            raise errors.IncompatibleNumaFormatError(msg)
        for thread_dir in thread_dirs:
            if (not os.path.isdir(os.path.join(numa_node_dir, thread_dir))
                or not thread_dir.startswith("cpu")):
                continue
            try:
                thread_id = int(thread_dir[3:])
            except (ValueError, IndexError) as exc:
                msg = ('Failed to get cores information for '
                       '%(node)s: %(error)s' %
                       {'node': numa_node_dir, 'error': exc})
                raise errors.IncompatibleNumaFormatError(msg)
            try:
                with open(os.path.join(numa_node_dir, thread_dir, 'topology',
                          'core_id')) as core_id_file:
                    cpu_id = int(core_id_file.read().strip())
            except (IOError, ValueError) as exc:
                msg = ('Failed to gather cpu_id for thread'
                       '%(thread)s NUMA node %(node)s: %(error)s' %
                       {'thread': thread_dir, 'node': numa_node_dir,
                        'error': exc})
                raise errors.IncompatibleNumaFormatError(msg)
            # CPU and NUMA node together forms a unique value, as cpu_id is
            # specific to a NUMA node
            # NUMA node id and cpu id tuple is used for unique key
            dict_key = numa_node_id, cpu_id
            if dict_key in dict_cpus:
                if thread_id not in dict_cpus[dict_key]['thread_siblings']:
                    dict_cpus[dict_key]['thread_siblings'].append(thread_id)
            else:
                cpu_item = {}
                cpu_item['thread_siblings'] = [thread_id]
                cpu_item['cpu'] = cpu_id
                cpu_item['numa_node'] = numa_node_id
                dict_cpus[dict_key] = cpu_item
            LOG.debug('Found a thread sibling %d for CPU %d in NUMA node %d',
                      thread_id, cpu_id, numa_node_id)
    return list(dict_cpus.values())


def get_nodes_nics_info(nic_device_path):
    """Collect the NUMA nodes nics information.

    "nics": [
          {"name": "<network interface name>", "numa_node": <numa_node_id>},
          ...,
        ]

    :param nic_device_path: nic device directory path
    :raises: IncompatibleNumaFormatError: when unexpected format data
             in NUMA node

    :return: A list of nics information with NUMA node id
    """
    nics = []
    if not os.path.isdir(nic_device_path):
        msg = ('Failed to get list of NIC\'s, NIC device path '
               'does not exist: %(nic_device_path)s' %
               {'nic_device_path': nic_device_path})
        raise errors.IncompatibleNumaFormatError(msg)
    for nic_dir in os.listdir(nic_device_path):
        if not os.path.isdir(os.path.join(nic_device_path, nic_dir, 'device')):
            continue
        try:
            with open(os.path.join(nic_device_path, nic_dir, 'device',
                                   'numa_node')) as nicsinfo_file:
                numa_node_id = int(nicsinfo_file.read().strip())
        except (IOError, ValueError) as exc:
            msg = ('Failed to gather NIC\'s for NUMA node %(node)s: '
                   '%(error)s' % {'node': nic_dir, 'error': exc})
            raise errors.IncompatibleNumaFormatError(msg)
        numa_node_nics = {}
        numa_node_nics['name'] = nic_dir
        numa_node_nics['numa_node'] = numa_node_id
        LOG.debug('Found a NIC %s in NUMA node %d', nic_dir,
                  numa_node_id)
        nics.append(numa_node_nics)
    return nics


def collect_numa_topology_info(data, failures):
    """Collect the NUMA topology information.

    {
      "numa_topology": {
        "ram": [{"numa_node": <numa_node_id>, "size_kb": <memory_in_kb>}, ...],
        "cpus": [
          {
            "cpu": <cpu_id>, "numa_node": <numa_node_id>,
            "thread_siblings": [<list of sibling threads>]
          },
          ...,
        ],
        "nics": [
          {"name": "<network interface name>", "numa_node": <numa_node_id>},
          ...,
        ]
      }
    }

    The data is gathered from /sys/devices/system/node/node<X> and
    /sys/class/net/ directories.

    :param data: mutable data that we'll send to inspector
    :param failures: AccumulatedFailures object

    :return: None
    """
    numa_node_path = '/sys/devices/system/node/'
    nic_device_path = '/sys/class/net/'
    numa_info = {}
    numa_node_dirs = []
    if not os.path.isdir(numa_node_path):
        LOG.warning('Failed to get list of NUMA nodes, NUMA node path '
                    'does not exist: %s', numa_node_path)
        return
    for numa_node_dir in os.listdir(numa_node_path):
        numa_node_dir_path = os.path.join(numa_node_path, numa_node_dir)
        if (os.path.isdir(numa_node_dir_path)
            and numa_node_dir.startswith("node")):
            numa_node_dirs.append(numa_node_dir_path)
    try:
        numa_info['ram'] = get_nodes_memory_info(numa_node_dirs)
        numa_info['cpus'] = get_nodes_cores_info(numa_node_dirs)
        numa_info['nics'] = get_nodes_nics_info(nic_device_path)
    except errors.IncompatibleNumaFormatError as exc:
        LOG.warning('Failed to get some NUMA information (%s)', exc)
        return
    data['numa_topology'] = numa_info

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

import abc
import functools
import os

import psutil
import six
import stevedore

from ironic_python_agent import encoding
from ironic_python_agent.openstack.common import log
from ironic_python_agent import utils

_global_manager = None


class HardwareSupport(object):
    """These are just guidelines to suggest values that might be returned by
    calls to `evaluate_hardware_support`. No HardwareManager in mainline
    ironic-python-agent will ever offer a value greater than `MAINLINE`.
    Service Providers should feel free to return values greater than
    SERVICE_PROVIDER to distinguish between additional levels of support.
    """
    NONE = 0
    GENERIC = 1
    MAINLINE = 2
    SERVICE_PROVIDER = 3


class HardwareType(object):
    MAC_ADDRESS = 'mac_address'


class BlockDevice(encoding.Serializable):
    def __init__(self, name, size):
        self.name = name
        self.size = size

    def serialize(self):
        return utils.get_ordereddict([
            ('name', self.name),
            ('size', self.size),
        ])


class NetworkInterface(encoding.Serializable):
    def __init__(self, name, mac_addr):
        self.name = name
        self.mac_address = mac_addr
        # TODO(russellhaering): Pull these from LLDP
        self.switch_port_descr = None
        self.switch_chassis_descr = None

    def serialize(self):
        return utils.get_ordereddict([
            ('name', self.name),
            ('mac_address', self.mac_address),
            ('switch_port_descr', self.switch_port_descr),
            ('switch_chassis_descr', self.switch_port_descr),
        ])


class CPU(encoding.Serializable):
    def __init__(self, model_name, frequency, count):
        self.model_name = model_name
        self.frequency = frequency
        self.count = count

    def serialize(self):
        return utils.get_ordereddict([
            ('model_name', self.model_name),
            ('frequency', self.frequency),
            ('count', self.count),
        ])


class Memory(encoding.Serializable):
    def __init__(self, total):
        self.total = total

    def serialize(self):
        return utils.get_ordereddict([
            ('total', self.total),
        ])


class HardwareManager(object):
    @abc.abstractmethod
    def evaluate_hardware_support(cls):
        pass

    @abc.abstractmethod
    def list_network_interfaces(self):
        pass

    @abc.abstractmethod
    def get_os_install_device(self):
        pass

    def list_hardware_info(self):
        hardware_info = {}
        hardware_info['interfaces'] = self.list_network_interfaces()
        hardware_info['cpu'] = self.get_cpus()
        hardware_info['disks'] = self.list_block_devices()
        hardware_info['memory'] = self.get_memory()
        return hardware_info


class GenericHardwareManager(HardwareManager):
    def __init__(self):
        self.sys_path = '/sys'

        if os.path.isdir('/mnt/sys'):
            self.sys_path = '/mnt/sys'

    def evaluate_hardware_support(cls):
        return HardwareSupport.GENERIC

    def _get_interface_info(self, interface_name):
        addr_path = '{0}/class/net/{1}/address'.format(self.sys_path,
                                                     interface_name)
        with open(addr_path) as addr_file:
            mac_addr = addr_file.read().strip()

        return NetworkInterface(interface_name, mac_addr)

    def _is_device(self, interface_name):
        device_path = '{0}/class/net/{1}/device'.format(self.sys_path,
                                                      interface_name)
        return os.path.exists(device_path)

    def list_network_interfaces(self):
        iface_names = os.listdir('{0}/class/net'.format(self.sys_path))
        return [self._get_interface_info(name)
                for name in iface_names
                if self._is_device(name)]

    def get_cpus(self):
        model = None
        freq = None
        with open('/proc/cpuinfo') as f:
            lines = f.read()
            for line in lines.split('\n'):
                if model and freq:
                    break
                if not model and line.startswith('model name'):
                    model = line.split(':')[1].strip()
                if not freq and line.startswith('cpu MHz'):
                    freq = line.split(':')[1].strip()

        return CPU(model, freq, psutil.cpu_count())

    def get_memory(self):
        # psutil returns a long, force it to an int
        return Memory(int(psutil.phymem_usage().total))

    def list_block_devices(self):
        report = utils.execute('blockdev', '--report',
                               check_exit_code=[0])[0]
        lines = report.split('\n')
        lines = [line.split() for line in lines if line != '']
        startsec_idx = lines[0].index('StartSec')
        device_idx = lines[0].index('Device')
        size_idx = lines[0].index('Size')
        # If a device doesn't start at sector 0, assume it is a partition
        return [BlockDevice(line[device_idx],
                            int(line[size_idx]))
                for line
                in lines[1:] if int(line[startsec_idx]) == 0]

    def get_os_install_device(self):
        # Find the first device larger than 4GB, assume it is the OS disk
        # TODO(russellhaering): This isn't a valid assumption in all cases,
        #                       is there a more reasonable default behavior?
        block_devices = self.list_block_devices()
        block_devices.sort(key=lambda device: device.size)
        for device in block_devices:
            if device.size >= (4 * pow(1024, 3)):
                return device.name


def _compare_extensions(ext1, ext2):
    mgr1 = ext1.obj
    mgr2 = ext2.obj
    return mgr1.evaluate_hardware_support() - mgr2.evaluate_hardware_support()


def get_manager():
    global _global_manager

    if not _global_manager:
        LOG = log.getLogger()
        extension_manager = stevedore.ExtensionManager(
            namespace='ironic_python_agent.hardware_managers',
            invoke_on_load=True)

        # There will always be at least one extension available (the
        # GenericHardwareManager).
        if six.PY2:
            preferred_extension = sorted(
                    extension_manager,
                    _compare_extensions)[0]
        else:
            preferred_extension = sorted(
                    extension_manager,
                    key=functools.cmp_to_key(_compare_extensions))[0]

        preferred_manager = preferred_extension.obj

        if preferred_manager.evaluate_hardware_support() <= 0:
            raise RuntimeError('No suitable HardwareManager could be found')

        LOG.info('selected hardware manager {0}'.format(
                 preferred_extension.entry_point_target))

        _global_manager = preferred_manager

    return _global_manager

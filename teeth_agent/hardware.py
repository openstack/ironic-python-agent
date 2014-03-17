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
import collections
import os
import subprocess

import stevedore
import structlog

from teeth_agent import encoding

_global_manager = None


class HardwareSupport(object):
    """These are just guidelines to suggest values that might be returned by
    calls to `evaluate_hardware_support`. No HardwareManager in mainline
    teeth-agent will ever offer a value greater than `MAINLINE`. Service
    Providers should feel free to return values greater than SERVICE_PROVIDER
    to distinguish between additional levels of support.
    """
    NONE = 0
    GENERIC = 1
    MAINLINE = 2
    SERVICE_PROVIDER = 3


class HardwareType(object):
    MAC_ADDRESS = 'mac_address'


class HardwareInfo(encoding.Serializable):
    def __init__(self, type, id):
        self.type = type
        self.id = id

    def serialize(self):
        return collections.OrderedDict([
            ('type', self.type),
            ('id', self.id),
        ])


class BlockDevice(object):
    def __init__(self, name, size, start_sector):
        self.name = name
        self.size = size
        self.start_sector = start_sector


class NetworkInterface(object):
    def __init__(self, name, mac_addr):
        self.name = name
        self.mac_address = mac_addr
        # TODO(russellhaering): Pull these from LLDP
        self.switch_port_descr = None
        self.switch_chassis_descr = None


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
        hardware_info = []
        for interface in self.list_network_interfaces():
            hardware_info.append(HardwareInfo(HardwareType.MAC_ADDRESS,
                                              interface.mac_address))
        return hardware_info


class GenericHardwareManager(HardwareManager):
    def __init__(self):
        self.sys_path = '/sys'

        if os.path.isdir('/mnt/sys'):
            self.sys_path = '/mnt/sys'

    def evaluate_hardware_support(cls):
        return HardwareSupport.GENERIC

    def _get_interface_info(self, interface_name):
        addr_path = '{}/class/net/{}/address'.format(self.sys_path,
                                                     interface_name)
        addr_file = open(addr_path, 'r')
        mac_addr = addr_file.read().strip()
        return NetworkInterface(interface_name, mac_addr)

    def _is_device(self, interface_name):
        device_path = '{}/class/net/{}/device'.format(self.sys_path,
                                                      interface_name)
        return os.path.exists(device_path)

    def list_network_interfaces(self):
        iface_names = os.listdir('{}/class/net'.format(self.sys_path))
        return [self._get_interface_info(name)
                for name in iface_names
                if self._is_device(name)]

    def _cmd(self, command):
        process = subprocess.Popen(command, stdout=subprocess.PIPE)
        return process.communicate()

    def _list_block_devices(self):
        report = self._cmd(['blockdev', '--report'])[0]
        lines = report.split('\n')
        lines = [line.split() for line in lines if line is not '']
        startsec_idx = lines[0].index('StartSec')
        device_idx = lines[0].index('Device')
        size_idx = lines[0].index('Size')
        return [BlockDevice(line[device_idx],
                            int(line[size_idx]),
                            int(line[startsec_idx]))
                for line
                in lines[1:]]

    def get_os_install_device(self):
        # Assume anything with a start sector other than 0, is a partition
        block_devices = [device for device in self._list_block_devices()
                         if device.start_sector == 0]

        # Find the first device larger than 4GB, assume it is the OS disk
        # TODO(russellhaering): This isn't a valid assumption in all cases,
        #                       is there a more reasonable default behavior?
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
        log = structlog.get_logger()
        extension_manager = stevedore.ExtensionManager(
            namespace='teeth_agent.hardware_managers',
            invoke_on_load=True)

        # There will always be at least one extension available (the
        # GenericHardwareManager).
        preferred_extension = sorted(extension_manager, _compare_extensions)[0]
        preferred_manager = preferred_extension.obj

        if preferred_manager.evaluate_hardware_support() <= 0:
            raise RuntimeError('No suitable HardwareManager could be found')

        log.info('selected hardware manager',
                 manager_name=preferred_extension.entry_point_target)

        _global_manager = preferred_manager

    return _global_manager

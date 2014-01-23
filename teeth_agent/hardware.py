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

import stevedore
import structlog

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


class HardwareManager(object):
    @abc.abstractmethod
    def evaluate_hardware_support(cls):
        pass

    @abc.abstractmethod
    def get_primary_mac_address(self):
        pass

    @abc.abstractmethod
    def get_os_install_device(self):
        pass


class GenericHardwareManager(HardwareManager):
    def evaluate_hardware_support(cls):
        return HardwareSupport.GENERIC

    def get_primary_mac_address(self):
        return open('/sys/class/net/eth0/address', 'r').read().strip('\n')

    def get_os_install_device(self):
        return '/dev/sda'


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

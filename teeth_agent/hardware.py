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

from stevedore import enabled
import structlog


class BaseHardwareManager(object):
    @staticmethod
    def supports_hardware():
        return True

    def get_primary_mac_address(self):
        return open('/sys/class/net/eth0/address', 'r').read().strip('\n')


def extension_supports_hardware(extension):
    return extension.plugin.supports_hardware()


def load_hardware_manager():
    # The idea here is that there is an inheritance tree of Hardware Managers.
    # For example:
    #
    #                         BaseHardwareManager
    #                           /              \
    #             SmallServerManager       LargeServerManager
    #                /    \                    /   \
    #              v1      v2                v1     v2
    #
    # In this hierarchy, any manager can claim to support the hardware, but any
    # of its subclasses may supercede its claim. In cases where two managers
    # with no ancestral relationship both claim to support the hardware, the
    # result is undefined.
    #
    # NOTE(russellhaering): I don't know if this is actually a good idea, I
    #                       just want to be able to have a base manager which
    #                       tries to supply reasonable defaults, and be able to
    #                       override it simply by installing an appropriate
    #                       plugin.
    log = structlog.get_logger()
    selected_plugin = BaseHardwareManager
    extension_manager = enabled.EnabledExtensionManager(
        namespace='teeth_agent.hardware_managers',
        check_func=extension_supports_hardware)

    for extension in extension_manager:
        plugin = extension.plugin
        log.info('found qualified hardware manager',
                 manager_name=plugin.__name__)
        if issubclass(plugin, selected_plugin):
            selected_plugin = plugin

    log.info('selected hardware manager',
             manager_name=selected_plugin.__name__)

    return selected_plugin()

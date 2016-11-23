# Copyright (C) 2016 Intel Corporation
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

import os

from oslo_config import cfg
from oslo_log import log

from ironic_python_agent import hardware
from ironic_python_agent import utils

LOG = log.getLogger()
CONF = cfg.CONF


def _detect_cna_card():
    addr_path = '/sys/class/net'
    for net_dev in os.listdir(addr_path):
        try:
            link_command = 'readlink {}/{}/device/driver/module'.format(
                addr_path, net_dev)
            out = utils.execute(link_command.split())
            if not out or out[1]:
                continue
        except OSError:
            continue
        driver_name = os.path.basename(out[0].strip())
        if driver_name == 'i40e':
            return True
    return False


def _disable_embedded_lldp_agent_in_cna_card():
    addr_path = '/sys/kernel/debug/i40e'
    failed_dirs = []
    if os.path.exists(addr_path):
        addr_dirs = os.listdir(addr_path)
    else:
        LOG.warning('Driver i40e was not loaded properly')
        return
    for inner_dir in addr_dirs:
        try:
            command_path = '{}/{}/command'.format(addr_path, inner_dir)
            with open(command_path, 'w') as command_file:
                command_file.write('lldp stop')
        except (OSError, IOError):
            failed_dirs.append(inner_dir)
            continue
    if failed_dirs:
        LOG.warning('Failed to disable the embedded LLDP on Intel CNA network '
                    'card. Addresses of failed pci devices: {}'
                    .format(str(failed_dirs).strip('[]')))


class IntelCnaHardwareManager(hardware.GenericHardwareManager):
    HARDWARE_MANAGER_NAME = 'IntelCnaHardwareManager'
    HARDWARE_MANAGER_VERSION = '1.0'

    def evaluate_hardware_support(self):
        if _detect_cna_card():
            LOG.debug('Found Intel CNA network card')
            return hardware.HardwareSupport.MAINLINE
        else:
            LOG.debug('No Intel CNA network card found')
            return hardware.HardwareSupport.NONE

    def collect_lldp_data(self, interface_names):
        """Collect and convert LLDP info from the node.

        On Intel CNA cards, in order to make LLDP info collecting possible,
        the embedded LLDP agent, which runs inside that card, needs to be
        turned off. Then we can give the control back to the super class.

        :param interface_names: list of names of node's interfaces.
        :return: a dict, containing the lldp data from every interface.
        """

        _disable_embedded_lldp_agent_in_cna_card()
        return super(IntelCnaHardwareManager, self).collect_lldp_data(
            interface_names)

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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log

from ironic_python_agent import hardware
from ironic_python_agent import utils

LOG = log.getLogger()
CONF = cfg.CONF


def _detect_cna_card():
    addr_path = '/sys/class/net'
    for net_dev in os.listdir(addr_path):
        link_path = '{}/{}/device/driver/module'.format(addr_path, net_dev)
        try:
            out = utils.execute('readlink', '-v', link_path)
        except OSError as e:
            LOG.warning('Something went wrong when readlink for '
                        'interface %(device)s. Error: %(error)s',
                        {'device': net_dev, 'error': e})
            continue
        except processutils.ProcessExecutionError as e:
            LOG.debug('Get driver for interface %(device)s failed. '
                      'Error: %(error)s',
                      {'device': net_dev, 'error': e})
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
        warning_msg = ('Failed to disable the embedded LLDP on Intel '
                       'CNA network card. Addresses of failed pci '
                       'devices: %s', str(failed_dirs).strip('[]'))
        LOG.warning(warning_msg)


class IntelCnaHardwareManager(hardware.HardwareManager):
    HARDWARE_MANAGER_NAME = 'IntelCnaHardwareManager'
    HARDWARE_MANAGER_VERSION = '1.0'

    def evaluate_hardware_support(self):
        if _detect_cna_card():
            LOG.debug('Found Intel CNA network card')
            # On Intel CNA cards, in order to make LLDP info collecting
            # possible, the embedded LLDP agent, which runs inside that
            # card, needs to be turned off.
            if CONF.collect_lldp:
                LOG.info('Disable CNA network card embedded lldp agent now')
                _disable_embedded_lldp_agent_in_cna_card()
            return hardware.HardwareSupport.MAINLINE
        else:
            LOG.debug('No Intel CNA network card found')
            return hardware.HardwareSupport.NONE

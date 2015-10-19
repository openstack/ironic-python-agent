# -*- coding: utf-8 -*-
#
# Copyright 2015 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


from oslo_concurrency import processutils
from oslo_log import log
from oslo_utils import uuidutils

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import utils

LOG = log.getLogger(__name__)


def _execute(cmd, error_msg, **kwargs):
    try:
        stdout, stderr = utils.execute(*cmd, **kwargs)
    except processutils.ProcessExecutionError as e:
        LOG.error(error_msg)
        raise errors.ISCSIError(error_msg, e.exit_code, e.stdout, e.stderr)


def _wait_for_iscsi_daemon(attempts=10):
    """Wait for the ISCSI daemon to start."""
    # here, iscsi daemon is considered not running in case
    # tgtadm is not able to talk to tgtd to show iscsi targets
    cmd = ['tgtadm', '--lld', 'iscsi', '--mode', 'target', '--op', 'show']
    _execute(cmd, "ISCSI daemon didn't initialize", attempts=attempts)


def _start_iscsi_daemon(iqn, device):
    """Start a ISCSI target for the device."""
    LOG.debug("Starting ISCSI target on device %{device}", {'device': device})

    # Start ISCSI Target daemon
    _execute(['tgtd'], "Unable to start the ISCSI daemon")

    _wait_for_iscsi_daemon()

    cmd = ['tgtadm', '--lld', 'iscsi', '--mode', 'target', '--op',
           'new', '--tid', '1', '--targetname', iqn]
    _execute(cmd, "Error when adding a new target for iqn %s" % iqn)

    cmd = ['tgtadm', '--lld', 'iscsi', '--mode', 'logicalunit', '--op',
           'new', '--tid', '1', '--lun', '1', '--backing-store', device]
    _execute(cmd, "Error when adding a new logical unit for iqn %s" % iqn)

    cmd = ['tgtadm', '--lld', 'iscsi', '--mode', 'target', '--op',
           'bind', '--tid', '1', '--initiator-address', 'ALL']
    _execute(cmd, "Error when enabling the target to accept the specific "
                  "initiators for iqn %s" % iqn)


class ISCSIExtension(base.BaseAgentExtension):

    @base.sync_command('start_iscsi_target')
    def start_iscsi_target(self, iqn=None):
        """Expose the disk as an ISCSI target."""
        # If iqn is not given, generate one
        if iqn is None:
            iqn = 'iqn-' + uuidutils.generate_uuid()

        device = hardware.dispatch_to_managers('get_os_install_device')
        _start_iscsi_daemon(iqn, device)
        return {"iscsi_target_iqn": iqn}

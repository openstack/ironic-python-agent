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


from ironic_lib import disk_utils
from oslo_concurrency import processutils
from oslo_log import log
from oslo_utils import uuidutils
try:
    import rtslib_fb
except ImportError:
    import rtslib as rtslib_fb

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent import netutils
from ironic_python_agent import utils

LOG = log.getLogger(__name__)
DEFAULT_ISCSI_PORTAL_PORT = 3260


def _execute(cmd, error_msg, **kwargs):
    try:
        stdout, stderr = utils.execute(*cmd, **kwargs)
    except (processutils.ProcessExecutionError, OSError) as e:
        LOG.error(error_msg)
        raise errors.ISCSICommandError(error_msg, e.exit_code,
                                       e.stdout, e.stderr)


def _wait_for_tgtd(attempts=10):
    """Wait for the ISCSI daemon to start."""
    # here, iscsi daemon is considered not running in case
    # tgtadm is not able to talk to tgtd to show iscsi targets
    cmd = ['tgtadm', '--lld', 'iscsi', '--mode', 'target', '--op', 'show']
    _execute(cmd, "ISCSI daemon didn't initialize", attempts=attempts)


def _start_tgtd(iqn, portal_port, device):
    """Start a ISCSI target for the device."""
    # Start ISCSI Target daemon
    _execute(['tgtd'], "Unable to start the ISCSI daemon")

    _wait_for_tgtd()

    # tgt service will create default portal on default port 3260.
    # so no need to create again if input portal_port == 3260.
    if portal_port != DEFAULT_ISCSI_PORTAL_PORT:
        cmd = ['tgtadm', '--lld', 'iscsi', '--mode', 'portal', '--op',
               'new', '--param', 'portal=0.0.0.0:' + str(portal_port)]
        _execute(cmd, "Error when adding a new portal with portal_port %d"
                 % portal_port)

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


def _start_lio(iqn, portal_port, device):
    try:
        storage = rtslib_fb.BlockStorageObject(name=iqn, dev=device)
        target = rtslib_fb.Target(rtslib_fb.FabricModule('iscsi'), iqn,
                                  mode='create')
        tpg = rtslib_fb.TPG(target, mode='create')
        # disable all authentication
        tpg.set_attribute('authentication', '0')
        tpg.set_attribute('demo_mode_write_protect', '0')
        tpg.set_attribute('generate_node_acls', '1')
        # lun=1 is hardcoded in ironic
        rtslib_fb.LUN(tpg, storage_object=storage, lun=1)
        tpg.enable = 1
    except rtslib_fb.utils.RTSLibError as exc:
        msg = 'Failed to create a target: {}'.format(exc)
        raise errors.ISCSIError(msg)

    try:
        # bind to the default port on all interfaces
        listen_ip = netutils.wrap_ipv6(netutils.get_wildcard_address())
        rtslib_fb.NetworkPortal(tpg, listen_ip, portal_port)
    except rtslib_fb.utils.RTSLibError as exc:
        msg = 'Failed to publish a target: {}'.format(exc)
        raise errors.ISCSIError(msg)


def clean_up(device):
    """Clean up iSCSI for a given device."""
    try:
        rts_root = rtslib_fb.RTSRoot()
    except (EnvironmentError, rtslib_fb.RTSLibError) as exc:
        LOG.info('Linux-IO is not available, not cleaning up. Error: %s.', exc)
        return

    storage = None
    for x in rts_root.storage_objects:
        if x.udev_path == device:
            storage = x
            break

    if storage is None:
        LOG.info('Device %(dev)s not found in the current iSCSI mounts '
                 '%(mounts)s.',
                 {'dev': device,
                  'mounts': [x.udev_path for x in rts_root.storage_objects]})
        return
    else:
        LOG.info('Deleting iSCSI target %(target)s for device %(dev)s.',
                 {'target': storage.name, 'dev': device})

    try:
        for x in rts_root.targets:
            if x.wwn == storage.name:
                x.delete()
                break

        storage.delete()
    except rtslib_fb.utils.RTSLibError as exc:
        msg = ('Failed to delete iSCSI target %(target)s for device %(dev)s: '
               '%(error)s') % {'target': storage.name,
                               'dev': device,
                               'error': exc}
        raise errors.ISCSIError(msg)


class ISCSIExtension(base.BaseAgentExtension):
    @base.sync_command('start_iscsi_target')
    def start_iscsi_target(self, iqn=None, wipe_disk_metadata=False,
                           portal_port=None):
        """Expose the disk as an ISCSI target.

        :param wipe_disk_metadata: if the disk metadata should be wiped out
                                   before the disk is exposed.
        """
        # If iqn is not given, generate one
        if iqn is None:
            iqn = 'iqn.2008-10.org.openstack:%s' % uuidutils.generate_uuid()

        device = hardware.dispatch_to_managers('get_os_install_device')

        if wipe_disk_metadata:
            disk_utils.destroy_disk_metadata(
                device,
                self.agent.get_node_uuid())

        LOG.debug("Starting ISCSI target with iqn %(iqn)s on device "
                  "%(device)s", {'iqn': iqn, 'device': device})

        try:
            rts_root = rtslib_fb.RTSRoot()
        except (EnvironmentError, rtslib_fb.RTSLibError) as exc:
            LOG.warning('Linux-IO is not available, falling back to TGT. '
                        'Error: %s.', exc)
            rts_root = None

        if portal_port is None:
            portal_port = DEFAULT_ISCSI_PORTAL_PORT

        if rts_root is None:
            _start_tgtd(iqn, portal_port, device)
        else:
            _start_lio(iqn, portal_port, device)
            LOG.debug('Linux-IO configuration: %s', rts_root.dump())

        LOG.info('Created iSCSI target with iqn %(iqn)s, portal port %(port)d,'
                 ' on device %(dev)s using %(method)s',
                 {'iqn': iqn, 'port': portal_port, 'dev': device,
                  'method': 'tgtd' if rts_root is None else 'linux-io'})

        return {"iscsi_target_iqn": iqn}

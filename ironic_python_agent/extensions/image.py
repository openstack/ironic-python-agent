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

import os
import shlex
import shutil
import tempfile

from oslo_concurrency import processutils

from ironic_python_agent import errors
from ironic_python_agent.extensions import base
from ironic_python_agent import hardware
from ironic_python_agent.openstack.common import log
from ironic_python_agent import utils

LOG = log.getLogger(__name__)


BIND_MOUNTS = ('/dev', '/sys', '/proc')


def _get_root_partition(device, root_uuid):
    """Find the root partition of a given device."""
    LOG.debug("Find the root partition %(uuid)s on device %(dev)s",
              {'dev': device, 'uuid': root_uuid})

    try:
        # Try to tell the kernel to re-read the partition table
        try:
            utils.execute('partx', '-u', device, attempts=3,
                          delay_on_retry=True)
        except processutils.ProcessExecutionError:
            LOG.warning("Couldn't re-read the partition table "
                        "on device %s" % device)

        report = utils.execute('lsblk', '-PbioKNAME,UUID,TYPE', device)[0]
        for line in report.split('\n'):
            part = {}
            # Split into KEY=VAL pairs
            vals = shlex.split(line)
            for key, val in (v.split('=', 1) for v in vals):
                part[key] = val.strip()
            # Ignore non partition
            if part.get('TYPE') != 'part':
                continue

            if part.get('UUID') == root_uuid:
                LOG.debug("Root partition %(uuid)s found on device "
                          "%(dev)s", {'uuid': root_uuid, 'dev': device})
                return '/dev/' + part.get('KNAME')
        else:
            error_msg = ("No root partition with UUID %(uuid)s found on "
                         "device %(dev)s" % {'uuid': root_uuid, 'dev': device})
            LOG.error(error_msg)
            raise errors.DeviceNotFound(error_msg)
    except processutils.ProcessExecutionError as e:
        error_msg = ('Finding the root partition with UUID %(uuid)s on '
                     'device %(dev)s failed with %(err)s' %
                     {'uuid': root_uuid, 'dev': device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)


def _install_grub2(device, root_uuid):
    """Install GRUB2 bootloader on a given device."""
    LOG.debug("Installing GRUB2 bootloader on device %s", device)
    root_partition = _get_root_partition(device, root_uuid)

    try:
        # Mount the partition and binds
        path = tempfile.mkdtemp()
        utils.execute('mount', root_partition, path)
        for fs in BIND_MOUNTS:
            utils.execute('mount', '-o', 'bind', fs, path + fs)

        binary_name = "grub"
        if os.path.exists(os.path.join(path, 'usr/sbin/grub2-install')):
            binary_name = "grub2"

        # Install grub
        utils.execute('chroot %(path)s /bin/bash -c '
                      '"/usr/sbin/%(bin)s-install %(dev)s"' %
                      {'path': path, 'bin': binary_name, 'dev': device},
                      shell=True)

        # Generate the grub configuration file
        utils.execute('chroot %(path)s /bin/bash -c '
                      '"/usr/sbin/%(bin)s-mkconfig -o '
                      '/boot/%(bin)s/grub.cfg"' %
                      {'path': path, 'bin': binary_name}, shell=True)

        LOG.info("GRUB2 successfully installed on %s", device)

    except processutils.ProcessExecutionError as e:
        error_msg = ('Installing GRUB2 boot loader to device %(dev)s '
                     'failed with %(err)s. Attempted 3 times.' %
                     {'dev': device, 'err': e})
        LOG.error(error_msg)
        raise errors.CommandExecutionError(error_msg)

    finally:
        umount_warn_msg = "Unable to umount %(path)s. Error: %(error)s"
        # Umount binds and partition
        umount_binds_fail = False
        for fs in BIND_MOUNTS:
            try:
                utils.execute('umount', path + fs, attempts=3,
                              delay_on_retry=True)
            except processutils.ProcessExecutionError as e:
                umount_binds_fail = True
                LOG.warning(umount_warn_msg, {'path': path + fs, 'error': e})

        # If umounting the binds succeed then we can try to delete it
        if not umount_binds_fail:
            try:
                utils.execute('umount', path, attempts=3, delay_on_retry=True)
            except processutils.ProcessExecutionError as e:
                LOG.warning(umount_warn_msg, {'path': path, 'error': e})
            else:
                # After everything is umounted we can then remove the
                # temporary directory
                shutil.rmtree(path)


class ImageExtension(base.BaseAgentExtension):

    @base.sync_command('install_bootloader')
    def install_bootloader(self, root_uuid):
        """Install the GRUB2 bootloader on the image.

        :param root_uuid: The UUID of the root partition.
        :raises: CommandExecutionError if the installation of the
                 bootloader fails.
        :raises: DeviceNotFound if the root partition is not found.

        """
        device = hardware.dispatch_to_managers('get_os_install_device')
        _install_grub2(device, root_uuid)

# Copyright 2014 Red Hat, Inc.
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

"""
Code for creating partitions on a disk.

Imported from ironic-lib's disk_utils as of the following commit:
https://opendev.org/openstack/ironic-lib/commit/42fa5d63861ba0f04b9a4f67212173d7013a1332
"""

import logging

from ironic_lib.common.i18n import _
from ironic_lib import exception
from ironic_lib import utils
from oslo_config import cfg

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class DiskPartitioner(object):

    def __init__(self, device, disk_label='msdos', alignment='optimal'):
        """A convenient wrapper around the parted tool.

        :param device: The device path.
        :param disk_label: The type of the partition table. Valid types are:
                           "bsd", "dvh", "gpt", "loop", "mac", "msdos",
                           "pc98", or "sun".
        :param alignment: Set alignment for newly created partitions.
                          Valid types are: none, cylinder, minimal and
                          optimal.

        """
        self._device = device
        self._disk_label = disk_label
        self._alignment = alignment
        self._partitions = []

    def _exec(self, *args):
        # NOTE(lucasagomes): utils.execute() is already a wrapper on top
        #                    of processutils.execute() which raises specific
        #                    exceptions. It also logs any failure so we don't
        #                    need to log it again here.
        utils.execute('parted', '-a', self._alignment, '-s', self._device,
                      '--', 'unit', 'MiB', *args, use_standard_locale=True)

    def add_partition(self, size, part_type='primary', fs_type='',
                      boot_flag=None, extra_flags=None):
        """Add a partition.

        :param size: The size of the partition in MiB.
        :param part_type: The type of the partition. Valid values are:
                          primary, logical, or extended.
        :param fs_type: The filesystem type. Valid types are: ext2, fat32,
                        fat16, HFS, linux-swap, NTFS, reiserfs, ufs.
                        If blank (''), it will create a Linux native
                        partition (83).
        :param boot_flag: Boot flag that needs to be configured on the
                          partition. Ignored if None. It can take values
                          'bios_grub', 'boot'.
        :param extra_flags: List of flags to set on the partition. Ignored
                            if None.
        :returns: The partition number.

        """
        self._partitions.append({'size': size,
                                 'type': part_type,
                                 'fs_type': fs_type,
                                 'boot_flag': boot_flag,
                                 'extra_flags': extra_flags})
        return len(self._partitions)

    def get_partitions(self):
        """Get the partitioning layout.

        :returns: An iterator with the partition number and the
                  partition layout.

        """
        return enumerate(self._partitions, 1)

    def commit(self):
        """Write to the disk."""
        LOG.debug("Committing partitions to disk.")
        cmd_args = ['mklabel', self._disk_label]
        # NOTE(lucasagomes): Lead in with 1MiB to allow room for the
        #                    partition table itself.
        start = 1
        for num, part in self.get_partitions():
            end = start + part['size']
            cmd_args.extend(['mkpart', part['type'], part['fs_type'],
                             str(start), str(end)])
            if part['boot_flag']:
                cmd_args.extend(['set', str(num), part['boot_flag'], 'on'])
            if part['extra_flags']:
                for flag in part['extra_flags']:
                    cmd_args.extend(['set', str(num), flag, 'on'])
            start = end

        self._exec(*cmd_args)

        try:
            from ironic_python_agent import disk_utils  # circular dependency
            disk_utils.wait_for_disk_to_become_available(self._device)
        except exception.IronicException as e:
            raise exception.InstanceDeployFailure(
                _('Disk partitioning failed on device %(device)s. '
                  'Error: %(error)s')
                % {'device': self._device, 'error': e})

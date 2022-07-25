==========================
Built-in hardware managers
==========================

GenericHardwareManager
======================

This is the default hardware manager for ironic-python-agent. It provides
support for :ref:`hardware-inventory` and the default deploy and clean steps.

Deploy steps
------------

``deploy.write_image(node, ports, image_info, configdrive=None)``
    A deploy step backing the ``write_image`` deploy step of the
    :ironic-doc:`direct deploy interface
    <admin/interfaces/deploy.html#direct-deploy>`.
    Should not be used explicitly, but can be overridden to provide a custom
    way of writing an image.
``deploy.erase_devices_metadata(node, ports)``
    Erases partition tables from all recognized disk devices. Can be used with
    software RAID since it requires empty holder disks.
``raid.apply_configuration(node, ports, raid_config, delete_existing=True)``
    Apply a software RAID configuration. It belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.

Injecting files
~~~~~~~~~~~~~~~

``deploy.inject_files(node, ports, files, verify_ca=True)``

This optional deploy step (introduced in the Wallaby release series) allows
injecting arbitrary files into the node. The list of files is built from the
optional ``inject_files`` property of the node concatenated with the explicit
``files`` argument. Each item in the list is a dictionary with the following
fields:

``path`` (required)
    An absolute path to the file on the target partition. All missing
    directories will be created.
``partition``
    Specifies the target partition in one of 3 ways:

    * A number is treated as a partition index (starting with 1) on the root
      device.
    * A path is treated as a block device path (e.g. ``/dev/sda1`` or
      ``/dev/disk/by-partlabel/<something>``.
    * If missing, the agent will try to find a partition containing the first
      component of the ``path`` on the root device. E.g. for
      ``/etc/sysctl.d/my.conf``, look for a partition containing ``/etc``.
``deleted``
    If ``True``, the file is deleted, not created.
    Incompatible with ``content``.
``content``
    Data to write. Incompatible with ``deleted``. Can take two forms:

    * A URL of the content. Can use Python-style formatting to build a node
      specific URL, e.g. ``http://server/{node[uuid]}/{ports[0][address]}``.
    * Base64 encoded binary contents.
``mode``, ``owner``, ``group``
    Numeric mode, owner ID and group ID of the file.
``dirmode``
    Numeric mode of the leaf directory if it has to be created.

This deploy step is disabled by default and can be enabled via a deploy
template or via the ``ipa-inject-files-priority`` kernel parameter.

Known limitations:

* Names are not supported for ``owner`` and ``group``.
* LVM is not supported.

Clean steps
-----------

``deploy.burnin_cpu``
    Stress-test the CPUs of a node via stress-ng for a configurable
    amount of time. Disabled by default.
``deploy.burnin_disk``
    Stress-test the disks of a node via fio. Disabled by default.
``deploy.burnin_memory``
    Stress-test the memory of a node via stress-ng for a configurable
    amount of time. Disabled by default.
``deploy.burnin_network``
    Stress-test the network of a pair of nodes via fio for a configurable
    amount of time. Disabled by default.
``deploy.erase_devices``
    Securely erases all information from all recognized disk devices.
    Relatively fast when secure ATA erase is available, otherwise can take
    hours, especially on a virtual environment. Enabled by default.
``deploy.erase_devices_metadata``
    Erases partition tables from all recognized disk devices. Can be used as
    an alternative to the much longer ``erase_devices`` step.
``deploy.erase_pstore``
    Erases entries from pstore, the kernel's oops/panic logger. Disabled by
    default. Can be enabled via priority overrides.
``raid.create_configuration``
    Create a RAID configuration. This step belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.
``raid.delete_configuration``
    Delete the RAID configuration. This step belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.

Cleaning safeguards
-------------------

The stock hardware manager contains a number of safeguards to prevent
unsafe conditions from occuring.

Devices Skip List
~~~~~~~~~~~~~~~~~

A list of devices that Ironic does not touch during the cleaning process
can be specified in the node properties field under
``skip_block_devices``. This should be a list of dictionaries
containing hints to identify the drives.

Shared Disk Cluster Filesystems
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Commonly used shared disk cluster filesystems, when detected, causes cleaning
processes on stock hardware manager methods to abort prior to destroying the
contents on the disk.

These filesystems include IBM General Parallel File System (GPFS),
VmWare Virtual Machine File System (VMFS), and Red Hat Global File System
(GFS2).

For information on troubleshooting, and disabling this check,
see :doc:`/admin/troubleshooting`.

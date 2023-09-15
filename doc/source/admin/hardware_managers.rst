==========================
Built-in hardware managers
==========================

GenericHardwareManager
======================

This is the default hardware manager for ironic-python-agent. It provides
support for :ref:`hardware-inventory` and the default deploy, clean,
and service steps.

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

Service steps
-------------

Service steps can be invoked by an operator of a baremetal node, to modify
or perform some intermediate action outside the realm of normal use of a
deployed bare metal instance. This is similar in form of interaction to
cleaning, and ultimately some cleaning and deployment steps *are* available
to be used.

``deploy.burnin_cpu``
    Stress-test the CPUs of a node via stress-ng for a configurable
    amount of time.
``deploy.burnin_memory``
    Stress-test the memory of a node via stress-ng for a configurable
    amount of time.
``deploy.burnin_network``
    Stress-test the network of a pair of nodes via fio for a configurable
    amount of time.
``raid.create_configuration``
    Create a RAID configuration. This step belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.
``raid.apply_configuration(node, ports, raid_config, delete_existing=True)``
    Apply a software RAID configuration. It belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.
``raid.delete_configuration``
    Delete the RAID configuration. This step belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.
``deploy.write_image(node, ports, image_info, configdrive=None)``
    A step backing the ``write_image`` deploy step of the
    :ironic-doc:`direct deploy interface
    <admin/interfaces/deploy.html#direct-deploy>`.
    Should not be used explicitly, but can be overridden to provide a custom
    way of writing an image.
``deploy.inject_files(node, ports, files, verify_ca=True)``
    A step to inject files into a system. Specifically this step is documented
    earlier in this documentation.

.. NOTE::
   The Ironic Developers chose to limit the items available for service steps
   such that the risk of data distruction is generally minimized.
   That being said, it could be reasonable to reconfigure RAID devices through
   local hardware managers *or* to write the base OS image as part of a
   service operation. As such, caution should be taken, and if additional data
   erasure steps are needed you may want to consider moving a node through
   cleaning to remove the workload. Otherwise, if you have a use case, please
   feel free to reach out to the Ironic Developers so we can understand and
   enable your use case.

Cleaning safeguards
-------------------

The stock hardware manager contains a number of safeguards to prevent
unsafe conditions from occuring.

Devices Skip List
~~~~~~~~~~~~~~~~~

A list of devices that Ironic does not touch during the cleaning and deployment
process can be specified in the node properties field under
``skip_block_devices``. This should be a list of dictionaries
containing hints to identify the drives. For example::

    'skip_block_devices': [{'name': '/dev/vda', 'vendor': '0x1af4'}]


To prevent software RAID devices from being deleted, put their volume name
(defined in the ``target_raid_config``) to the list.

Note: one dictionary with one value for each of the logical disks.
For example::

    'skip_block_devices': [{'volume_name': 'large'}, {'volume_name': 'temp'}]


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

==========================
Custom hardware managers
==========================

MellanoxDeviceHardwareManager
=============================

This is a custom hardware manager for ironic-python-agent. It provides
support for Nvidia/Mellanox NICs.

* You can get the binraies firmware for all Nvidia/Mellanox NICs from here `Nvidia firmware downloads <https://network.nvidia.com/support/firmware/firmware-downloads/>`_

* And you can get the deviceID from here `Nvidia/Mellanox NICs list <https://pci-ids.ucw.cz/read/PC/15b3>`_

* Also you can check here `MFT decumentation <https://docs.nvidia.com/networking/display/MFTv4240/Using+mlxconfig>`_ for some supported parameters

Clean steps
-----------

``update_nvidia_nic_firmware_image(node, ports, images)``

A clean step used to update Nvidia/Mellanox NICs firmware images from the
required parameter ``images`` list. it's disabled by default.
Each image in the list is a dictionary with the following fields:

``url`` (required)
    The url of the firmware image (file://, http://).
``checksum`` (required)
    checksum of the provided image.
``checksumType`` (required)
    checksum type, it could be (md5/sha512/sha256).
``componentFlavor`` (required)
    The PSID of the nic.
``version`` (required)
    version of the firmware image , it must be the same as in the image file.

``update_nvidia_nic_firmware_settings(node, ports, settings)``

A clean step used to update Nvidia/Mellanox NICs firmware settings from the
required parameter ``settings`` list. it's disabled by default.
Each settings in the list is a dictionary with the following fields:

``deviceID`` (required)
    The ID of the NIC
``globalConfig``
    The global configuration for NIC
``function0Config``
    The per-function configuration of the first port of the NIC
``function1Config``
    The per-function configuration of the second port of the NIC

Service steps
-------------

The Clean steps supported by the MellanoxDeviceHardwareManager are also
available as Service steps if an infrastructure operator wishes to apply
new firmware for a running machine.

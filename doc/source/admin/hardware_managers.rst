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

Clean steps
-----------

``deploy.erase_devices``
    Securely erases all information from all recognized disk devices.
    Relatively fast when secure ATA erase is available, otherwise can take
    hours, especially on a virtual environment. Enabled by default.
``deploy.erase_devices_metadata``
    Erases partition tables from all recognized disk devices. Can be used as
    an alternative to the much longer ``erase_devices`` step.
``raid.create_configuration``
    Create a RAID configuration. This step belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.
``raid.delete_configuration``
    Delete the RAID configuration. This step belongs to the ``raid`` interface
    and must be used through the :ironic-doc:`ironic RAID feature
    <admin/raid.html>`.

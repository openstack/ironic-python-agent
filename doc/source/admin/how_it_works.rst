How it works
============

Integration with Ironic
-----------------------

Compatible Deploy Drivers
~~~~~~~~~~~~~~~~~~~~~~~~~

Agent Deploy Driver
<<<<<<<<<<<<<<<<<<<
IPA works with the agent Deploy driver in Ironic to provision nodes. Starting
with ironic-python-agent running on a ramdisk on an unprovisioned node,
Ironic makes API calls to ironic-python-agent to provision the machine. This
allows for greater control and flexibility of the entire deployment process.

PXE Deploy Driver
<<<<<<<<<<<<<<<<<
IPA may also be used with the original Ironic pxe driver as of the Kilo
OpenStack Ironic release.

Configuring Deploy Drivers
<<<<<<<<<<<<<<<<<<<<<<<<<<
For information on how to install and configure Ironic drivers, including
drivers for IPA, see the Ironic drivers documentation [0]_.

Lookup
~~~~~~
On startup, the agent performs a lookup in Ironic to determine its node UUID
by sending a hardware profile to the Ironic lookup endpoint:
``/v1/lookup``.

Heartbeat
~~~~~~~~~
After successfully looking up its node, the agent heartbeats via
``/v1/heartbeat/{node_ident}`` every N seconds, where
N is the Ironic conductor's agent.heartbeat_timeout value multiplied by a
number between .3 and .6.

For example, if your conductor's ironic.conf contains::

  [agent]
  heartbeat_timeout = 60

IPA will heartbeat between every 20 and 36 seconds. This is to ensure jitter
for any agents reconnecting after a network or API disruption.

After the agent heartbeats, the conductor performs any actions needed against
the node, including querying status of an already run command. For example,
initiating in-band cleaning tasks or deploying an image to the node.

Inspection
~~~~~~~~~~
IPA can conduct hardware inspection on start up and post data to the `Ironic
Inspector`_. Edit your default PXE/iPXE configuration or IPA options
baked in the image, and set ``ipa-inspection-callback-url`` to the
full endpoint of Ironic Inspector, for example::

    ipa-inspection-callback-url=http://IP:5050/v1/continue

Make sure your DHCP environment is set to boot IPA by default.

.. _Ironic Inspector: https://docs.openstack.org/ironic-inspector/

Hardware Inventory
------------------
IPA collects various hardware information using its
:doc:`Hardware Managers <../contributor/hardware_managers>`,
and sends it to Ironic on lookup and to Ironic Inspector on Inspection_.

The exact format of the inventory depends on the hardware manager used.
Here is the basic format expected to be provided by all hardware managers.
The inventory is a dictionary (JSON object), containing at least the following
fields:

``cpu``
    CPU information: ``model_name``, ``frequency``, ``count``,
    ``architecture`` and ``flags``.

``memory``
    RAM information: ``total`` (total size in bytes), ``physical_mb``
    (physically installed memory size in MiB, optional).

    .. note::
        The difference is that the latter includes the memory region reserved
        by the kernel and is always slightly bigger. It also matches what
        the Nova flavor would contain for this node and thus is used by the
        inspection process instead of ``total``.

``bmc_address``
    IP address of the node's BMC (aka IPMI address), optional.

``disks``
    list of disk block devices with fields: ``name``, ``model``,
    ``size`` (in bytes), ``rotational`` (boolean), ``wwn``, ``serial``,
    ``vendor``, ``wwn_with_extension``, ``wwn_vendor_extension``, ``hctl``.

``interfaces``
    list of network interfaces with fields: ``name``, ``mac_address``,
    ``ipv4_address``, ``lldp``, ``vendor``, ``product``, and optionally
    ``biosdevname``(BIOS given NIC name). If configuration option
    ``collect_lldp`` is set to True the ``lldp`` field will be populated
    by a list of type-length-value(TLV) fields retrieved using the
    Link Layer Discovery Protocol (LLDP).

``system_vendor``
    system vendor information from SMBIOS as reported by ``dmidecode``:
    ``product_name``, ``serial_number`` and ``manufacturer``.

``boot``
    boot information with fields: ``current_boot_mode`` (boot mode used for
    the current boot - BIOS or UEFI) and ``pxe_interface`` (interface used
    for PXE booting, if any).

References
==========
.. [0] Enabling Drivers - https://docs.openstack.org/ironic/latest/admin/drivers/ipa.html

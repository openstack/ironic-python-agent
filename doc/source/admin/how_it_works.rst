How it works
============

Integration with Ironic
-----------------------
For information on how to install and configure Ironic drivers, including
drivers for IPA, see the :ironic-doc:`Ironic drivers documentation
</admin/drivers/ipa.html>`.

Lookup
~~~~~~
On startup, the agent performs a lookup in Ironic to determine its node UUID
by sending a hardware profile to the Ironic lookup endpoint:
`/v1/lookup
<https://docs.openstack.org/api-ref/baremetal/?expanded=agent-lookup-detail#agent-lookup>`_.

Heartbeat
~~~~~~~~~
After successfully looking up its node, the agent heartbeats via
`/v1/heartbeat/{node_ident}
<https://docs.openstack.org/api-ref/baremetal/?expanded=agent-heartbeat-detail#agent-heartbeat>`_
every N seconds, where N is the Ironic conductor's ``agent.heartbeat_timeout``
value multiplied by a number between .3 and .6.

For example, if your conductor's ironic.conf contains::

  [agent]
  heartbeat_timeout = 60

IPA will heartbeat between every 20 and 36 seconds. This is to ensure jitter
for any agents reconnecting after a network or API disruption.

After the agent heartbeats, the conductor performs any actions needed against
the node, including querying status of an already run command. For example,
initiating in-band cleaning tasks or deploying an image to the node.

Inspection
----------
IPA can conduct hardware inspection on start up and post data to the
:ironic-inspector-doc:`Ironic Inspector <>` via the `/v1/continue
<https://docs.openstack.org/api-ref/baremetal-introspection/?expanded=ramdisk-callback-detail#ramdisk-callback>`_
endpoint.

Edit your default PXE/iPXE configuration or IPA options baked in the image, and
set ``ipa-inspection-callback-url`` to the full endpoint of Ironic Inspector,
for example::

    ipa-inspection-callback-url=http://IP:5050/v1/continue

Make sure your DHCP environment is set to boot IPA by default.

For the cases where the infrastructure operator and cloud user are the same,
an additional tool exists that can be installed alongside the agent inside
a running instance. This is the ``ironic-collect-introspection-data``
command which allows for a node in ``ACTIVE`` state to publish updated
introspection data to ironic-inspector. This ability requires ironic-inspector
to be configured with ``[processing]permit_active_introspection`` set to
``True``. For example::

    ironic-collect-introspection-data --inspection_callback_url http://IP:5050/v1/continue

Alternatively, this command may also be used with multicast DNS
functionality to identify the Ironic Inspector service endpoint. For example::

    ironic-collect-introspection-data --inspection_callback_url mdns

An additional daemon mode may be useful for some operators who wish to receive
regular updates, in the form of the ``[DEFAULT]introspection_daemon`` boolean
configuration option.
For example::

    ironic-collect-introspection-data --inspection_callback_url mdns --introspection_daemon

The above command will attempt to connect to introspection and will then enter
a loop to publish every 300 seconds. This can be tuned with the
``[DEFAULT]introspection_daemon_post_interval`` configuration option.

Inspection Data
~~~~~~~~~~~~~~~
As part of the inspection process, data is collected on the machine and sent
back to :ironic-inspector-doc:`Ironic Inspector <>` for storage. It can be
accessed via the `introspection data API
<https://docs.openstack.org/api-ref/baremetal-introspection/?expanded=get-introspection-data-detail#get-introspection-data>`_.

The exact format of the data depends on the enabled *collectors*, which can be
configured using the ``ipa-inspection-collectors`` kernel parameter. Each
collector appends information to the resulting JSON object. The in-tree
collectors are:

``default``
    The default enabled collectors. Collects the following keys:

    * ``inventory`` - `Hardware Inventory`_.
    * ``root_disk`` - The default root device for this machine, which will be
      used for deployment if root device hints are not provided.
    * ``configuration`` - Inspection configuration, an object with two keys:

      * ``collectors`` - List of enabled collectors.
      * ``managers`` - List of enabled :ref:`Hardware Managers`: items with
        keys ``name`` and ``version``.

    * ``boot_interface`` - Deprecated, use the
      ``inventory.boot.pxe_interface`` field.

``logs``
    Collect system logs. To yield useful results it must always go last in the
    list of collectors. Provides one key:

    * ``logs`` - base64 encoded tarball with various logs.

``pci-devices``
    Collects the list of PCI devices. Provides one key:

    * ``pci_devices`` - list of objects with keys ``vendor_id`` and
      ``product_id``.

``extra-hardware``
    Collects a vast list of facts about the systems, using the hardware_
    library, which is a required dependency for this collector. Adds one key:

    * ``data`` - raw data from the ``hardware-collect`` utility. Is a list of
      lists with 4 items each. It is recommended to use this collector together
      with the ``extra_hardware`` processing hook on the Ironic Inspector
      side to convert it to a nested dictionary in the ``extra`` key.

      If ``ipa-inspection-benchmarks`` is set, the corresponding benchmarks are
      executed and their result is also provided.

``dmi-decode``
    Collects information from ``dmidecode``. Provides one key:

    * ``dmi`` DMI information in three keys: ``bios``, ``cpu`` and ``memory``.

      .. TODO(dtantsur): figure out details

``numa-topology``
    Collects NUMA_ topology information. Provides one key:

    * ``numa_topology`` with three nested keys:

      * ``ram`` - list of objects with keys ``numa_node`` (node ID) and
        ``size_kb``.
      * ``cpus`` - list of objects with keys ``cpu`` (CPU ID), ``numa_node``
        (node ID) and ``thread_siblings`` (list of sibling threads).
      * ``nics`` - list of objects with keys ``name`` (NIC name) and
        ``numa_node`` (node ID).

``lldp``
    Collects information about the network connectivity using LLDP_. Provides
    one key:

    * ``lldp_raw`` - mapping of interface names to lists of raw
      type-length-value (TLV) records.

.. _hardware: https://pypi.org/project/hardware/
.. _NUMA: https://en.wikipedia.org/wiki/Non-uniform_memory_access
.. _LLDP: https://en.wikipedia.org/wiki/Link_Layer_Discovery_Protocol

.. _hardware-inventory:

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
    IPv4 address of the node's BMC (aka IPMI v4 address), optional.

``bmc_v6address``
    IPv6 address of the node's BMC (aka IPMI v6 address), optional.

``disks``
    list of disk block devices with fields: ``name``, ``model``,
    ``size`` (in bytes), ``rotational`` (boolean), ``wwn``, ``serial``,
    ``uuid``, ``vendor``, ``wwn_with_extension``, ``wwn_vendor_extension``,
    ``hctl`` and ``by_path`` (the full disk path, in the form
    ``/dev/disk/by-path/<rest-of-path>``).

``interfaces``
    list of network interfaces with fields: ``name``, ``mac_address``,
    ``ipv4_address``, ``lldp``, ``vendor``, ``product``, and optionally
    ``biosdevname`` (BIOS given NIC name) and ``speed_mbps`` (maximum supported
    speed).

    .. note::
       For backward compatibility, interfaces may contain ``lldp`` fields.
       They are deprecated, consumers should rely on the ``lldp`` inspection
       collector instead.

``system_vendor``
    system vendor information from SMBIOS as reported by ``dmidecode``:
    ``product_name``, ``serial_number`` and ``manufacturer``, as well as
    a ``firmware`` structure with fields ``vendor``, ``version`` and
    ``build_date``.

``boot``
    boot information with fields: ``current_boot_mode`` (boot mode used for
    the current boot - BIOS or UEFI) and ``pxe_interface`` (interface used
    for PXE booting, if any).

``hostname``
    hostname for the system

    .. note::
        This is most likely to be set by the DHCP server. Could be localhost
        if the DHCP server does not set it.

Image Checksums
---------------

As part of the process of downloading images to be written to disk as part of
image deployment, a series of fields are utilized to determine if the
image which has been downloaded matches what the user stated as the expected
image checksum utilizing the ``instance_info/image_checksum`` value.

OpenStack, as a whole, has replaced the "legacy" ``checksum`` field with
``os_hash_value`` and ``os_hash_algo`` fields, which allows for an image
checksum and value to be asserted. An advantage of this is a variety of
algorithms are available, if a user/operator is so-inclined.

For the purposes of Ironic, we continue to support the pass-through checksum
field as we support the checksum being retrieved via a URL.

We also support determining the checksum by length.

The field can be utilized to designate:

* A URL to retreive a checksum from.
* MD5 (Disabled by default, see ``[DEFAULT]md5_enabled`` in the agent
  configuration file.)
* SHA-2 based SHA256
* SHA-2 based SHA512

SHA-3 based checksums are not supported for auto-determination as they can
have a variable length checksum result. At of when this documentation was
added, SHA-2 based checksum algorithms have not been withdrawn from from
approval. If you need to force use of SHA-3 based checksums, you *must*
utilize the ``os_hash_algo`` setting along with the ``os_hash_value``
setting.

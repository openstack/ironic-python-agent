===============================
Installing Ironic Python Agent!
===============================

Image Builders
==============
Unlike most other python software, you must build an IPA ramdisk image before
use. This is because it's not installed in an operating system, but instead is
run from within a ramdisk.

CoreOS
------
One way to build a ramdisk image for IPA is with the CoreOS image [0]_.
Prebuilt copies of the CoreOS image, suitable for pxe, are available on
`tarballs.openstack.org <http://tarballs.openstack.org/ironic-python-agent/coreos/files/>`__.

Build process
~~~~~~~~~~~~~
On a high level, the build steps are as follows:

1) A docker build is performed using the ``Dockerfile`` in the root of the
   ironic-python-agent project.
2) The resulting docker image is exported to a filesystem image.
3) The filesystem image, along with a cloud-config.yml [1]_, are embedded into
   the CoreOS PXE image at /usr/share/oem/.
4) On boot, the ironic-python-agent filesystem image is extracted and run
   inside a systemd-nspawn container. /usr/share/oem is mounted into this
   container as /mnt.

Customizing the image
~~~~~~~~~~~~~~~~~~~~~
There are several methods you can use to customize the IPA ramdisk:

* Embed SSH keys by putting an authorized_keys file in /usr/share/oem/
* Add your own hardware managers by modifying the Dockerfile to install
  additional python packages.
* Modify the cloud-config.yml [1]_ to perform additional tasks at boot time.

diskimage-builder
-----------------
Another way to build a ramdisk image for IPA is by using diskimage-builder
[2]_. The ironic-agent diskimage-builder element builds the IPA ramdisk, which
installs all the required packages and configures services as needed.

tinyipa
-------

Ironic Python Agent repo also provides a set of scripts to build a
Tiny Core Linux-based deployment kernel and ramdisk (code name ``tinyipa``)
under ``imagebuild/tinyipa`` folder.

`Tiny Core Linux <http://tinycorelinux.net/>`_
is a very minimalistic Linux distribution.
Due to its small size and decreased RAM requirements
it is mostly suitable for usage in CI with virtualized hardware,
and is already used on a number of gate jobs in projects under
OpenStack Baremetal program.
On the other hand, due to its generally newer Linux kernel it also known to
work on real hardware if the kernel supports all necessary components
installed.

Please refer to ``imagebuild/tinyipa/README.rst`` for more information and
build instructions.

ISO Images
----------

Additionally, the IPA ramdisk can be packaged inside of an ISO for use with
supported virtual media drivers. Simply use the ``iso-image-create`` utility
packaged with IPA, pass it an initrd and kernel. e.g.::

  ./iso-image-create -o /path/to/output.iso -i /path/to/ipa.initrd -k /path/to/ipa.kernel

This is a generic tool that can be used to combine any initrd and kernel into
a suitable ISO for booting, and so should work against any IPA ramdisk created
-- both DIB and CoreOS.

IPA Flags
=========

You can pass a variety of flags to IPA on start up to change its behavior.
If you're using the CoreOS image, you can modify the
ironic-python-agent.service unit in cloud-config.yaml [3]_.

* ``--standalone``: This disables the initial lookup and heartbeats to Ironic.
  Lookup sends some information to Ironic in order to determine Ironic's node
  UUID for the node. Heartbeat sends periodic pings to Ironic to tell Ironic
  the node is still running. These heartbeats also trigger parts of the deploy
  and cleaning cycles. This flag is useful for debugging IPA without an Ironic
  installation.

* ``--debug``: Enables debug logging.


IPA and SSL
===========

During its operation IPA makes HTTP requests to a number of other services,
currently including

- ironic for lookup/heartbeats
- ironic-inspector to publish results of introspection
- HTTP image storage to fetch the user image to be written to the node's disk
  (Object storage service or other service storing user images
  when ironic is running in a standalone mode)

When these services are configured to require SSL-encrypted connections,
IPA can be configured to either properly use such secure connections or
ignore verifying such SSL connections.

Configuration mostly happens in the IPA config file
(default is ``/etc/ironic_python_agent/ironic_python_agent.conf``)
or command line arguments passed to ``ironic-python-agent``,
and it is possible to provide some options via kernel command line arguments
instead.

Available options in the ``[DEFAULT]`` config file section are:

insecure
  Whether to verify server SSL certificates.
  When not specified explicitly, defaults to the value of ``ipa-insecure``
  kernel command line argument (converted to boolean).
  The default for this kernel command line argument is taken to be ``False``.
  Overriding it to ``True`` by adding ``ipa-insecure=1`` to the value of
  ``[pxe]pxe_append_params`` in ironic configuration file will allow running
  the same IPA-based deploy ramdisk in a CI-like environment when services
  are using secure HTTPS endpoints with self-signed certificates without
  adding a custom CA file to the deploy ramdisk (see below).

cafile
  Path to the PEM encoded Certificate Authority file.
  When not specified, available system-wide list of CAs will be used to
  verify server certificates.
  Thus in order to use IPA with HTTPS endpoints of other services in
  a secure fashion (with ``insecure`` option being ``False``, see above),
  operators should either ensure that certificates of those services
  are verifiable by root CAs present in the deploy ramdisk,
  or add a custom CA file to the ramdisk and set this IPA option to point
  to this file at ramdisk build time.

certfile
  Path to PEM encoded client certificate cert file.
  This option must be used when services are configured to require client
  certificates on SSL-secured connections.
  This cert file must be added to the deploy ramdisk and path
  to it specified for IPA via this option at ramdisk build time.
  This option has an effect only when the ``keyfile`` option is also set.

keyfile
  Path to PEM encoded client certificate key file.
  This option must be used when services are configured to require client
  certificates on SSL-secured connections.
  This key file must be added to the deploy ramdisk and path
  to it specified for IPA via this option at ramdisk build time.
  This option has an effect only when the ``certfile`` option is also set.

Currently a single set of cafile/certfile/keyfile options is used for all
HTTP requests to the other services.

Securing IPA's HTTP server itself with SSL is not yet supported in default
ramdisk builds.

Hardware Managers
=================

What is a HardwareManager?
--------------------------
Hardware managers are how IPA supports multiple different hardware platforms
in the same agent. Any action performed on hardware can be overridden by
deploying your own hardware manager.

Why build a custom HardwareManager?
-----------------------------------
Custom hardware managers allow you to include hardware-specific tools, files
and cleaning steps in the Ironic Python Agent. For example, you could include a
BIOS flashing utility and BIOS file in a custom ramdisk. Your custom
hardware manager could expose a cleaning step that calls the flashing utility
and flashes the packaged BIOS version (or even download it from a tested web
server).

How can I build a custom HardwareManager?
-----------------------------------------
Operators wishing to build their own hardware managers should reference
the documentation available at `Hardware Managers`_.

.. _Hardware Managers: https://docs.openstack.org/ironic/latest/contributor/hardware_managers.html

References
==========
.. [0] CoreOS PXE Images - https://coreos.com/docs/running-coreos/bare-metal/booting-with-pxe/
.. [1] CoreOS Cloud Init - https://coreos.com/docs/cluster-management/setup/cloudinit-cloud-config/
.. [2] DIB Element for IPA - https://docs.openstack.org/diskimage-builder/latest/elements/ironic-agent/README.html
.. [3] cloud-config.yaml - https://git.openstack.org/cgit/openstack/ironic-python-agent/tree/imagebuild/coreos/oem/cloud-config.yml

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`

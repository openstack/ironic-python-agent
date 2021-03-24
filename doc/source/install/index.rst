==============================
Installing Ironic Python Agent
==============================

Image Builders
==============

Unlike most other python software, you must build or download an IPA ramdisk
image before use. This is because it's not installed in an operating system,
but instead is run from within a ramdisk.

Two kinds of images are published on every commit from every branch of IPA:

* DIB_ images are suitable for production usage and can be downloaded from
  https://tarballs.openstack.org/ironic-python-agent/dib/files/.
* TinyIPA_ images are suitable for CI and testing environments and can be
  downloaded from
  https://tarballs.openstack.org/ironic-python-agent/tinyipa/files/.

If you need to build your own image, use the tools from the
ironic-python-agent-builder_ project.

IPA Flags
=========

You can pass a variety of flags to IPA on start up to change its behavior.

* ``--debug``: Enables debug logging.


IPA and TLS
===========

Client Configuration
--------------------

During its operation IPA makes HTTP requests to a number of other services,
currently including

- ironic for lookup/heartbeats
- ironic-inspector to publish results of introspection
- HTTP image storage to fetch the user image to be written to the node's disk
  (Object storage service or other service storing user images
  when ironic is running in a standalone mode)

When these services are configured to require TLS-encrypted connections,
IPA can be configured to either properly use such secure connections or
ignore verifying such TLS connections.

Configuration mostly happens in the IPA config file
(default is ``/etc/ironic_python_agent/ironic_python_agent.conf``, can also
be any file placed in ``/etc/ironic-python-agent.d``)
or command line arguments passed to ``ironic-python-agent``,
and it is possible to provide some options via kernel command line arguments
instead.

Available options in the ``[DEFAULT]`` config file section are:

insecure
  Whether to verify server TLS certificates.
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

Server Configuration
--------------------

Starting with the Victoria release, the API provided by ironic-python-agent can
also be secured via TLS. There are two options to do that:

Automatic TLS
   This option is enabled by default if no other options are enabled. If ironic
   supports API version 1.68, a new self-signed TLS certificate will be
   generated in runtime and sent to ironic on heartbeat.

   No special configuration is required on the ironic side.
Manual TLS
   If you need to provide your own TLS certificate, you can configure it when
   building an image. Set the following options in the ironic-python-agent
   configuration file:

   .. code-block:: ini

    [DEFAULT]
    listen_tls = True
    advertise_protocol = https
    # Disable automatic TLS.
    enable_auto_tls = False

    [ssl]
    # Certificate and private key file paths (on the ramdisk).
    cert_file = /path/to/certificate
    # The private key must not be password-protected!
    key_file = /path/to/private/key
    # Optionally, authenticate connecting clients (i.e. ironic conductors).
    #ca_file = /path/to/ca

   If using DIB to build the ramdisk, use the ironic-python-agent-tls_ element
   to automate these steps.

   On the ironic side you have two options:

   * If the certificate can pass host validation, i.e. contains the correct host
     name or IP address of the agent, add its path to each node with::

        baremetal node set <node> --driver-info agent_verify_ca=/path/to/ca/or/certificate

   * Usually, the IP address of the agent is not known in advance, so you need
     to disable host validation instead::

        baremetal node set <node> --driver-info agent_verify_ca=False

.. _ironic-python-agent-tls: https://opendev.org/openstack/ironic-python-agent-builder/src/branch/master/dib/ironic-python-agent-tls

Hardware Managers
=================

Hardware managers are how IPA supports multiple different hardware platforms
in the same agent. Any action performed on hardware can be overridden by
deploying your own hardware manager.

Custom hardware managers allow you to include hardware-specific tools, files
and cleaning steps in the Ironic Python Agent. For example, you could include a
BIOS flashing utility and BIOS file in a custom ramdisk. Your custom
hardware manager could expose a cleaning step that calls the flashing utility
and flashes the packaged BIOS version (or even download it from a tested web
server).

Operators wishing to build their own hardware managers should reference
the documentation available at :doc:`Hardware Managers
</contributor/hardware_managers>`.

.. _ironic-python-agent-builder: https://docs.openstack.org/ironic-python-agent-builder
.. _DIB: https://docs.openstack.org/ironic-python-agent-builder/latest/admin/dib.html
.. _TinyIPA: https://docs.openstack.org/ironic-python-agent-builder/latest/admin/tinyipa.html

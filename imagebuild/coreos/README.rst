ironic-python-agent CoreOS Image builder.
=========================================

Builds a CoreOS image suitable for running the ironic-python-agent on a
server.

Requirements
============

Must be run from a linux machine with a working docker installation and
python-pip

Run the following locally or from a virtualenv to install the python
requirements

::

    pip install -r requirements.txt

Booting the agent with this image
=================================

PXE
---

The image is typically booted via PXE. Here's an example ipxe
configuration (replace my-web-server with the IP/hostname of the http
server hosting your image):

::

    #!ipxe

    dhcp
    kernel http://my-web-server/coreos_production_pxe.vmlinuz
    initrd http://my-web-server/coreos_production_pxe_image-oem.cpio.gz
    boot

You can either embed a configuration file into the image, or set
configuration options via the kernel command line. The only value most
people will need is:

-  ``ipa-api-url=http://ironic-api-server:6385``

But any config value supported in the agent can be given to the agent
via the kernel command line, which allows the use of the same agent
image across environments because it contains no state.

Virtual Media
-------------

Openstack Ironic supports booting IPA via virtual media in the form of
an ISO image. Please see Ironic documentation for details on running in
this configuration.

Getting the agent
=================

Download
--------

If you don't want to build your own image, you can download a copy of
ironic-python-agent ramdisk and kernel, built using CoreOS, at:
http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe.vmlinuz
and
http://tarballs.openstack.org/ironic-python-agent/coreos/files/coreos_production_pxe_image-oem.cpio.gz

Build instructions
------------------

To create a docker repository and embed it into a CoreOS pxe image:

::

    make

To just create the docker repository in oem/container.tar.gz:

::

    make docker

To embed the oem/ directory into a CoreOS pxe image:

Note: In order to have the ability to ssh into the created image, you
need to pass ssh keys in via the kernel command line for CoreOS, or
create oem/authorized\_keys with the keys you need added before building
the image.

::

    make coreos

To create a CoreOS ISO image to boot with virtual media:

::

    make iso

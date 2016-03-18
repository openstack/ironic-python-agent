=============================
Tiny Core Ironic Python Agent
=============================

.. WARNING::
  This is experimental! Build tested on Ubuntu Server 14.04, Debian Jessie and Fedora 21

Build script requirements
-------------------------
For the main build script:

* wget
* pip
* unzip
* sudo
* awk
* mksquashfs

For building an ISO you'll also need:

* genisoimage

Instructions:
-------------
To create a new ramdisk, run::

  make

or::

  ./build-tinyipa.sh && ./finalise-tinyipa.sh

This will create two new files once completed:

* tinyipa.vmlinuz
* tinyipa.gz

These are your two files to upload to glance for use with Ironic.

Building an ISO from a previous make run:
-----------------------------------------
Once you've built tinyipa it is possible to pack it into an ISO if required. To
create a bootable ISO, run::

  make iso

or::

./build-iso.sh

This will create one new file once completed:

* tinyipa.iso

To build a fresh ramdisk and build an iso from it:
--------------------------------------------------
Run::

  make all

To clean up the whole build environment run:
--------------------------------------------
Run::

  make clean

For cleaning up just the iso or just the ramdisk build::

  make clean_iso

or::

  make clean_tinyipa

Advanced options
----------------

If you want the build script to preinstall everything into the ramdisk,
instead of loading some things at runtime (this results in a slightly bigger
ramdisk), before running make or build-tinyipa.sh run::

  export BUILD_AND_INSTALL_TINYIPA=true

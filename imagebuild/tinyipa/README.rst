=============================
Tiny Core Ironic Python Agent
=============================

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

(De)Optimizing the image
~~~~~~~~~~~~~~~~~~~~~~~~

If you want the build script to preinstall everything into the ramdisk,
instead of loading some things at runtime (this results in a slightly bigger
ramdisk), before running make or build-tinyipa.sh run::

  export BUILD_AND_INSTALL_TINYIPA=true

By default, building TinyIPA will compile most of the Python code to
optimized ``*.pyo`` files, completely remove most of ``*.py`` and ``*.pyc``
files, and run ironic-python-agent with ``PYTHONOPTIMIZE=1``
to save space on the ramdisk.
If instead you want a normal Python experience inside the image,
for example for debugging/hacking on IPA in a running ramdisk,
before running make or build-tinyipa.sh run::

    export PYOPTIMIZE_TINYIPA=false


Enabling SSH access to the ramdisk
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you want to enable SSH access to the image, set ``ENABLE_SSH`` variable in
your shell before building the tinyipa::

  export ENABLE_SSH=true

By default it will use public RSA or DSA keys of the user running the build.
To provide other public SSH key, export path to it in your shell before
building tinyipa as follows::

  export SSH_PUBLIC_KEY=<full-path-to-public-key>


Enabling biosdevname in the ramdisk
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you want to collect BIOS given names of NICs in the inventory, set
``TINYIPA_REQUIRE_BIOSDEVNAME`` variable in your shell before building the
tinyipa::

  export TINYIPA_REQUIRE_BIOSDEVNAME=true

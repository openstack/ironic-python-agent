Example Hardware Managers
=========================

``vendor-device``
-----------------

This example manager is meant to demonstrate good patterns for developing a
device-specific hardware manager, such as for a specific version of NIC or
disk.

Use Cases include:

* Adding device-specific clean-steps, such as to flash firmware or
  verify it's still properly working after being provisioned.
* Implementing erase_device() using a vendor-provided utility for a given
  disk model.

``custom-disk-erase``
---------------------

This example manager is meant to demonstrate good patterns for developing a
hardware manager to perform disk erasure using a custom vendor utility.

Use case:
* Ensuring block devices of a specific model are erased using custom code

``business-logic``
------------------

This example manager is meant to demonstrate how cleaning and the agent can
use the node object and the node itself to enforce business logic and node
consistency.

Use Cases include:

* Quality control on hardware by ensuring no component is beyond its useful
  life.
* Asserting truths about the node; such as number of disks or total RAM.
* Reporting metrics about the node's hardware state.
* Overriding logic of get_os_install_device().
* Inserting additional deploy steps.

Make your own Manager based on these
------------------------------------

To make your own hardware manager based on these examples, copy a relevant
example out of this directory. Modify class names and entrypoints in setup.cfg
to be not-examples.

Since the entrypoints are defined in setup.cfg, simply installing your new
python package alongside IPA in a custom ramdisk should be enough to enable
the new hardware manager.

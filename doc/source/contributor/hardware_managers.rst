.. _Hardware Managers:

Hardware Managers
=================

What is a HardwareManager?
--------------------------
Hardware managers are how IPA supports multiple different hardware platforms
in the same agent. Any action performed on hardware can be overridden by
deploying your own hardware manager.

How are methods executed on HardwareManagers?
---------------------------------------------
Methods that modify hardware are dispatched to each hardware manager in
priority order. When a method is dispatched, if a hardware manager does not
have a method by that name or raises `IncompatibleHardwareMethodError`, IPA
continues on to the next hardware manager. Any hardware manager that returns
a result from the method call is considered a success and its return value
passed on to whatever dispatched the method. If the method is unable to run
successfully on any hardware managers, `HardwareManagerMethodNotFound` is
raised.

Does IPA ship with a HardwareManager?
-------------------------------------
IPA ships with GenericHardwareManager, which implements basic cleaning and
deployment methods compatible with most hardware.

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
Custom HardwareManagers should subclass hardware.HardwareManager or
hardware.GenericHardwareManager. The only required method is
evaluate_hardware_support(), which should return one of the enums
in hardware.HardwareSupport. Hardware support determines which hardware
manager is executed first for a given function (see: "`How are methods
executed on HardwareManagers?`_" for more info). Common methods you
may want to implement are list_hardware_info(), to add additional hardware
the GenericHardwareManager is unable to identify and erase_devices(), to
erase devices in ways other than ATA secure erase or shredding.

Custom HardwareManagers and Cleaning
------------------------------------
One of the reasons to build a custom hardware manager is to expose extra steps
in Ironic Cleaning [1]_. A node will perform a set of cleaning steps any
time the node is deleted by a tenant or moved from MANAGEABLE state to
AVAILABLE state. If the node is using an agent\_\* driver, Ironic will query
IPA for a list of clean steps that should be executed on the node. IPA
will dispatch a call to `get_clean_steps()` on all available hardware managers
and then return the combined list to Ironic.

To expose extra clean steps, the custom hardware manager should have a function
named `get_clean_steps()` which returns a list of dictionaries. The
dictionaries should be in the form::

    {
        // A function on the custom hardware manager
        'step': 'upgrade_firmware',
        // An integer priority. Largest priorities are executed first
        'priority': 10,
        // Should always be the deploy interface
        'interface': 'deploy',
        // Request the node to be rebooted out of band by Ironic when the
        // step completes successfully
        'reboot_requested': False
    }

Then, you should create functions which match each of the `step` keys in
the clean steps you return. The functions will take two parameters: `node`,
a dictionary representation of the Ironic node, and `ports`, a list of
dictionary representations of the Ironic ports attached to `node`.

When a clean step is executed in IPA, the `step` key will be sent to the
hardware managers in hardware support order, using
`hardware.dispatch_to_managers()`. For each hardware manager, if the manager
has a function matching the `step` key, it will be executed. If the function
returns a value (including None), that value is returned to Ironic and no
further managers are called. If the function raises
`IncompatibleHardwareMethodError`, the next manager will be called. If the
function raises any other exception, the command will be considered failed,
the command result's error message will be set to the exception's error
message, and no further managers will be called. An example step::

    def upgrade_firmware(self, node, ports):
        if self._device_exists():
            # Do the upgrade
            return 'upgraded firmware'
        else:
            raise errors.IncompatibleHardwareMethodError()

.. note::

    If two managers return steps with the same `step` key, the priority will
    be set to whichever manager has a higher hardware support level and then
    use the higher priority in the case of a tie.

Versioning
~~~~~~~~~~
Each hardware manager has a name and a version. This version is used during
cleaning to ensure the same version of the agent is used to on a node through
the entire process. If the version changes, cleaning is restarted from the
beginning to ensure consistent cleaning operations and to make
updating the agent in production simpler.

You can set the version of your hardware manager by creating a class variable
named 'HARDWARE_MANAGER_VERSION', which should be a string. The default value
is '1.0'. You should change this version string any time you update your
hardware manager. You can also change the name your hardware manager presents
by creating a class variable called HARDWARE_MANAGER_NAME, which is a string.
The name defaults to the class name. Currently IPA only compares version as a
string; any version change whatsoever will induce cleaning to restart.

Priority
~~~~~~~~
A hardware manager has a single overall priority, which should be based on how
well it supports a given piece of hardware. At load time, IPA executes
`evaluate_hardware_support()` on each hardware manager. This method should
return an int representing hardware manager priority, based on what it detects
about the platform it's running on. Suggested values are included in the
`HardwareSupport` class. Returning a value of 0 aka `HardwareSupport.NONE`,
will prevent the hardware manager from being used. IPA will never ship a
hardware manager with a priority higher than 3, aka
`HardwareSupport.SERVICE_PROVIDER`.

References
==========
.. [1] Ironic Cleaning - https://docs.openstack.org/ironic/latest/admin/cleaning.html

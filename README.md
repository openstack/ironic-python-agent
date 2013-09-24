# teeth-agent

## Protocol

JSON. Line Delimitated. Bi-directional. Most messages contain:

* `version` Message Version - String
* `id` Message ID - String

Commands contain:

* `method` Method - String
* `params` Params - Hash of parameters to Method.

Success Responses contain:

* `id` Original Message ID from Command - String
* `result` Result from Command - Hash

Error Responses contain:

* `id` Original Message ID from Command - String
* `error` Result from Command - Hash, `.msg` contains human readable error.  Other fields might come later.

Fatal Error:

* `fatal_error` - String - Fatal error message;  Connection should be closed.


### Commands

#### All Protocol Implementations.

* `ping`: (All) Params are echo'ed back as results.

#### Agent specific Commands

* `log`: (Agent->Server) Log a structured message from the Agent.
* `status`: (Server->Agent) Uptime, version, and other fields reported.

#### Decommission

* `decom.disk_erase`: (Server->Agent) Erase all attached block devices securely.
* `decom.firmware_secure`: (Server->Agent) Update Firmwares/BIOS versions and settings.
* `decom.qc`: (Server->Agent) Run quality control checks on chassis model. Includes sending specifications of chassis (cpu types, disks, etc)


#### Standbye

* `standbye.cache_images`: (Server->Agent) Cache an set of image UUID on local storage.  Ordered in priority, chassis may only cache a subset depending on local storage.
* `standbye.prepare_image`: (Server->Agent) Prepare a image UUID to be ran.
* `standbye.run_image`: (Server->Agent) Run an image UUID.  Must include Config Drive Settings.  Agent will write config drive, and setup grub.  If the Agent can detect a viable kexec target it will kexec into it, otherwise reboot.






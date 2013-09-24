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
* `task_status`: (Agent->Server) Update status of a task.  Task has a `.state`, which is `running`, `error` or `complete`.  `running` will additionally contain `.eta` and `.percent`, a measure of how much work estimated to remain in seconds and how much work is done.  Once `error` or `complete` is sent, no more updates will be sent.  `error` state includes an additional human readable `.msg` field.


#### Decommission

* `decom.disk_erase`: (Server->Agent) Erase all attached block devices securely.  Returns a Task ID.
* `decom.firmware_secure`: (Server->Agent) Update Firmwares/BIOS versions and settings.  Returns a Task ID.
* `decom.qc`: (Server->Agent) Run quality control checks on chassis model. Includes sending specifications of chassis (cpu types, disks, etc).  Returns a Task ID.


#### Standbye

* `standbye.cache_images`: (Server->Agent) Cache an set of image UUID on local storage.  Ordered in priority, chassis may only cache a subset depending on local storage.  Returns a Task ID.
* `standbye.prepare_image`: (Server->Agent) Prepare a image UUID to be ran. Returns a Task ID.
* `standbye.run_image`: (Server->Agent) Run an image UUID.  Must include Config Drive Settings.  Agent will write config drive, and setup grub.  If the Agent can detect a viable kexec target it will kexec into it, otherwise reboot. Returns a Task ID.






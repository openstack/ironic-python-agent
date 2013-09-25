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
* `task_status`: (Agent->Server) Update status of a task.  Task has an `.task_id` which was previously designated.  Task has a `.state`, which is `running`, `error` or `complete`.  `running` will additionally contain `.eta` and `.percent`, a measure of how much work estimated to remain in seconds and how much work is done.  Once `error` or `complete` is sent, no more updates will be sent.  `error` state includes an additional human readable `.msg` field.


#### Decommission

* `decom.disk_erase`: (Server->Agent) Erase all attached block devices securely. Takes a `task_id`.
* `decom.firmware_secure`: (Server->Agent) Update Firmwares/BIOS versions and settings.  Takes a `task_id`.
* `decom.qc`: (Server->Agent) Run quality control checks on chassis model. Includes sending specifications of chassis (cpu types, disks, etc).  Takes a `task_id`.


#### Standbye

* `standbye.cache_images`: (Server->Agent) Cache an set of image UUID on local storage.  Ordered in priority, chassis may only cache a subset depending on local storage.  Takes a `task_id`.
* `standbye.prepare_image`: (Server->Agent) Prepare a image UUID to be ran. Takes a `task_id`.
* `standbye.run_image`: (Server->Agent) Run an image UUID.  Must include Config Drive Settings.  Agent will write config drive, and setup grub.  If the Agent can detect a viable kexec target it will kexec into it, otherwise reboot. Takes a `task_id`.






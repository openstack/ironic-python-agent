===========
Rescue Mode
===========

Ironic supports putting nodes in rescue mode using hardware types that
support rescue interfaces. A rescue operation can be used to boot nodes
into a rescue ramdisk so that the ``rescue`` user can access the node.
This provides the ability to access the node when normal access is not
possible. For example, if there is a need to perform manual password
reset or data recovery in the event of some failure, a rescue operation
can be used. IPA rescue extension exposes a command ``finalize_rescue``
(that is used by Ironic) to set the password for the ``rescue`` user
when the rescue ramdisk is booted.

finalize_rescue command
=======================

The rescue extension exposes the command ``finalize_rescue``; when
invoked, it triggers rescue mode::

    POST /v1/commands

    {"name": "rescue.finalize_rescue",
     "params": {
        "rescue_password": "p455w0rd"}
    }

``rescue_password`` is a required parameter for this command.

Upon success, it returns following data in response::

    {"command_name": "finalize_rescue",
     "command_params": {
        "rescue_password": "p455w0rd"},
     "command_status": "SUCCEEDED"
     "command_result": null
     "command_error": null
    }

If successful, this synchronous command will:

1. Write the salted and encrypted ``rescue_password`` to
   ``/etc/ipa-rescue-config/ipa-rescue-password`` in the chroot or filesystem
   that ironic-python-agent is running in.

2. Stop the ironic-python-agent process after completing these actions and
   returning the response to the API request.

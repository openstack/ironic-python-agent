.. _troubleshooting:

=========================================
Troubleshooting Ironic-Python-Agent (IPA)
=========================================

This document contains basic trouble shooting information for IPA.

Gaining Access to IPA on a node
===============================
In order to access a running IPA instance a user must be added or enabled on
the image. Below we will cover several ways to do this.

Access via ssh
--------------

diskimage-builder (DIB)
~~~~~~~~~~~~~~~~~~~~~~~
SSH access can be added to DIB built IPA images with the dynamic-login [0]_
or the devuser element [1]_

The dynamic-login element allows the operator to inject a SSH key when the
image boots. Kernel command line parameters are used to do this.

dynamic-login element example:

- Add ``sshkey="ssh-rsa BBA1..."`` to pxe_append_params setting in
  the ``ironic.conf`` file
- Restart the ironic-conductor with the command
  ``service ironic-conductor restart``

devuser element example::

  export DIB_DEV_USER_USERNAME=username
  export DIB_DEV_USER_PWDLESS_SUDO=yes
  export DIB_DEV_USER_AUTHORIZED_KEYS=$HOME/.ssh/id_rsa.pub
  disk-image-create -o /path/to/custom-ipa debian ironic-agent devuser

tinyipa
~~~~~~~

If you want to enable SSH access to the image,
set ``ENABLE_SSH`` variable in your shell to ``true`` before building
the tinyipa image::

  export ENABLE_SSH=true

By default it will use default public RSA (or, if not available, DSA)
key of the user running the build (``~/.ssh/id_{rsa,dsa}.pub``).

To provide other public SSH key, export full path to it in your shell
before building tinyipa as follows::

  export SSH_PUBLIC_KEY=/path/to/other/ssh/public/key

The user to use for access is default Tiny Core Linux user ``tc``.
This user has no password and has password-less ``sudo`` permissions.
Installed SSH server is configured to disable Password authentication.

Access via console
------------------
If you need to use console access, passwords must be enabled there are a
couple ways to enable this depending on how the IPA image was created:

diskimage-builder (DIB)
~~~~~~~~~~~~~~~~~~~~~~~
Users wishing to use password access can be add the dynamic-login [0]_ or the
devuser element [1]_

The dynamic-login element allows the operator to change the root password
dynamically when the image boots. Kernel command line parameters
are used to do this.

dynamic-login element example::

  Generate a ENCRYPTED_PASSWORD with the openssl passwd -1 command
  Add rootpwd="$ENCRYPTED_PASSWORD" value on the pxe_append_params setting in /etc/ironic/ironic.conf
  Restart the ironic-conductor with the command service ironic-conductor restart

Users can also be added to DIB built IPA images with the devuser element [1]_

Example::

  export DIB_DEV_USER_USERNAME=username
  export DIB_DEV_USER_PWDLESS_SUDO=yes
  export DIB_DEV_USER_PASSWORD=PASSWORD
  ironic-python-agent-builder -o /path/to/custom-ipa -e devuser debian

tinyipa
~~~~~~~

The image built with scripts provided in ``tinyipa`` folder
of `Ironic Python Agent Builder <https://opendev.org/openstack/ironic-python-agent-builder>`_
repository by default auto-logins the default
Tiny Core Linux user ``tc`` to the console.
This user has no password and has password-less ``sudo`` permissions.

Set IPA to debug logging
========================
Debug logging can be enabled a several different ways. The easiest way is to
add ``ipa-debug=1`` to the kernel command line. To do this:

- Append ``ipa-debug=1`` to the pxe_append_params setting in the
  ``ironic.conf`` file
- Restart the ironic-conductor with the command
  ``service ironic-conductor restart``

If the system is running and uses systemd then editing the services file
will be required.

- ``systemctl edit ironic-python-agent.service``
- Append ``--debug`` to end of the ExecStart command
- Restart IPA. See the `Manually restart IPA`_ section below.

Where can I find the IPA logs
=============================

Retrieving the IPA logs will differ depending on which base image was used.


* Operating system that do not use ``systemd`` (ie Ubuntu 14.04)

  - logs will be found in the /var/log/ folder.

* Operating system that do use ``systemd`` (ie Fedora, CentOS, RHEL)

  - logs may be viewed with ``sudo journalctl -u ironic-python-agent``

Manually restart IPA
====================

In some cases it is helpful to enable debug mode on a running node.
If the system does not use systemd then IPA can be restarted directly::

  sudo /usr/local/bin/ironic-python-agent [--debug]

If the system uses systemd then systemctl can be used to restart the service::

  sudo systemctl restart ironic-python-agent.service


References
==========
.. [0] `Dynamic-login DIB element`: https://github.com/openstack/diskimage-builder/tree/master/diskimage_builder/elements/dynamic-login
.. [1] `DevUser DIB element`: https://github.com/openstack/diskimage-builder/tree/master/diskimage_builder/elements/devuser

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
CoreOS
~~~~~~
To enable the ``core`` user on pre-built or CoreOS images a ssh public key
will need to added. To do this you will need to:

- Add ``sshkey="ssh-rsa AAAA..."`` to pxe_append_params setting in ironic.conf
  file
- Restart the ironic-conductor with the command
  ``service ironic-conductor restart``
- ``ssh core@<ip-address-of-node>``

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

CoreOS
~~~~~~
CoreOS has support for auto login on the console [4]_. This can be enabled by:

- Adding ``coreos.autologin`` to pxe_append_params setting
  in the ``ironic.conf`` file. See [4]_ for more information on using
  autologin.

If you do not wish to enable auto login users can be added to CoreOS by editing
the cloud-config.yml file and adding the following [2]_::

  users:
    - name: username
      passwd: $6$5s2u6/jR$un0AvWnqilcgaNB3Mkxd5... <example password hash>
      groups:
        - sudo

If using a pre-built image the cloud-config.yml must first be extracted::

  mkdir tmp_folder
  cd tmp_folder
  zcat ../coreos_production_pxe_image-oem-stable-mitaka.cpio | cpio --extract --make-directories

To create a password hash the mkpasswd command can be used::

  mkpasswd --method=SHA-512 --rounds=4096

After adding the user block with your favorite editor recompress the image::

  find . | cpio --create --format='newc' |gzip -c -9 > ../coreos_production_pxe_image-oem-stable-mitaka.cpio.NEW.gz

An alternative to editing the embedded cloud-config.yml [4]_ file is to pass a
new one on the kernel command line by:

- adding ``cloud-config-url=http://example.com/cloud-config.yml``
  to pxe_append_params setting in the ``ironic.conf`` file

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
  disk-image-create -o /path/to/custom-ipa debian ironic-agent devuser

tinyipa
~~~~~~~

The image built with scripts provided in ``imagebuild/tinyipa`` folder
of Ironic Python Agent repository by default auto-logins the default
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

Another method is to edit the cloud-config.yml file.  IPA's instructions on
building a custom image can be found at [3]_.

This essentially boils down to the following steps:

#. ``git clone https://git.openstack.org/openstack/ironic-python-agent``
#. ``cd ironic-python-agent``
#. ``pip install -r ./requirements.txt``
#. If not installed, please install the docker container engine. [5]_
#. ``cd imagebuild/coreos``
#. Edit ``oem/cloud-config.yml`` and add ``--debug`` to the end of the
   ExecStart setting for the ironic-python-agent.service unit.
#. Execute ``make`` to complete the build process.

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

* Operating system that do use ``systemd`` (ie Fedora 22, CoreOS)

  - logs may be viewed with ``sudo journalctl -u ironic-python-agent``

  .. note::
      sudo is not required with the CoreOS images.


Manually restart IPA
====================

In some cases it is helpful to enable debug mode on a running node.
If the system does not use systemd then IPA can be restarted directly::

  sudo /usr/local/bin/ironic-python-agent [--debug]

If the system uses systemd then systemctl can be used to restart the service::

  sudo systemctl restart ironic-python-agent.service


References
==========
.. [0] `Dynamic-login DIB element`: https://github.com/openstack/diskimage-builder/tree/master/elements/dynamic-login
.. [1] `DevUser DIB element`: https://github.com/openstack/diskimage-builder/tree/master/elements/devuser
.. [2] `Add User to CoreOS`: https://coreos.com/os/docs/latest/adding-users.html
.. [3] `IPA image build reference`: https://github.com/openstack/ironic-python-agent/tree/master/imagebuild/coreos/README.rst
.. [4] `Booting CoreOS via PXE`: https://coreos.com/os/docs/latest/booting-with-pxe.html
.. [5] `Install docker engine`: https://docs.docker.com/engine/installation/

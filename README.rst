ironic-python-agent
===================

An agent for controlling and deploying Ironic controlled baremetal nodes.

The ironic-python-agent works with the agent driver in Ironic to provision
the node.  Starting with ironic-python-agent running on a ramdisk on the
unprovisioned node, Ironic makes API calls to ironic-python-agent to provision
the machine.  This allows for greater control and flexibility of the entire
deployment process.

The ironic-python-agent may also be used with the original Ironic pxe drivers
as of the Kilo OpenStack release.


Building the IPA deployment ramdisk
===================================

See `CoreOS Image builder <https://github.com/openstack/ironic-python-agent/tree/master/imagebuild/coreos>`_.


Using IPA with devstack
=======================

This is covered in the `Deploying Ironic with DevStack <http://docs.openstack.org/developer/ironic/dev/dev-quickstart.html#deploying-ironic-with-devstack>`_
section of the Ironic dev-quickstart guide.


Project Resources
=================
Project status, bugs, and blueprints are tracked on Launchpad:

  http://launchpad.net/ironic

Developer documentation can be found here:

  http://docs.openstack.org/developer/ironic-python-agent

Additional resources are linked from the project wiki page:

  https://wiki.openstack.org/wiki/Ironic-python-agent

IRC channel:
    #openstack-ironic

To contribute, start here: `Openstack: How to
contribute <http://docs.openstack.org/infra/manual/developers.html>`_.

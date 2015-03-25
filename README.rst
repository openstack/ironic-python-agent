ironic-python-agent
===================

An agent for controlling and deploying Ironic controlled baremetal nodes.

The ironic-python-agent works with the agent driver in Ironic to provision the node.
Starting with ironic-python-agent running on a ramdisk on the unprovisioned node,
Ironic makes API calls to ironic-python-agent to provision the machine.
This allows for greater control and flexibility of the entire deployment process.

The ironic-python-agent may also be used with the original Ironic pxe drivers as of the
Kilo OpenStack release.


Building the IPA deployment ramdisk
==================================

See `CoreOS Image builder <https://github.com/openstack/ironic-python-agent/tree/master/imagebuild/coreos>`


Using IPA with devstack
=======================

This is covered in the `Deploying Ironic with DevStack <http://docs.openstack.org/developer/ironic/dev/dev-quickstart.html#deploying-ironic-with-devstack>`
section of the Ironic dev-quickstart guide.


Project Resources
=================

IRC channel:
    #openstack-ironic

To contribute, start here: `Openstack: How to
contribute <http://docs.openstack.org/infra/manual/developers.html>`__.

===================
Ironic Python Agent
===================

Team and repository tags
========================

.. image:: https://governance.openstack.org/tc/badges/ironic-python-agent.svg
    :target: https://governance.openstack.org/tc/reference/tags/index.html

Overview
========

*WARNING:* The Ironic-Python-Agent version in this branch is vulnerable to
CVE-2024-44082. Do not run this in production unless using a patched
conductor with ``[conductor]/conductor_always_validate_images`` set to
``True``.

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

For more information see the `Image Builder <https://docs.openstack.org/ironic-python-agent/latest/install/index.html#image-builders>`_ section of the Ironic Python Agent
developer guide.


Using IPA with devstack
=======================

This is covered in the `Deploying Ironic with DevStack <https://docs.openstack.org/ironic/latest/contributor/dev-quickstart.html#deploying-ironic-with-devstack>`_
section of the Ironic dev-quickstart guide.


Project Resources
=================
Project status, features, and bugs are tracked on StoryBoard:

  https://storyboard.openstack.org/#!/project/947

Developer documentation can be found here:

  https://docs.openstack.org/ironic-python-agent/latest/

Release notes for the project are available at:

  https://docs.openstack.org/releasenotes/ironic-python-agent/

Source code repository for the project is located at:

  https://opendev.org/openstack/ironic-python-agent/

IRC channel:
    #openstack-ironic

To contribute, start here: `Openstack: How to
contribute <https://docs.openstack.org/infra/manual/developers.html>`_.

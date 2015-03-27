=============================================
Welcome to Ironic-Python-Agent documentation!
=============================================

Introduction
============

An agent for controlling and deploying Ironic controlled baremetal nodes.

The ironic-python-agent works with the agent driver in Ironic to provision
nodes. Starting with ironic-python-agent running on a ramdisk on the
unprovisioned node, Ironic makes API calls to ironic-python-agent to provision
the machine. This allows for greater control and flexibility of the entire
deployment process.

The ironic-python-agent may also be used with the original Ironic pxe driver
as of the Kilo OpenStack release.

Developer Guide
===============

Generated Developer Documentation
---------------------------------

.. toctree::
  :maxdepth: 0

  api/autoindex

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

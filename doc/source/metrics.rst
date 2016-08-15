.. _metrics:

===============================================
Emitting metrics from Ironic-Python-Agent (IPA)
===============================================

This document describes how to emit metrics from IPA, including timers and
counters in code to directly emitting hardware metrics from a custom
HardwareManager.

Overview
========
IPA uses the metrics implementation from ironic-lib, with a few caveats due
to the dynamic configuration done at lookup time. You cannot cache the metrics
instance as the MetricsLogger returned will change after lookup if configs
different than the default setting have been used. This also means that the
method decorator supported by ironic-lib cannot be used in IPA.

Using a context manager
=======================
Using the context manager is the recommended way for sending metrics that time
or count sections of code. However, given that you cannot cache the
MetricsLogger, you have to explicitly call get_metrics_logger() from
ironic-lib every time. For example::

  from ironic_lib import metrics_utils

  def my_method():
      with metrics_utils.get_metrics_logger(__name__).timer('my_method'):
          return _do_work()

As a note, these metric collectors do work for custom HardwareManagers as
well. However, you may want to metric the portions of a method that determine
compatibility separate from portions of a method that actually do work, in
order to assure the metrics are relevant and useful on all hardware.

Explicitly sending metrics
==========================
A feature that may be particularly helpful for deployers writing custom
HardwareManagers is the ability to explicitly send metrics. For instance,
you could add a cleaning step which would retrieve metrics about a device and
ship them using the provided metrics library. For example::

  from ironic_lib import metrics_utils

  def my_cleaning_step():
      for name, value in _get_smart_data():
          metrics_utils.get_metrics_logger(__name__).send_gauge(name, value)

References
==========
For more information, please read the source of the metrics module in
`ironic-lib <http://git.openstack.org/cgit/openstack/ironic-lib/tree/ironic_lib>`_.

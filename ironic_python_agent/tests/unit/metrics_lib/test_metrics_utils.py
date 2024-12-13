# Copyright 2016 Rackspace Hosting
# All Rights Reserved
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_config import cfg

from ironic_python_agent import errors
from ironic_python_agent.metrics_lib import metrics as metricslib
from ironic_python_agent.metrics_lib import metrics_statsd
from ironic_python_agent.metrics_lib import metrics_utils
from ironic_python_agent.tests.unit import base

CONF = cfg.CONF


class TestGetLogger(base.IronicAgentTest):
    def setUp(self):
        super(TestGetLogger, self).setUp()

    def test_default_backend(self):
        metrics = metrics_utils.get_metrics_logger('foo')
        self.assertIsInstance(metrics, metricslib.NoopMetricLogger)

    def test_statsd_backend(self):
        CONF.set_override('backend', 'statsd', group='metrics')

        metrics = metrics_utils.get_metrics_logger('foo')
        self.assertIsInstance(metrics, metrics_statsd.StatsdMetricLogger)
        CONF.clear_override('backend', group='metrics')

    def test_nonexisting_backend(self):
        self.assertRaises(errors.InvalidMetricConfig,
                          metrics_utils.get_metrics_logger, 'foo', 'test')

    def test_numeric_prefix(self):
        self.assertRaises(errors.InvalidMetricConfig,
                          metrics_utils.get_metrics_logger, 1)

    def test_numeric_list_prefix(self):
        self.assertRaises(errors.InvalidMetricConfig,
                          metrics_utils.get_metrics_logger, (1, 2))

    def test_default_prefix(self):
        metrics = metrics_utils.get_metrics_logger()
        self.assertIsInstance(metrics, metricslib.NoopMetricLogger)
        self.assertEqual(metrics.get_metric_name("bar"), "bar")

    def test_prepend_host_backend(self):
        CONF.set_override('prepend_host', True, group='metrics')
        CONF.set_override('prepend_host_reverse', False, group='metrics')

        metrics = metrics_utils.get_metrics_logger(prefix='foo',
                                                   host="host.example.com")
        self.assertIsInstance(metrics, metricslib.NoopMetricLogger)
        self.assertEqual(metrics.get_metric_name("bar"),
                         "host.example.com.foo.bar")

        CONF.clear_override('prepend_host', group='metrics')
        CONF.clear_override('prepend_host_reverse', group='metrics')

    def test_prepend_global_prefix_host_backend(self):
        CONF.set_override('prepend_host', True, group='metrics')
        CONF.set_override('prepend_host_reverse', False, group='metrics')
        CONF.set_override('global_prefix', 'global_pre', group='metrics')

        metrics = metrics_utils.get_metrics_logger(prefix='foo',
                                                   host="host.example.com")
        self.assertIsInstance(metrics, metricslib.NoopMetricLogger)
        self.assertEqual(metrics.get_metric_name("bar"),
                         "global_pre.host.example.com.foo.bar")

        CONF.clear_override('prepend_host', group='metrics')
        CONF.clear_override('prepend_host_reverse', group='metrics')
        CONF.clear_override('global_prefix', group='metrics')

    def test_prepend_other_delim(self):
        metrics = metrics_utils.get_metrics_logger('foo', delimiter='*')
        self.assertIsInstance(metrics, metricslib.NoopMetricLogger)
        self.assertEqual(metrics.get_metric_name("bar"),
                         "foo*bar")

    def test_prepend_host_reverse_backend(self):
        CONF.set_override('prepend_host', True, group='metrics')
        CONF.set_override('prepend_host_reverse', True, group='metrics')

        metrics = metrics_utils.get_metrics_logger('foo',
                                                   host="host.example.com")
        self.assertIsInstance(metrics, metricslib.NoopMetricLogger)
        self.assertEqual(metrics.get_metric_name("bar"),
                         "com.example.host.foo.bar")

        CONF.clear_override('prepend_host', group='metrics')
        CONF.clear_override('prepend_host_reverse', group='metrics')

import time
from ironic_python_agent.api import app
from ironic_python_agent.extensions import base
from ironic_python_agent import agent
from ironic_python_agent import ironic_api_client
from oslo_log import log
from oslo_config import cfg
from ironic_python_agent import hardware

LOG = log.getLogger(__name__)

class FakeInterfaces:
    def __init__(self):
        self.mac_address = None

class FakeIPA(base.ExecuteCommandMixin):
    def __init__(self, api_url, advertise_address, listen_address,
                 ip_lookup_attempts, ip_lookup_sleep, network_interface,
                 lookup_timeout, lookup_interval, standalone, agent_token,
                 hardware_initialization_delay=0, advertise_protocol='http'):
        self.api_url = api_url
        self.advertise_address = advertise_address
        self.listen_address = listen_address
        self.ip_lookup_attempts = ip_lookup_attempts
        self.ip_lookup_sleep = ip_lookup_sleep
        self.network_interface = network_interface
        self.lookup_timeout = lookup_timeout
        self.lookup_interval = lookup_interval
        self.standalone = standalone
        agent_token = str('0123456789' * 10)
        self.agent_token = agent_token
        self.agent_token_required = cfg.CONF.agent_token_required
        self.hardware_initialization_delay = hardware_initialization_delay
        self.advertise_protocol = advertise_protocol
        self.api_client = ironic_api_client.APIClient(self.api_url)
        self.api = app.Application(self, cfg.CONF)
        # self.api_client = None
        self.heartbeater = agent.IronicPythonAgentHeartbeater(self)
        self.version = "1.0"
        # self.node_uuid = "515171d1-4526-454e-bb26-a3ed99997fe1"
        # self.node_uuid = "7a478010-c971-404f-893f-29a25d83afbc"
        self.node_uuid = "f64006e5-522b-4244-b397-2479e3fa32b4"
        # self.node_uuid = "515171d1-4526-454e-bb26-a3ed99997fe1-fake"
        # self.node_uuid = "27946b59-9e44-4fa7-8e91-f3527a1ef094"
        self.heartbeat_timeout = 200
        self.generated_cert = None

    def get_status(self):
        """Retrieve a serializable status.

        :returns: a :class:`ironic_python_agent.agent.IronicPythonAgent`
                  instance describing the agent's status.
        """
        return agent.IronicPythonAgentStatus(
            started_at=self.started_at,
            version=self.version
        )

    def validate_agent_token(self, token):
        return True

    def process_lookup_data(self, content):
        """Update agent configuration from lookup data."""

        self.node = content['node']
        LOG.info('Lookup succeeded, node UUID is %s',
                 self.node['uuid'])
        # hardware.cache_node(self.node)
        self.heartbeat_timeout = content['config']['heartbeat_timeout']

        # Update config with values from Ironic
        config = content.get('config', {})
        if config.get('metrics'):
            for opt, val in config.items():
                setattr(cfg.CONF.metrics, opt, val)
        if config.get('metrics_statsd'):
            for opt, val in config.items():
                setattr(cfg.CONF.metrics_statsd, opt, val)
        if config.get('agent_token_required'):
            self.agent_token_required = True
        token = config.get('agent_token')
        if token:
            if len(token) >= 32:
                LOG.debug('Agent token recorded as designated by '
                          'the ironic installation.')
                self.agent_token = token
                # set with-in the API client.
                if not self.standalone:
                    self.api_client.agent_token = token
            elif token == '******':
                LOG.warning('The agent token has already been '
                            'retrieved. IPA may not operate as '
                            'intended and the deployment may fail '
                            'depending on settings in the ironic '
                            'deployment.')
                if not self.agent_token and self.agent_token_required:
                    LOG.error('Ironic is signaling that agent tokens '
                              'are required, however we do not have '
                              'a token on file. '
                              'This is likely **FATAL**.')
            else:
                LOG.info('An invalid token was received.')
        if self.agent_token and not self.standalone:
            # Explicitly set the token in our API client before
            # starting heartbeat operations.
            self.api_client.agent_token = self.agent_token

    def run(self):
        """Run the Ironic Python Agent."""
        LOG.info('Starting fake ironic-python-agent version: %s',
                 self.version)
        self.started_at = agent._time()

        if self.hardware_initialization_delay > 0:
            LOG.info('Waiting %d seconds before proceeding',
                     self.hardware_initialization_delay)
            time.sleep(self.hardware_initialization_delay)

        if self.api_url:
            content = self.api_client.lookup_node(
                hardware_info={'interfaces': [FakeInterfaces()]},
                timeout=self.lookup_timeout,
                starting_interval=self.lookup_interval,
                node_uuid=self.get_node_uuid())
            LOG.debug('Received lookup results: %s', content)
            self.process_lookup_data(content)
                # Save the API url in case we need it later.
            hardware.save_api_client(
                self.api_client, self.lookup_timeout,
                self.lookup_interval)

        self.serve_ipa_api()

    def serve_ipa_api(self):
        """Serve the API until an extension terminates it."""
        # cert_file, key_file = self._start_auto_tls()
        self.api.start()
        self.heartbeater.start()
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            LOG.info('Caught keyboard interrupt, exiting')

    def get_node_uuid(self):
        return self.node_uuid

    def set_agent_advertise_addr(self):
        pass

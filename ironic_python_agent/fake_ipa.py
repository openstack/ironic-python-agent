import time
from ironic_python_agent.extensions import base
from ironic_python_agent import agent
from ironic_python_agent import ironic_api_client
from oslo_log import log

LOG = log.getLogger(__name__)

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
        self.agent_token = agent_token
        self.hardware_initialization_delay = hardware_initialization_delay
        self.advertise_protocol = advertise_protocol
        self.api_client = ironic_api_client.APIClient(self.api_url)
        self.heartbeater = agent.IronicPythonAgentHeartbeater(self)
        self.version = "1.0"
        self.node_uuid = "Fake_uuid"

    def get_status(self):
        """Retrieve a serializable status.

        :returns: a :class:`ironic_python_agent.agent.IronicPythonAgent`
                  instance describing the agent's status.
        """
        return agent.IronicPythonAgentStatus(
            started_at=self.started_at,
            version=self.version
        )

    def run(self):
        """Run the Ironic Python Agent."""
        LOG.info('Starting fake ironic-python-agent version: %s',
                 self.version)
        self.started_at = agent._time()

        if self.hardware_initialization_delay > 0:
            LOG.info('Waiting %d seconds before proceeding',
                     self.hardware_initialization_delay)
            time.sleep(self.hardware_initialization_delay)

    def serve_ipa_api(self):
        """Serve the API until an extension terminates it."""
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

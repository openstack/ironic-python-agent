# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from ironic_python_agent import hardware
from ironic_python_agent import utils
from oslo_config import cfg
from oslo_log import log

import yaml

CONF = cfg.CONF
LOG = log.getLogger()


class ContainerHardwareManager(hardware.HardwareManager):
    """Hardware manager for container-based cleanup."""

    HARDWARE_MANAGER_NAME = "ContainerHardwareManager"
    HARDWARE_MANAGER_VERSION = "1"
    ALLOW_ARBITARY_CONTAINERS = CONF.container.allow_arbitrary_containers
    ALLOWED_CONTAINERS = CONF.container.allowed_containers

    def __init__(self):
        """Dynamically create cleanup methods."""
        self.STEPS = self._load_steps_from_yaml(
            CONF.container.container_steps_file)
        LOG.debug("Loaded steps: %s", self.STEPS)
        for step in self.STEPS:
            if not self.ALLOW_ARBITARY_CONTAINERS:
                if step['image'] not in self.ALLOWED_CONTAINERS:
                    LOG.debug(
                        "%s is not registered as ALLOWED_CONTAINERS "
                        "in ironic-python-agent.conf", step['image']
                    )

                    continue
            setattr(self, step["name"], self._create_cleanup_method(step))

    def _load_steps_from_yaml(self, file_path):
        """Load steps from YAML file."""
        try:
            with open(file_path, 'r') as file:
                data = yaml.safe_load(file)
                return data.get('steps', [])
        except Exception as e:
            LOG.debug("Error loading steps from YAML file: %s", e)
            return []

    def evaluate_hardware_support(self):
        """Determine if container runner exists and return support level."""
        try:
            stdout, _ = utils.execute("which", CONF.container.runner)
            if stdout.strip():
                LOG.debug("Found %s, returning MAINLINE",
                          CONF.container.runner)
                return hardware.HardwareSupport.MAINLINE
        except Exception as e:
            LOG.debug("Error checking container runner: %s", str(e))
        LOG.debug("No container runner found, returning NONE")
        return hardware.HardwareSupport.NONE

    def get_clean_steps(self, node, ports):
        """Dynamically generate cleaning steps."""
        steps = []
        for step in self.STEPS:
            steps.append(
                {
                    "step": step["name"],
                    "priority": step["priority"],
                    "interface": step['interface'],
                    "reboot_requested": step['reboot_requested'],
                    "abortable": step["abortable"],
                }
            )
        return steps

    def _create_cleanup_method(self, step):
        """Return a function that runs the container with the given image."""

        def _cleanup(node, ports):
            try:
                utils.execute(
                    CONF.container.runner,
                    "pull",
                    *step.get("pull_options", CONF.container.pull_options),
                    step["image"],
                )
                utils.execute(
                    CONF.container.runner,
                    "run",
                    *step.get("run_options", CONF.container.run_options),
                    step["image"],
                )
            except Exception as e:
                LOG.exception("Error during cleanup: %s", e)
                raise
            return True

        return _cleanup

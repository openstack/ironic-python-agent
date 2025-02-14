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

from ironic_python_agent import errors
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

    def __init__(self):
        self.STEPS = None

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
        containers_runners = ["podman", "docker"]
        for runner in containers_runners:
            try:
                stdout, _ = utils.execute("which", runner)
                LOG.debug("Found %s, returning MAINLINE",
                          runner)
                return hardware.HardwareSupport.MAINLINE
            except Exception as e:
                LOG.debug("Error checking container runner: %s", e)
        LOG.debug("No container runner found, returning NONE")
        return hardware.HardwareSupport.NONE

    def get_clean_steps(self, node, ports):
        """Dynamically generate cleaning steps."""
        self.STEPS = self._load_steps_from_yaml(
            CONF.container['container_steps_file'])
        steps = []
        for step in self.STEPS:
            try:
                steps.append(
                    {
                        "step": step["name"],
                        "priority": step["priority"],
                        "interface": step['interface'],
                        "reboot_requested": step['reboot_requested'],
                        "abortable": step["abortable"],
                    }
                )
            except KeyError as e:
                missing_key = str(e)
                step_name = step.get("name", "unknown")
                LOG.exception("Missing key '%s' in cleaning step: %s",
                              missing_key, step_name)
                raise errors.HardwareManagerConfigurationError(
                    f"Missing required key '{missing_key}' in cleaning step:\
                    {step_name}"
                )
        return steps

    def __getattr__(self, name):
        ALLOW_ARBITRARY_CONTAINERS = CONF.container
        ['allow_arbitrary_containers']
        ALLOWED_CONTAINERS = CONF.container['allowed_containers']
        if self.STEPS is None:
            self.STEPS = self._load_steps_from_yaml(
                CONF.container['container_steps_file'])

        for step in self.STEPS:
            if step.get('name') == name:
                if not ALLOW_ARBITRARY_CONTAINERS:
                    if step.get('image') not in ALLOWED_CONTAINERS:
                        LOG.debug(
                            "%s is not registered as ALLOWED_CONTAINERS "
                            "in ironic-python-agent.conf", step.get('image')
                        )
                        continue

                def run_container_steps(*args, **kwargs):
                    try:
                        utils.execute(
                            CONF.container.runner,
                            "pull",
                            *step.get("pull_options",
                                      CONF.container.pull_options),
                            step.get("image"),
                        )
                        LOG.info("Container image '%s' pulled",
                                 step.get("image"))
                        utils.execute(
                            CONF.container.runner,
                            "run",
                            *step.get("run_options",
                                      CONF.container.run_options),
                            step.get("image"),
                        )
                        LOG.info("Container image '%s' completed",
                                 step.get("image"))
                    except Exception as e:
                        LOG.exception("Error during cleanup: %s", e)
                        raise
                return run_container_steps
        raise AttributeError(
            "%s object has no attribute %s", self.__class__.__name__, name)

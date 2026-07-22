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

from functools import partial
import yaml

CONF = cfg.CONF
LOG = log.getLogger(__name__)


class ContainerHardwareManager(hardware.HardwareManager):
    """Hardware manager for container-based cleanup."""

    HARDWARE_MANAGER_NAME = "ContainerHardwareManager"
    HARDWARE_MANAGER_VERSION = "1"

    _RESERVED_NAMES = None

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

    def _check_permitted(self, container_url, pull_options, run_options,
                         trusted):
        """Apply container policy and return the options to execute with.

        Steps baked into the ramdisk are trusted: an operator authored them at
        build time and they cannot be altered at run time. Steps carrying an
        image in their arguments, such as from a runbook or deploy template,
        are not, and are held to [container]allowed_containers.

        :param trusted: whether the step came from the ramdisk itself.
        :returns: the pull and run options to execute with.
        :raises ContainerNotPermittedError: if the image is not permitted.
        """
        if trusted or CONF.container.allow_arbitrary_containers:
            return (pull_options or CONF.container.pull_options,
                    run_options or CONF.container.run_options)

        if container_url not in CONF.container.allowed_containers:
            # Matching is exact and operators are expected to pin by digest,
            # so a refusal is usually two long strings differing in one
            # place. Logging both saves a trip back into the ramdisk to find
            # out what the allowlist actually said.
            LOG.error("Refusing to run container %s: it is not listed in "
                      "[container]allowed_containers, which permits %s",
                      container_url, CONF.container.allowed_containers)
            raise errors.ContainerNotPermittedError(container_url)

        # NOTE(cid): options alone defeat an image allowlist (--privileged,
        # -v /:/host, --entrypoint), so a caller who may not choose the image
        # may not choose the flags either.
        return (CONF.container.pull_options, CONF.container.run_options)

    def _run_container(self, container_url, pull_options=None,
                       run_options=None, trusted=False):
        """Pull and run a container image.

        The only place container images are executed. Every entry point routes
        through here so the policy check cannot be reached around.
        """
        pull_options, run_options = self._check_permitted(
            container_url, pull_options, run_options, trusted)
        utils.execute(CONF.container.runner, "pull",
                      *pull_options, container_url)
        utils.execute(CONF.container.runner, "run",
                      *run_options, container_url)

    def _container_step(self, node, ports, container_url, pull_options=None,
                        run_options=None, trusted=False):
        try:
            self._run_container(container_url, pull_options=pull_options,
                                run_options=run_options, trusted=trusted)
            LOG.info("Container step completed for image: %s", container_url)
        except Exception as e:
            LOG.exception("Error during container operation: %s", e)
            raise

    def container_clean_step(self, node, ports, container_url,
                             pull_options=None, run_options=None):
        """Run a container image supplied through step arguments.

        trusted is hardcoded and deliberately absent from this signature.
        Step arguments are passed straight through, so making it a
        parameter would let a runbook assert its own trust.
        """
        return self._container_step(node, ports, container_url,
                                    pull_options=pull_options,
                                    run_options=run_options, trusted=False)

    def _create_cleanup_method(self, container_url, pull_options=None,
                               run_options=None):
        """Build the callable invoked for a ramdisk-baked step."""
        return partial(self._container_step, container_url=container_url,
                       pull_options=pull_options, run_options=run_options,
                       trusted=True)

    def _create_container_step(self):
        return {
            "step": "container_clean_step",
            "priority": 0,  # run only manual cleaning
            "interface": "deploy",
            "reboot_requested": False,
            "abortable": True,
            "argsinfo": {
                "container_url": {"description": "Container image URL"},
                "pull_options": {"description": "Pull options",
                                 "required": False},
                "run_options": {"description": "Run options",
                                "required": False},
            },
        }

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
        steps = [self._create_container_step()]
        for step in self.STEPS:
            # A step advertised here but refused by __getattr__ would be
            # scheduled and then fail with a confusing "method not found".
            name = step.get("name")
            if name in self._reserved_names():
                raise errors.HardwareManagerConfigurationError(
                    f"Container step '{name}' collides with an existing "
                    f"hardware manager method and would shadow it. Rename it "
                    f"in {CONF.container['container_steps_file']}."
                )
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

    def get_service_steps(self, node, ports):
        return self.get_clean_steps(node, ports)

    def get_deploy_steps(self, node, ports):
        return self.get_clean_steps(node, ports)

    @classmethod
    def _reserved_names(cls):
        """Names a YAML step is not allowed to claim.

        This manager reports MAINLINE, so it is consulted ahead of every other
        manager for every dispatch. Without this, a step named
        erase_devices_metadata would run a container instead of erasing the
        disk, and the step would be reported as successful. An operator's own
        hardware manager is as shadowable as the generic one, so every loaded
        manager contributes the names it answers to.
        """
        if cls._RESERVED_NAMES is not None:
            return cls._RESERVED_NAMES

        names = (frozenset(dir(cls))
                 | frozenset(dir(hardware.GenericHardwareManager)))

        # NOTE(cid): the loaded managers are read from the cache instead of
        # being requested with get_managers(). Managers are probed and
        # initialized inside get_managers_detail(), so asking it for them
        # from __getattr__ while it is still running re-enters it with the
        # cache empty and recurses.
        managers = hardware._global_managers
        if not managers:
            # Nothing is loaded yet, so the generic manager is every name
            # that can be known here. Deliberately left uncached: the full
            # set is available once loading finishes.
            return names

        cls._RESERVED_NAMES = names.union(
            *(frozenset(dir(hwm['manager'])) for hwm in managers))
        return cls._RESERVED_NAMES

    def __getattr__(self, name):
        """Resolve a steps file entry to the callable that runs it.

        Container policy is not applied here. Resolving a name is not running
        it, and enforcing at resolution time has let the guard be skipped
        silently before; policy lives in _check_permitted(). Private names are
        never synthesized, because doing so sends copy, pickle and hasattr
        probing into a YAML read.
        """
        if name.startswith('_') or name in self._reserved_names():
            raise AttributeError(
                '%s object has no attribute %s'
                % (self.__class__.__name__, name))

        # Not self.STEPS: that recurses here when __init__ has not run.
        steps = self.__dict__.get('STEPS')
        if steps is None:
            steps = self.STEPS = self._load_steps_from_yaml(
                CONF.container['container_steps_file'])

        for step in steps:
            if step.get('name') == name:
                return self._create_cleanup_method(
                    container_url=step.get('image'),
                    pull_options=step.get('pull_options'),
                    run_options=step.get('run_options'))
        raise AttributeError(
            '%s object has no attribute %s'
            % (self.__class__.__name__, name))

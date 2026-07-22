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

# Transports naming an image in a remote registry, and so the only ones it is
# safe to look through. oci:// is ironic's own spelling for a registry
# reference and carries no trademark. Stripping a local transport instead
# would let containers-storage:example.com/tool:1 match an allowlist entry
# written for the registry image while running whatever happens to sit in
# local storage under that name. A transport absent from here fails closed:
# the reference does not normalize, so it matches nothing and is refused.
TRANSPORT_PREFIXES = ('docker://', 'oci://')


def _normalize_image_ref(value):
    """Strip the transport prefix from a container image reference.

    ``docker://example.com/tool:1`` and ``example.com/tool:1`` name the same
    image, so the allowlist must not treat them as different.
    """
    for prefix in TRANSPORT_PREFIXES:
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def _as_options(value):
    """Normalize configured container options into argv elements.

    pull_options and run_options are ListOpts, and lists split on commas
    rather than whitespace. The conductor sends them as plain strings and the
    build element writes them space separated, so without this a whole option
    string reaches the runtime as a single argument. An option value
    containing a literal space cannot be expressed this way.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [word for item in value for word in str(item).split()]


class ContainerHardwareManager(hardware.HardwareManager):
    """Hardware manager for container-based cleanup."""

    HARDWARE_MANAGER_NAME = "ContainerHardwareManager"
    HARDWARE_MANAGER_VERSION = "1"

    # Runtimes support detection scans for; [container]runner picks one.
    CONTAINER_RUNNERS = ("podman", "docker")

    _RESERVED_NAMES = None

    def __init__(self):
        self.STEPS = None

    def _load_steps_from_yaml(self, file_path):
        """Load container steps from the configured YAML file.

        A missing file means the ramdisk defines no container steps, which is
        normal. A file that exists but cannot be read or parsed is an operator
        error and is reported rather than treated as "no steps".

        :raises HardwareManagerConfigurationError: if the file exists but
            cannot be read, parsed, or does not match the expected schema.
        """
        try:
            with open(file_path, 'r') as file:
                data = yaml.safe_load(file)
        except FileNotFoundError:
            LOG.debug("No container steps file at %s", file_path)
            return []
        except (OSError, yaml.YAMLError) as e:
            raise errors.HardwareManagerConfigurationError(
                f"Could not read container steps from {file_path}: {e}"
            )

        if data is None:
            return []
        if not isinstance(data, dict):
            raise errors.HardwareManagerConfigurationError(
                f"Container steps file {file_path} must contain a mapping "
                f"with a 'steps' key, got {type(data).__name__}."
            )

        steps = data.get('steps') or []
        if not isinstance(steps, list):
            raise errors.HardwareManagerConfigurationError(
                f"'steps' in {file_path} must be a list, got "
                f"{type(steps).__name__}."
            )
        for step in steps:
            self._validate_step(step, file_path)
        return steps

    @staticmethod
    def _validate_step(step, file_path):
        """Check a single YAML step has what execution will need.

        :raises HardwareManagerConfigurationError: if the step is unusable.
        """
        if not isinstance(step, dict):
            raise errors.HardwareManagerConfigurationError(
                f"Each container step in {file_path} must be a mapping, got "
                f"{type(step).__name__}."
            )
        for key in ('name', 'image'):
            if not step.get(key):
                raise errors.HardwareManagerConfigurationError(
                    f"Container step '{step.get('name', '<unnamed>')}' in "
                    f"{file_path} is missing the required '{key}' key."
                )

    def _check_permitted(self, container_url, pull_options, run_options,
                         trusted):
        """Apply container policy and return the options to execute with.

        Steps baked into the ramdisk are trusted: an operator authored them at
        build time and they cannot be altered at run time. Steps carrying an
        image in their arguments, such as from a runbook or deploy template,
        are not, and are held to [container]allowed_containers.

        Step arguments are validated by name but not by type, so
        container_url arrives as whatever JSON the runbook carried and is
        type checked here.

        :param trusted: whether the step came from the ramdisk itself.
        :returns: the pull and run options to execute with.
        :raises InvalidCommandParamsError: if container_url is not a string.
        :raises ContainerNotPermittedError: if the image is not permitted.
        """
        if not isinstance(container_url, str) or not container_url:
            raise errors.InvalidCommandParamsError(
                "container_url must be a non-empty string, got "
                f"{type(container_url).__name__}.")

        if trusted or CONF.container.allow_arbitrary_containers:
            return (_as_options(pull_options or CONF.container.pull_options),
                    _as_options(run_options or CONF.container.run_options))

        allowed = {_normalize_image_ref(image)
                   for image in CONF.container.allowed_containers}
        if _normalize_image_ref(container_url) not in allowed:
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
        return (_as_options(CONF.container.pull_options),
                _as_options(CONF.container.run_options))

    def _run_container(self, container_url, pull_options=None,
                       run_options=None, trusted=False):
        """Pull and run a container image.

        The only place container images are executed. Every entry point routes
        through here so the policy check cannot be reached around.
        """
        pull_options, run_options = self._check_permitted(
            container_url, pull_options, run_options, trusted)
        self._check_runner_available()
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
                "container_url": {"description": "Container image URL",
                                  "required": True},
                "pull_options": {"description": "Pull options",
                                 "required": False},
                "run_options": {"description": "Run options",
                                "required": False},
            },
        }

    def evaluate_hardware_support(self):
        """Determine if a container runner exists and return support level.

        [container]runner is not consulted here. Managers are evaluated before
        the lookup response is applied, so it would test a value the conductor
        is about to replace. _check_runner_available() checks the configured
        runtime at execution time instead.

        The runtime is asked for its version rather than merely located, so a
        binary that is present but cannot run does not read as support.
        """
        for runner in self.CONTAINER_RUNNERS:
            try:
                utils.execute(runner, "--version")
                LOG.debug("Found %s, returning MAINLINE", runner)
                return hardware.HardwareSupport.MAINLINE
            except Exception as e:
                LOG.debug("Error checking container runner: %s", e)
        LOG.info("No container runtime (%s) is usable in this ramdisk, "
                 "container based steps are unavailable",
                 ", ".join(self.CONTAINER_RUNNERS))
        return hardware.HardwareSupport.NONE

    def _check_runner_available(self):
        """Verify the configured container runner runs in this ramdisk.

        :raises HardwareManagerConfigurationError: if it is not usable.
        """
        runner = CONF.container.runner
        try:
            utils.execute(runner, "--version")
        except Exception as e:
            raise errors.HardwareManagerConfigurationError(
                f"Configured container runner '{runner}' "
                f"([container]runner) is not usable in this ramdisk: {e}"
            )

    def _get_steps(self, automatic):
        """Build the advertised step list.

        :param automatic: whether a step's declared priority is honored. A
            priority in the steps file describes automated cleaning; other
            phases expose the same steps for explicit invocation only.
        """
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
                # Read priority even when it is about to be discarded, so a
                # steps file missing it fails the same way in every phase.
                priority = step["priority"]
                steps.append(
                    {
                        "step": step["name"],
                        "priority": priority if automatic else 0,
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
                    f"Missing required key {missing_key} in cleaning step: "
                    f"{step_name}"
                )
        return steps

    def get_clean_steps(self, node, ports):
        """Dynamically generate cleaning steps."""
        return self._get_steps(automatic=True)

    def get_service_steps(self, node, ports):
        """Generate service steps, none of which run on their own.

        Priorities in the steps file describe automated cleaning. Honoring
        them here would run every such container on every service operation.
        """
        return self._get_steps(automatic=False)

    def get_deploy_steps(self, node, ports):
        """Generate deploy steps, none of which run on their own.

        A deploy step with a priority above zero runs automatically, so
        honoring the steps file priority here would fire a container meant
        for cleaning on every deployment.
        """
        return self._get_steps(automatic=False)

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
            try:
                steps = self._load_steps_from_yaml(
                    CONF.container['container_steps_file'])
            except errors.HardwareManagerConfigurationError as e:
                # NOTE(cid): raising here would break dispatch for unrelated
                # methods, since this manager is consulted first for all of
                # them. get_clean_steps() reports the same problem loudly.
                LOG.error("Cannot resolve container step %s: %s", name, e)
                steps = []
            self.STEPS = steps

        for step in steps:
            if step.get('name') == name:
                return self._create_cleanup_method(
                    container_url=step.get('image'),
                    pull_options=step.get('pull_options'),
                    run_options=step.get('run_options'))
        raise AttributeError(
            '%s object has no attribute %s'
            % (self.__class__.__name__, name))

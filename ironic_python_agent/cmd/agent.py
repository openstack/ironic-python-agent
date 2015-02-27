# Copyright 2013 Rackspace, Inc.
#
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

import glob
import os

from oslo_concurrency import processutils
from oslo_config import cfg

from ironic_python_agent import agent
from ironic_python_agent import errors
from ironic_python_agent.openstack.common import log
from ironic_python_agent import utils

CONF = cfg.CONF


def _read_params_from_file(filepath):
    """Extract key=value pairs from a file.

    :param filepath: path to a file containing key=value pairs separated by
                     whitespace or newlines.
    :returns: a dictionary representing the content of the file
    """
    with open(filepath) as f:
        cmdline = f.read()

    options = cmdline.split()
    params = {}
    for option in options:
        if '=' not in option:
            continue
        k, v = option.split('=', 1)
        params[k] = v

    return params


def _get_agent_params():
    """Gets parameters passed to the agent via kernel cmdline or vmedia.

    Parameters can be passed using either the kernel commandline or through
    virtual media. If boot_method is vmedia, merge params provided via vmedia
    with those read from the kernel command line.

    Although it should never happen, if a variable is both set by vmedia and
    kernel command line, the setting in vmedia will take precedence.

    :returns: a dict of potential configuration parameters for the agent
    """
    params = _read_params_from_file('/proc/cmdline')

    # If the node booted over virtual media, the parameters are passed
    # in a text file within the virtual media floppy.
    if params.get('boot_method', None) == 'vmedia':
        vmedia_params = _get_vmedia_params()
        params.update(vmedia_params)

    return params


def _get_vmedia_device():
    """Finds the device filename of the virtual media device using sysfs.

    :returns: a string containing the filename of the virtual media device
    """
    sysfs_device_models = glob.glob("/sys/class/block/*/device/model")
    vmedia_device_model = "virtual media"
    for model_file in sysfs_device_models:
        try:
            with open(model_file) as model_file_fobj:
                if vmedia_device_model in model_file_fobj.read().lower():
                    vmedia_device = model_file.split('/')[4]
                    return vmedia_device
        except Exception:
            pass


def _get_vmedia_params():
    """This method returns the parameters passed to the agent through virtual
    media floppy.

    :returns: a partial dict of potential agent configuration parameters
    :raises: VirtualMediaBootError when it cannot find the virtual media device
    """
    vmedia_mount_point = "/vmedia_mnt"
    parameters_file = "parameters.txt"

    vmedia_device = _get_vmedia_device()
    if not vmedia_device:
        msg = "Unable to find virtual media device"
        raise errors.VirtualMediaBootError(msg)

    vmedia_device_file = os.path.join("/dev", vmedia_device)
    os.mkdir(vmedia_mount_point)

    try:
        stdout, stderr = utils.execute("mount", vmedia_device_file,
                                       vmedia_mount_point)
    except processutils.ProcessExecutionError as e:
        msg = ("Unable to mount virtual media device %(device)s: %(error)s" %
              {'device': vmedia_device_file, 'error': e})
        raise errors.VirtualMediaBootError(msg)

    parameters_file_path = os.path.join(vmedia_mount_point, parameters_file)
    params = _read_params_from_file(parameters_file_path)

    try:
        stdout, stderr = utils.execute("umount", vmedia_mount_point)
    except processutils.ProcessExecutionError as e:
        pass

    return params


APARAMS = _get_agent_params()

cli_opts = [
    cfg.StrOpt('api_url',
                  default=APARAMS.get('ipa-api-url', 'http://127.0.0.1:6835'),
                  deprecated_name='api-url',
                  help='URL of the Ironic API'),

    cfg.StrOpt('listen_host',
                  default=APARAMS.get('ipa-listen-host', '0.0.0.0'),
                  deprecated_name='listen-host',
                  help='The IP address to listen on.'),

    cfg.IntOpt('listen_port',
               default=int(APARAMS.get('ipa-listen-port', 9999)),
               deprecated_name='listen-port',
               help='The port to listen on'),

    cfg.StrOpt('advertise_host',
                  default=APARAMS.get('ipa-advertise-host', None),
                  deprecated_name='advertise_host',
                  help='The host to tell Ironic to reply and send '
                       'commands to.'),

    cfg.IntOpt('advertise_port',
               default=int(APARAMS.get('ipa-advertise-port', 9999)),
               deprecated_name='advertise-port',
               help='The port to tell Ironic to reply and send '
                    'commands to.'),

    cfg.IntOpt('ip_lookup_attempts',
               default=int(APARAMS.get('ipa-ip-lookup-attempts', 3)),
               deprecated_name='ip-lookup-attempts',
               help='The number of times to try and automatically'
                    'determine the agent IPv4 address.'),

    cfg.IntOpt('ip_lookup_sleep',
               default=int(APARAMS.get('ipa-ip-lookup-timeout', 10)),
               deprecated_name='ip-lookup-sleep',
               help='The amaount of time to sleep between attempts'
                    'to determine IP address.'),

    cfg.StrOpt('network_interface',
               default=APARAMS.get('ipa-network-interface', None),
               deprecated_name='network-interface',
               help='The interface to use when looking for an IP'
               'address.'),

    cfg.IntOpt('lookup_timeout',
               default=int(APARAMS.get('ipa-lookup-timeout', 300)),
               deprecated_name='lookup-timeout',
               help='The amount of time to retry the initial lookup '
                    'call to Ironic. After the timeout, the agent '
                    'will exit with a non-zero exit code.'),

    cfg.IntOpt('lookup_interval',
               default=int(APARAMS.get('ipa-lookup-timeout', 1)),
               deprecated_name='lookup-interval',
               help='The initial interval for retries on the initial '
                    'lookup call to Ironic. The interval will be '
                    'doubled after each failure until timeout is '
                    'exceeded.'),

    cfg.StrOpt('driver_name',
                  default=APARAMS.get('ipa-driver-name', 'agent_ipmitool'),
                  deprecated_name='driver-name',
                  help='The Ironic driver in use for this node'),

    cfg.FloatOpt('lldp_timeout',
                 default=APARAMS.get('lldp-timeout', 30.0),
                 help='The amount of seconds to wait for LLDP packets.'),

    cfg.BoolOpt('standalone',
                default=APARAMS.get('ipa-standalone', False),
                help='Note: for debugging only. Start the Agent but suppress '
                     'any calls to Ironic API.'),
]

CONF.register_cli_opts(cli_opts)


def run():
    CONF()
    log.setup('ironic-python-agent')
    agent.IronicPythonAgent(CONF.api_url,
                            (CONF.advertise_host, CONF.advertise_port),
                            (CONF.listen_host, CONF.listen_port),
                            CONF.ip_lookup_attempts,
                            CONF.ip_lookup_sleep,
                            CONF.network_interface,
                            CONF.lookup_timeout,
                            CONF.lookup_interval,
                            CONF.driver_name,
                            CONF.standalone).run()

# Copyright 2016 Cisco Systems, Inc.
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

from oslo_config import cfg
from oslo_log import log as logging

from ironic_python_agent import netutils
from ironic_python_agent import utils

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

APARAMS = utils.get_agent_params()

INSPECTION_DEFAULT_COLLECTORS = 'default,logs'
INSPECTION_DEFAULT_DHCP_WAIT_TIMEOUT = 60

cli_opts = [
    cfg.StrOpt('api_url',
               default=APARAMS.get('ipa-api-url'),
               regex='^(mdns|http(s?):\\/\\/.+)',
               help='URL(s) of the Ironic API. '
                    'Can be supplied as "ipa-api-url" kernel parameter.'
                    'The value(s) must start with either http:// or https://. '
                    'A special value "mdns" can be specified to fetch the '
                    'URL using multicast DNS service discovery. If several '
                    'URLs are provided, all of them are tried until one '
                    'does not return a connection error.'),

    cfg.StrOpt('global_request_id',
               default=APARAMS.get('ipa-global-request-id'),
               help='Global request ID header to provide to Ironic API. '
                    'Can be supplied as "ipa-global-request-id" kernel '
                    'parameter. The value must be in form "req-<UUID>".'),

    cfg.StrOpt('listen_host',
               default=APARAMS.get('ipa-listen-host',
                                   netutils.get_wildcard_address()),
               sample_default='::',
               help='The IP address to listen on. '
                    'Can be supplied as "ipa-listen-host" kernel parameter.'),

    cfg.PortOpt('listen_port',
                default=int(APARAMS.get('ipa-listen-port', 9999)),
                help='The port to listen on. '
                     'Can be supplied as "ipa-listen-port" kernel parameter.'),

    # This is intentionally not settable via kernel command line, as it
    # requires configuration parameters from oslo_service which are not
    # configurable over the command line and require files-on-disk.
    # Operators who want to use this support should configure it statically
    # as part of a ramdisk build.
    cfg.BoolOpt('listen_tls',
                default=False,
                help='When true, IPA will host API behind TLS. You will also '
                     'need to configure [ssl] group options for cert_file, '
                     'key_file, and, if desired, ca_file to validate client '
                     'certificates.'),

    cfg.BoolOpt('enable_auto_tls',
                default=True,
                help='Enables auto-generating TLS parameters when listen_tls '
                     'is False and ironic API version indicates support for '
                     'automatic agent TLS.'),

    cfg.IntOpt('auto_tls_allowed_clock_skew',
               default=3600, min=0,
               help='Clock skew (in seconds) allowed in the generated TLS '
                    'certificate.'),

    cfg.StrOpt('advertise_host',
               default=APARAMS.get('ipa-advertise-host', None),
               help='The host to tell Ironic to reply and send '
                    'commands to. '
                    'Can be supplied as "ipa-advertise-host" '
                    'kernel parameter.'),

    cfg.PortOpt('advertise_port',
                default=int(APARAMS.get('ipa-advertise-port', 9999)),
                help='The port to tell Ironic to reply and send '
                     'commands to. '
                     'Can be supplied as "ipa-advertise-port" '
                     'kernel parameter.'),

    cfg.StrOpt('advertise_protocol',
               default=APARAMS.get('ipa-advertise-protocol', 'http'),
               choices=['http', 'https'],
               help='Protocol to use for the callback URL. HTTP is used by '
                    'default, set to "https" if you have HTTPS configured.'),

    cfg.IntOpt('ip_lookup_attempts',
               min=1,
               default=int(APARAMS.get('ipa-ip-lookup-attempts', 6)),
               help='The number of times to try and automatically '
                    'determine the agent IPv4 address. '
                    'Can be supplied as "ipa-ip-lookup-attempts" '
                    'kernel parameter.'),

    cfg.IntOpt('ip_lookup_sleep',
               min=0,
               default=int(APARAMS.get('ipa-ip-lookup-timeout', 10)),
               help='The amount of time to sleep between attempts '
                    'to determine IP address. '
                    'Can be supplied as "ipa-ip-lookup-timeout" '
                    'kernel parameter.'),

    cfg.StrOpt('network_interface',
               default=APARAMS.get('ipa-network-interface', None),
               help='The interface to use when looking for an IP address. '
                    'Can be supplied as "ipa-network-interface" '
                    'kernel parameter.'),

    cfg.IntOpt('lookup_timeout',
               min=0,
               default=int(APARAMS.get('ipa-lookup-timeout', 600)),
               help='The amount of time to retry the initial lookup '
                    'call to Ironic. After the timeout, the agent '
                    'will exit with a non-zero exit code. '
                    'Can be supplied as "ipa-lookup-timeout" '
                    'kernel parameter.'),

    cfg.IntOpt('lookup_interval',
               min=0,
               default=int(APARAMS.get('ipa-lookup-interval', 1)),
               help='The initial interval for retries on the initial '
                    'lookup call to Ironic. The interval will be '
                    'doubled after each failure until timeout is '
                    'exceeded. '
                    'Can be supplied as "ipa-lookup-interval" '
                    'kernel parameter.'),

    cfg.FloatOpt('lldp_timeout',
                 default=APARAMS.get('ipa-lldp-timeout', 30.0),
                 help='The amount of seconds to wait for LLDP packets. '
                      'Can be supplied as "ipa-lldp-timeout" '
                      'kernel parameter.'),

    cfg.BoolOpt('collect_lldp',
                default=APARAMS.get('ipa-collect-lldp', False),
                help='Whether IPA should attempt to receive LLDP packets for '
                     'each network interface it discovers in the inventory. '
                     'Can be supplied as "ipa-collect-lldp" '
                     'kernel parameter.',
                deprecated_for_removal=True,
                deprecated_reason="Use the lldp collector instead"),

    cfg.StrOpt('inspection_callback_url',
               default=APARAMS.get('ipa-inspection-callback-url'),
               help='Endpoint(s) to send inspection data to. If set, hardware '
                    'inventory will be collected and sent there on start up. '
                    'A special value "mdns" can be specified to fetch the '
                    'URL using multicast DNS service discovery. '
                    'Can be supplied as "ipa-inspection-callback-url" '
                    'kernel parameter. If the URL is not provided but '
                    'inspection_collectors is not empty, the URL is detected '
                    'from api_url.'),

    cfg.StrOpt('inspection_collectors',
               default=APARAMS.get('ipa-inspection-collectors'),
               help='Comma-separated list of plugins providing additional '
                    'hardware data for inspection. The default are %s. '
                    'Can be supplied as "ipa-inspection-collectors" '
                    'kernel parameter.'
                    % INSPECTION_DEFAULT_COLLECTORS),

    cfg.IntOpt('inspection_dhcp_wait_timeout',
               min=0,
               default=APARAMS.get('ipa-inspection-dhcp-wait-timeout',
                                   INSPECTION_DEFAULT_DHCP_WAIT_TIMEOUT),
               help='Maximum time (in seconds) to wait for the PXE NIC '
                    '(or all NICs if inspection_dhcp_all_interfaces is True) '
                    'to get its IP address via DHCP before inspection. '
                    'Set to 0 to disable waiting completely. '
                    'Can be supplied as "ipa-inspection-dhcp-wait-timeout" '
                    'kernel parameter.'),

    cfg.BoolOpt('inspection_dhcp_all_interfaces',
                default=APARAMS.get('ipa-inspection-dhcp-all-interfaces',
                                    False),
                help='Whether to wait for all interfaces to get their IP '
                     'addresses before inspection. If set to false '
                     '(the default), only waits for the PXE interface. '
                     'Can be supplied as '
                     '"ipa-inspection-dhcp-all-interfaces" '
                     'kernel parameter.'),

    cfg.IntOpt('hardware_initialization_delay',
               min=0,
               default=APARAMS.get('ipa-hardware-initialization-delay', 0),
               help='How much time (in seconds) to wait for hardware to '
                    'initialize before proceeding with any actions. '
                    'Can be supplied as "ipa-hardware-initialization-delay" '
                    'kernel parameter.'),

    cfg.IntOpt('disk_wait_attempts',
               min=0,
               default=APARAMS.get('ipa-disk-wait-attempts', 10),
               help='The number of times to try and check to see if '
                    'at least one suitable disk has appeared in inventory '
                    'before proceeding with any actions. '
                    'Can be supplied as "ipa-disk-wait-attempts" '
                    'kernel parameter.'),

    cfg.IntOpt('disk_wait_delay',
               min=0,
               default=APARAMS.get('ipa-disk-wait-delay', 3),
               help='How much time (in seconds) to wait between attempts '
                    'to check if at least one suitable disk has appeared '
                    'in inventory. Set to zero to disable. '
                    'Can be supplied as "ipa-disk-wait-delay" '
                    'kernel parameter.'),
    cfg.BoolOpt('insecure',
                default=APARAMS.get('ipa-insecure', False),
                help='Verify HTTPS connections. Can be supplied as '
                     '"ipa-insecure" kernel parameter.'),
    cfg.StrOpt('cafile',
               help='Path to PEM encoded Certificate Authority file '
                    'to use when verifying HTTPS connections. '
                    'Default is to use available system-wide configured CAs.'),
    cfg.StrOpt('certfile',
               help='Path to PEM encoded client certificate cert file. '
                    'Must be provided together with "keyfile" option. '
                    'Default is to not present any client certificates to '
                    'the server.'),
    cfg.StrOpt('keyfile',
               help='Path to PEM encoded client certificate key file. '
                    'Must be provided together with "certfile" option. '
                    'Default is to not present any client certificates to '
                    'the server.'),
    cfg.BoolOpt('introspection_daemon',
                default=False,
                help='When the ``ironic-collect-introspection-data`` '
                     'command is executed, continue running as '
                     'a background process and continue to post data '
                     'to the bare metal inspection service.'),
    cfg.IntOpt('introspection_daemon_post_interval',
               default=300,
               help='The interval in seconds by which to transmit data to '
                    'the bare metal introspection service when the '
                    '``ironic-collect-introspection-data`` program is '
                    'executing in daemon mode.'),
    cfg.StrOpt('ntp_server',
               default=APARAMS.get('ipa-ntp-server', None),
               help='Address of a single NTP server against which the '
                    'agent should sync the hardware clock prior to '
                    'rebooting to an instance.'),
    cfg.BoolOpt('fail_if_clock_not_set',
                default=False,
                help='If operations should fail if the clock time sync '
                     'fails to complete successfully.'),
    cfg.StrOpt('agent_token',
               default=APARAMS.get('ipa-agent-token'),
               help='Pre-shared token to use when working with the '
                    'ironic API. This value is typically supplied by '
                    'ironic automatically.'),
    cfg.StrOpt('image_server_user',
               default=None,
               help='Pre-shared username used in Basic Auth process '
                    'against the http(s) server that hosts the disk image.'
                    'This variable can be also configured via image_info.'
                    'Value coming from image_info takes precedence over'
                    'value coming from command line or configuration file.'),
    cfg.StrOpt('image_server_password',
               default=None,
               help='Pre-shared password used in Basic Auth process '
                    'against the http(s) server that hosts the disk image.'
                    'This variable can be also configured via image_info.'
                    'Value coming from image_info takes precedence over'
                    'value coming from command line or configuration file.'),
    cfg.StrOpt('image_server_auth_strategy',
               default="noauth",
               help='Option to select authentication strategy used during'
                    'communication with the server that hosts the disk images'
                    'and related checksums. This option also turns'
                    'image_server_password and image_server_user'
                    'into mandatory variables for those authentication'
                    'strategies that require username + password credentials.'
                    'This variable can be also configured via image_info.'
                    'Value coming from image_info takes precedence over'
                    'value coming from command line or configuration file.'),
    cfg.BoolOpt('agent_token_required',
                default=APARAMS.get('ipa-agent-token-required', False),
                help='Control to enforce if API command requests should '
                     'enforce token validation. The configuration provided '
                     'by the conductor MAY override this and force this '
                     'setting to be changed to True in memory.'),
    cfg.IntOpt('image_download_connection_timeout', min=1,
               default=APARAMS.get(
                   'ipa-image-download-connection-timeout', 60),
               help='The connection timeout (in seconds) when downloading '
                    'an image. Does not affect the whole download.'),
    cfg.IntOpt('image_download_connection_retries', min=0,
               default=APARAMS.get('ipa-image-download-connection-retries', 9),
               help='How many times to retry the connection when downloading '
                    'an image. Also retries on failure HTTP statuses.'),
    cfg.IntOpt('image_download_connection_retry_interval', min=0,
               default=APARAMS.get(
                   'ipa-image-download-connection-retry-interval', 10),
               help='Interval (in seconds) between two attempts to establish '
                    'connection when downloading an image.'),
    cfg.StrOpt('ironic_api_version',
               default=APARAMS.get('ipa-ironic-api-version', None),
               help='Ironic API version in format "x.x". If not set, the API '
                    'version will be auto-detected. Defining an API version '
                    'using this setting is not advisiable nor recommended as '
                    'it blocks auto-detection of the API version. '
                    'This is an advanced override setting which may only '
                    'be useful if the environment requires API version '
                    'auto-detection to be disabled or blocked.'),
    cfg.StrOpt('enable_vlan_interfaces',
               default=APARAMS.get('ipa-enable-vlan-interfaces', ''),
               help='Comma-separated list of VLAN interfaces to enable, '
                    'in the format "interface.vlan".  If only an '
                    'interface is provided, then IPA should attempt to '
                    'bring up all VLANs on that interface detected '
                    'via lldp.  If "all" is set then IPA should attempt '
                    'to bring up all VLANs from lldp on all interfaces. '
                    'By default, no VLANs will be brought up.'),
    cfg.BoolOpt('ignore_bootloader_failure',
                default=APARAMS.get('ipa-ignore-bootloader-failure'),
                help='If the agent should ignore failures to install a '
                     'bootloader configuration into UEFI NVRAM. This '
                     'option should only be considered if the hardware '
                     'is automatically searching and adding UEFI '
                     'bootloaders from partitions. Use on a system '
                     'which is NOT doing this will likely cause the '
                     'deployment to fail. This setting should only be '
                     'used if you are absolutely sure of what you are '
                     'doing and that your hardware supports '
                     'such functionality. Hint: Most hardware does not.'),
    cfg.IntOpt('inject_files_priority',
               default=APARAMS.get('ipa-inject-files-priority', 0),
               min=0, max=99,  # 100 is when IPA is booted
               help='Priority of the inject_files deploy step (disabled '
                    'by default), an integer between 1 and .'),
    cfg.BoolOpt('guard-special-filesystems',
                default=APARAMS.get('ipa-guard-special-filesystems', True),
                help='Guard "special" shared device filesystems from '
                     'cleaning by the stock hardware manager\'s cleaning '
                     'methods. If one of these filesystems is detected '
                     'during cleaning, the cleaning process will be aborted '
                     'and infrastructure operator intervention may be '
                     'required as this option is intended to prevent '
                     'cleaning from inadvertently destroying a running '
                     'cluster which may be visible over a storage fabric '
                     'such as FibreChannel.'),
    cfg.BoolOpt('md5_enabled',
                default=True,
                help='If the MD5 algorithm is enabled for file checksums. '
                     'Will be changed to False in the future.'),
    cfg.IntOpt('http_request_timeout',
               default=APARAMS.get('ipa-http-request-timeout', 30),
               min=1,
               help='Time in seconds to wait for an HTTP request TCP socket '
                    'used by an API request to a remote service to enter '
                    'a state where a request can be transmitted.'),
    cfg.BoolOpt('config_drive_rebuild',
                default=False,
                help='If the agent should rebuild the configuration drive '
                     'using a local filesystem, instead of letting Ironic '
                     'determine if this action is necessary.'),
    cfg.BoolOpt('disable_deep_image_inspection',
                default=False,
                help='This disables the additional deep image inspection '
                     'the agent does before converting and writing an image. '
                     'Generally, this should remain enabled for maximum '
                     'security, but this option allows disabling it if there '
                     'is a compatibility concern.'),
    cfg.ListOpt('permitted_image_formats',
                default='raw,qcow2',
                help='The supported list of image formats which are '
                     'permitted for deployment with Ironic Python Agent. If '
                     'an image format outside of this list is detected, the '
                     'image validation logic will fail the deployment '
                     'process. This check is skipped if deep image '
                     'inspection is disabled.'),
]

disk_utils_opts = [
    cfg.IntOpt('efi_system_partition_size',
               default=550,
               help='Size of EFI system partition in MiB when configuring '
                    'UEFI systems for local boot. A common minimum is ~200 '
                    'megabytes, however OS driven firmware updates and '
                    'unikernel usage generally requires more space on the '
                    'efi partition.'),
    cfg.IntOpt('bios_boot_partition_size',
               default=1,
               help='Size of BIOS Boot partition in MiB when configuring '
                    'GPT partitioned systems for local boot in BIOS.'),
    cfg.StrOpt('dd_block_size',
               default='1M',
               help='Block size to use when writing to the nodes disk.'),
    cfg.IntOpt('partition_detection_attempts',
               default=3,
               min=1,
               help='Maximum attempts to detect a newly created partition.'),
    cfg.IntOpt('partprobe_attempts',
               default=10,
               help='Maximum number of attempts to try to read the '
                    'partition.'),
    cfg.IntOpt('image_convert_memory_limit',
               default=2048,
               help='Memory limit for "qemu-img convert" in MiB. Implemented '
                    'via the address space resource limit.'),
    cfg.IntOpt('image_convert_attempts',
               default=3,
               help='Number of attempts to convert an image.'),
]

disk_part_opts = [
    cfg.IntOpt('check_device_interval',
               default=1,
               help='After Ironic has completed creating the partition table, '
                    'it continues to check for activity on the attached iSCSI '
                    'device status at this interval prior to copying the image'
                    ' to the node, in seconds'),
    cfg.IntOpt('check_device_max_retries',
               default=20,
               help='The maximum number of times to check that the device is '
                    'not accessed by another process. If the device is still '
                    'busy after that, the disk partitioning will be treated as'
                    ' having failed.')
]


def list_opts():
    return [('DEFAULT', cli_opts),
            ('disk_utils', disk_utils_opts),
            ('disk_partitioner', disk_part_opts)]


def populate_config():
    """Populate configuration. In a method so tests can easily utilize it."""
    CONF.register_cli_opts(cli_opts)
    CONF.register_opts(disk_utils_opts, group='disk_utils')
    CONF.register_opts(disk_part_opts, group='disk_partitioner')


def override(params):
    """Override configuration with values from a dictionary.

    This is used for configuration overrides from mDNS.

    :param params: new configuration parameters as a dict.
    """
    if not params:
        return

    LOG.debug('Overriding configuration with %s', params)
    for key, value in params.items():
        if key.startswith('ipa_'):
            key = key[4:]
        else:
            LOG.warning('Skipping unknown configuration option %s', key)
            continue

        try:
            CONF.set_override(key, value)
        except Exception as exc:
            LOG.warning('Unable to override configuration option %(key)s '
                        'with %(value)r: %(exc)s',
                        {'key': key, 'value': value, 'exc': exc})


populate_config()

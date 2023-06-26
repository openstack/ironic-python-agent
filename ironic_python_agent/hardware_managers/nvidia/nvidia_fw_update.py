# Copyright 2022 Nvidia
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

import os
import re
import shutil
import tempfile
from urllib import error as urlError
from urllib.parse import urlparse
from urllib import request

from ironic_lib.common.i18n import _
from ironic_lib.exception import IronicException
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log
from oslo_utils import fileutils

from ironic_python_agent import utils


CONF = cfg.CONF

FW_VERSION_REGEX = r'FW Version:\s*\t*(?P<fw_ver>\d+\.\d+\.\d+)'
RUNNING_FW_VERSION_REGEX = \
    r'FW Version\(Running\):\s*\t*(?P<fw_ver>\d+\.\d+\.\d+)'
ARRAY_PARAM_REGEX = r'(?P<param_name>\w+)\[((?P<index>\d+)|' \
                    r'((?P<first_index>\d+)\.\.(?P<last_index>\d+)))\]'
ARRAY_PARAM_VALUE_REGEX = r'Array\[(?P<first_index>\d+)' \
                          r'\.\.(?P<last_index>\d+)\]'
PSID_REGEX = r'PSID:\s*\t*(?P<psid>\w+)'
NETWORK_DEVICE_REGEX = r'02\d\d'
LOG = log.getLogger()

"""
Example of Nvidia NIC Firmware images list:
[
  {
    "url": "file:///firmware_images/fw1.bin",
    "checksum": "a94e683ea16d9ae44768f0a65942234d",
    "checksumType": "md5",
    "componentFlavor": "MT_0000000540",
    "version": "24.34.1002"
  },
  {
    "url": "http://10.10.10.10/firmware_images/fw2.bin",
    "checksum": "a94e683ea16d9ae44768f0a65942234c",
    "checksumType": "sha512",
    "componentFlavor": "MT_0000000652",
    "version": "24.34.1002"
  }
]

Example of Nvidia NIC Firmware settings list:
[
  {
    "deviceID": "1017",
    "globalConfig": {
      "NUM_OF_VFS": 127,
      "SRIOV_EN": True
    },
    "function0Config": {
      "PF_TOTAL_SF": 500
    },
    "function1Config": {
      "PF_TOTAL_SF": 600
    }
  },
  {
    "deviceID": "101B",
    "globalConfig": {
      "NUM_OF_VFS": 127,
      "SRIOV_EN": True
    },
    "function0Config": {
      "PF_TOTAL_SF": 500
    },
    "function1Config": {
      "PF_TOTAL_SF": 600
    }
  }
]
"""


def check_prereq():
    """Check that all needed tools are available in the system.

    :returns:   None
    :raises:    processutils.ProcessExecutionError
    """
    try:
        # check for mstflint
        utils.execute('mstflint', '-v')
        # check for mstconfig
        utils.execute('mstconfig', '-v')
        # check for mstfwreset
        utils.execute('mstfwreset', '-v')
        # check for lspci
        utils.execute('lspci', '--version')
    except processutils.ProcessExecutionError as e:
        LOG.error('Failed Prerequisite check. %s', e)
        raise e


class InvalidFirmwareImageConfig(IronicException):
    _msg_fmt = _('Invalid firmware image config: %(error_msg)s')


class InvalidFirmwareSettingsConfig(IronicException):
    _msg_fmt = _('Invalid firmware settings config: %(error_msg)s')


class MismatchChecksumError(IronicException):
    _msg_fmt = _('Mismatch Checksum for the firmware image: %(error_msg)s')


class MismatchComponentFlavor(IronicException):
    _msg_fmt = _('Mismatch Component Flavor: %(error_msg)s')


class MismatchFWVersion(IronicException):
    _msg_fmt = _('Mismatch Firmware version: %(error_msg)s')


class DuplicateComponentFlavor(IronicException):
    _msg_fmt = _('Duplicate Component Flavor for the firmware image: '
                 '%(error_msg)s')


class DuplicateDeviceID(IronicException):
    _msg_fmt = _('Duplicate Device ID for firmware settings: '
                 '%(error_msg)s')


class UnSupportedConfigByMstflintPackage(IronicException):
    _msg_fmt = _('Unsupported config by mstflint package: %(error_msg)s')


class UnSupportedConfigByFW(IronicException):
    _msg_fmt = _('Unsupported config by Firmware: %(error_msg)s')


class InvalidURLScheme(IronicException):
    _msg_fmt = _('Invalid URL Scheme: %(error_msg)s')


class NvidiaNicFirmwareOps(object):
    """Perform various Firmware related operations on nic device"""

    def __init__(self, dev):
        self.dev = dev
        self.dev_info = {}

    def parse_mstflint_query_output(out):
        """Parse Mstflint query output

        For now just extract 'FW Version' and 'PSID'
        :param out: string, mstflint query output
        :returns:   dict of query attributes
        """
        query_info = {}
        for line in out.split('\n'):
            line = line.strip()
            fw_ver = re.match(FW_VERSION_REGEX, line)
            running_fw_ver = re.match(RUNNING_FW_VERSION_REGEX, line)
            psid = re.match(PSID_REGEX, line)
            if fw_ver is not None:
                query_info['fw_ver'] = fw_ver.group('fw_ver')
            if running_fw_ver is not None:
                query_info['running_fw_ver'] = running_fw_ver.group('fw_ver')
            if psid is not None:
                query_info['psid'] = psid.group('psid')
        return query_info

    def _query_device(self, force=False):
        """Get firmware information from nvidia nic device

        :param force:   bool, force device query, even if query was executed in
                        previous calls.
        :returns:       dict of firmware image attributes
        :raises:        processutils.ProcessExecutionError
        """
        if not force and self.dev_info.get('device', '') == self.dev:
            return self.dev_info
        try:
            cmd = ('mstflint', '-d', self.dev, '-qq', 'query')
            out, _r = utils.execute(*cmd)
        except processutils.ProcessExecutionError as e:
            LOG.error('Failed to query firmware of device %s: %s',
                      self.dev, e)
            raise e
        self.dev_info = NvidiaNicFirmwareOps.parse_mstflint_query_output(out)
        self.dev_info['device'] = self.dev
        return self.dev_info

    def get_nic_psid(self):
        """Get the psid of nvidia nic device

        :returns:   string, the psid of the nic device
        """
        return self._query_device().get('psid')

    def is_image_changed(self):
        """Check if image changed and nic device requires firmware reset

        before applying any configurations on the device.
        Currently the reset happens if image was changed
        :returns:    bool, True if image changed
        """
        self._query_device(force=True)
        is_image_changed = 'running_fw_ver' in self.dev_info and \
                           self.dev_info['running_fw_ver'] != \
                           self.dev_info['fw_ver']
        return is_image_changed

    def _need_update(self, fw_version):
        """Check if nic device requires firmware update

        :param fw_version:  string, the firmware version of image
        :returns:           bool, True if update is needed
        """
        self._query_device(force=True)
        LOG.info('Device firmware version: %s , Image firmware version: %s',
                 self.dev_info['fw_ver'], fw_version)
        return self.dev_info['fw_ver'] != fw_version

    def _burn_firmware(self, image_path):
        """Burn firmware on device

        :param image_path:  string, firmware binary file path
        :returns:           None
        :raises:            processutils.ProcessExecutionError
        """
        LOG.info('Updating firmware image (%s) for device: %s',
                 image_path, self.dev)
        try:
            cmd = ('mstflint', '-d', self.dev, '-i', image_path,
                   '-y', 'burn')
            utils.execute(*cmd)
        except processutils.ProcessExecutionError as e:
            LOG.error('Failed to update firmware image for device %s, %s',
                      self.dev, e)
            raise e
        LOG.info('Device %s: firmware image successfully updated.', self.dev)

    def reset_device(self, raise_exception=False):
        """Reset nvidia nic to load the new firmware image

        :returns:   None
        :raises:    processutils.ProcessExecutionError
        """
        LOG.info('Device %s: Performing firmware reset.', self.dev)
        cmd = ('mstfwreset', '-d', self.dev, '-y', '--sync', '1', 'reset')
        try:
            utils.execute(*cmd)
            LOG.info('Device %s: Firmware successfully reset.', self.dev)
        except processutils.ProcessExecutionError as e:
            LOG.error('Failed to reset device %s %s', self.dev, e)
            if raise_exception:
                raise e

    def fw_update_if_needed(self, version, image_path):
        """Update firmware if the current version not equal image version

        :param version:     string, the firmware version of image
        :param image_path:  string, the firmware image path
        :returns:           None
        """
        if self._need_update(version):
            if 'running_fw_ver' in self.dev_info:
                self.reset_device(raise_exception=True)
            self._burn_firmware(image_path)
        else:
            LOG.info('Firmware update is not required for Device.')


class NvidiaNic(object):
    """A class of nvidia nic contains pci, device ID,  device PSID and

    an instance of NvidiaNicFirmwareOps
    """

    def __init__(self, dev_pci, dev_id, dev_psid, dev_ops):
        self.dev_pci = dev_pci
        self.dev_id = dev_id
        self.dev_psid = dev_psid
        self.dev_ops = dev_ops


class NvidiaNics(object):
    """Discover and retrieve Nvidia Nics on the system.

    Can be used as an iterator once discover has been called.
    """

    def __init__(self):
        self._devs = []
        self._devs_psids = []
        self._dev_ids = []

    def discover(self):
        """Discover Nvidia Nics in the system.

        :returns:   None
        :raises:    processutils.ProcessExecutionError
        """
        if len(self._devs) > 0:
            return self._devs
        devs = []

        cmd = ('lspci', '-Dn', '-d', '15b3:')
        try:
            out, _r = utils.execute(*cmd)
        except processutils.ProcessExecutionError as e:
            LOG.error('Exception occurred while discovering Nvidia Nics %s',
                      e)
            raise e
        for line in out.strip().split('\n'):
            if not line:
                continue
            dev_class = line.split()[1].split(':')[0]
            if not re.match(NETWORK_DEVICE_REGEX, dev_class):
                continue
            dev_pci = line.split()[0]
            dev_id = line.split('15b3:')[1].split()[0]
            dev_ops = NvidiaNicFirmwareOps(dev_pci)
            dev_psid = dev_ops.get_nic_psid()
            self._dev_ids.append(dev_id)
            self._devs_psids.append(dev_psid)
            devs.append(NvidiaNic(dev_pci, dev_id, dev_psid, dev_ops))
        self._devs = devs

    def get_psids_list(self):
        """Get a list of PSIDs of Nvidia Nics in the system.

        :returns:   list of PSIDs of Nvidia Nics in the system
        """
        return set(self._devs_psids)

    def get_ids_list(self):
        """Get a list of IDs of Nvidia Nics in the system.

        :returns:   list of IDs of Nvidia Nics in the system
        """
        return set(self._dev_ids)

    def __iter__(self):
        return self._devs.__iter__()


class NvidiaNicFirmwareBinary(object):
    """A class of nvidia nic firmware binary which manages the binary

    firmware image, downloads it, validates it and provides its path on the
    system
    """

    def __init__(self, url, checksum, checksum_type,
                 component_flavor, version):
        self.url = url
        self.checksum = checksum
        self.checksum_type = checksum_type
        self.psid = component_flavor
        self.version = version
        self.image_info = {}
        self._process_url()
        self._validate_image_psid()
        self._validate_image_firmware_version()
        self._validate_image_checksum()

    def __del__(self):
        self._cleanup_file()

    def _cleanup_file(self):
        """Delete the temporary downloaded firmware image if exist in cleanup

        :returns:   None
        """
        if os.path.exists(os.path.dirname(self.dest_file_path)):
            try:
                shutil.rmtree(os.path.dirname(self.dest_file_path))
            except Exception as e:
                LOG.error('Failed to remove temporary directory for FW '
                          'binary: %s', e)

    def _download_file_based_fw(self):
        """Download the firmware image file from the provided file url (move)

        :returns:    None
        :raises:    Exception
        """
        src_file = self.parsed_url.path
        try:
            LOG.info('Moving file: %s to %s', self.url,
                     self.dest_file_path)
            shutil.move(src_file, self.dest_file_path)
        except Exception as e:
            LOG.error('Failed to move file: %s, %s', src_file, e)
            raise e

    def _download_http_based_fw(self):
        """Download the firmware image file from the provided url

        :returns:   None
        :raises:    urlError.HTTPError
        """
        try:
            LOG.info('Downloading file: %s to %s', self.url,
                     self.dest_file_path)
            # NOTE(TheJulia: nosec b310 rule below is covered by _process_url
            url_data = request.urlopen(
                self.url,
                timeout=CONF.image_download_connection_timeout)  # nosec
        except urlError.URLError as url_error:
            LOG.error('Failed to open URL data: %s', url_error)
            raise url_error
        except urlError.HTTPError as http_error:
            LOG.error('Failed to download data: %s', http_error)
            raise http_error
        with open(self.dest_file_path, 'wb') as f:
            f.write(url_data.read())

    def _process_url(self):
        """Process the firmware url and download the image to a temporary

        destination in the system.
        The supported firmware URL schemes are (file://, http://, https://)
        :returns:   None
        :raises:    InvalidURLScheme, for unsupported firmware url
        """
        parsed_url = urlparse(self.url)
        self.parsed_url = parsed_url
        file_name = os.path.basename(str(parsed_url.path))
        self.dest_file_path = os.path.join(tempfile.mkdtemp(
            prefix='nvidia_firmware'), file_name)
        url_scheme = parsed_url.scheme
        if url_scheme == 'file':
            self._download_file_based_fw()
        elif url_scheme == 'http' or url_scheme == 'https':
            self._download_http_based_fw()
        else:
            err = 'Firmware URL scheme %s is not supported.' \
                  'The supported firmware URL schemes are' \
                  '(http://, https://, file://)' % url_scheme
            raise InvalidURLScheme(error_msg=_(err))

    def _get_info(self):
        """Get firmware information from firmware binary image

        Caller should wrap this call under try catch to skip non compliant
        firmware binaries.
        :returns:   dict of firmware image attributes
        :raises:    processutils.ProcessExecutionError
        """
        if self.image_info:
            return self.image_info
        try:
            cmd = ('mstflint', '-i', self.dest_file_path, 'query')
            out, _r = utils.execute(*cmd)
        except processutils.ProcessExecutionError as e:
            LOG.error('Failed to query firmware image %s, %s',
                      self.dest_file_path, e)
            raise e
        self.image_info = NvidiaNicFirmwareOps.parse_mstflint_query_output(
            out)
        return self.image_info

    def _validate_image_psid(self):
        """Validate that the provided PSID same as the PSID in provided

        firmware image
        :raises:    MismatchComponentFlavor if they are not equal
        """

        image_psid = self._get_info().get('psid')
        if image_psid != self.psid:
            err = 'The provided psid %s does not match the image psid %s' % \
                  (self.psid, image_psid)
            LOG.error(err)
            raise MismatchComponentFlavor(error_msg=_(err))

    def _validate_image_firmware_version(self):
        """Validate that the provided firmware version same as the version

        in provided firmware image
        :raises:    MismatchFWVersion if they are not equal
        """

        image_version = self._get_info().get('fw_ver')
        if image_version != self.version:
            err = 'The provided firmware version %s does not match ' \
                  'image firmware version %s' % (self.version, image_version)
            LOG.error(err)
            raise MismatchFWVersion(error_msg=_(err))

    def _validate_image_checksum(self):
        """Validate the provided checksum with the calculated one of the

        provided firmware image
        :raises:    MismatchChecksumError if they are not equal
        """
        calculated_checksum = fileutils.compute_file_checksum(
            self.dest_file_path, algorithm=self.checksum_type)
        if self.checksum != calculated_checksum:
            err = 'Mismatch provided checksum %s for image %s' % (
                self.checksum, self.url)
            LOG.error(err)
            raise MismatchChecksumError(error_msg=_(err))


class NvidiaFirmwareImages(object):
    """A class of nvidia firmware images which manages the user provided

    firmware images list
    """

    def __init__(self, firmware_images):
        self.firmware_images = firmware_images
        self.filtered_images_psid_dict = {}

    def validate_images_schema(self):
        """Validate the provided firmware images list schema

        :raises:    InvalidFirmwareImageConfig if any param is missing
        """
        for image in self.firmware_images:
            if not (image.get('url')
                    and image.get('checksum')
                    and image.get('checksumType')
                    and image.get('componentFlavor')
                    and image.get('version')):
                err = 'Invalid parameters for image %s,' \
                      'please provide the following parameters ' \
                      'url, checksum, checksumType, componentFlavor, ' \
                      'version' % image
                LOG.error(err)
                raise InvalidFirmwareImageConfig(error_msg=_(err))

    def filter_images(self, psids_list):
        """Filter firmware images according to the system nics PSIDs,

        and create a map of PSIDs on the system and user provided images.
        Duplicate PSID is not allowed

        :param psids_list:  list of psids of machines nics
        :returns:           None
        :raises:            DuplicateComponentFlavor
        """
        for image in self.firmware_images:
            if image.get('componentFlavor') in psids_list:
                if self.filtered_images_psid_dict.get(
                        image.get('componentFlavor')):
                    err = 'Duplicate componentFlavor %s' % \
                          image['componentFlavor']
                    LOG.error(err)
                    raise DuplicateComponentFlavor(error_msg=_(err))
                else:
                    self.filtered_images_psid_dict[
                        image.get('componentFlavor')] = image
            else:
                LOG.debug('Image with component Flavor %s does not match '
                          'any nic in the system',
                          image.get('componentFlavor'))

    def apply_net_firmware_update(self, nvidia_nics):
        """Apply nic firmware update for all nvidia nics on the system

        which have mappings to the user provided firmware images
        :param nvidia_nics: an object of NvidiaNics
        """
        seen_nics = set()
        for nic in nvidia_nics:
            if self.filtered_images_psid_dict.get(nic.dev_psid):
                # pci_prefix is the pci address without the function number
                # we use it to check if we saw the nic before or not
                pci_prefix = nic.dev_pci[:-1]
                is_seen_nic = pci_prefix in seen_nics
                if not is_seen_nic:
                    seen_nics.add(pci_prefix)
                    fw_bin = NvidiaNicFirmwareBinary(
                        self.filtered_images_psid_dict[nic.dev_psid]['url'],
                        self.filtered_images_psid_dict[nic.dev_psid][
                            'checksum'],
                        self.filtered_images_psid_dict[nic.dev_psid][
                            'checksumType'],
                        self.filtered_images_psid_dict[nic.dev_psid][
                            'componentFlavor'],
                        self.filtered_images_psid_dict[nic.dev_psid][
                            'version'])
                    nic.dev_ops.fw_update_if_needed(
                        self.filtered_images_psid_dict[nic.dev_psid][
                            'version'],
                        fw_bin.dest_file_path)


class NvidiaNicConfig(object):
    """Get/Set Nvidia nics configurations"""

    def __init__(self, nvidia_dev, params):
        self.nvidia_dev = nvidia_dev
        self.params = params
        self._tool_confs = None
        self.device_conf_dict = {}

    def _mstconfig_parse_data(self, data):
        """Parsing the mstconfig out to json

        :param data:    mstconfig query output
        :returns:       dict of nic configuration
        """
        data = list(filter(None, data.split('\n')))
        data_dict = {}
        lines_counter = 0
        for line in data:
            lines_counter += 1
            if 'Configurations:' in line:
                break
        for i in range(lines_counter, len(data)):
            line_data = list(filter(None, data[i].strip().split()))
            data_dict[line_data[0]] = line_data[1]

        return data_dict

    def _get_device_conf_dict(self):
        """Get device Configurations

        :returns:   dict {"PARAM_NAME": "Param value", ....}
        :raises:    processutils.ProcessExecutionError
        """
        LOG.info('Getting configurations for device: %s',
                 self.nvidia_dev.dev_pci)
        if not self.device_conf_dict:
            try:
                cmd = ['mstconfig', '-d', self.nvidia_dev.dev_pci, 'q']
                out, _r = utils.execute(*cmd)
            except processutils.ProcessExecutionError as e:
                LOG.error('Failed to query firmware of device %s: %s',
                          self.nvidia_dev.dev_pci, e)
                raise e
            self.device_conf_dict = self._mstconfig_parse_data(out)
        return self.device_conf_dict

    def _param_supp_by_config_tool(self, param_name):
        """Check if configuration tool supports the provided configuration

        parameter.
        :param param_name:  string, configuration name
        :returns:           bool
        :raises:            processutils.ProcessExecutionError
        """
        if self._tool_confs is None:
            try:
                self._tool_confs, _r = utils.execute(
                    'mstconfig', '-d', self.nvidia_dev.dev_pci, 'i')
            except processutils.ProcessExecutionError as e:
                LOG.error('Failed to query tool configuration of device'
                          ' %s: %s', self.nvidia_dev.dev_pci, e)
                raise e
        # trim any array index if present
        indexed_param = re.match(ARRAY_PARAM_REGEX, param_name)
        if indexed_param:
            param_name = indexed_param.group('param_name')
        return param_name in self._tool_confs

    def _param_supp_by_fw(self, param_name):
        """Check if fw image supports the provided configuration

        parameter.
        :param param_name:  string, configuration name
        :returns:           bool
        :raises:            processutils.ProcessExecutionError
        """
        current_mlx_config = self._get_device_conf_dict()
        indexed_param = re.match(ARRAY_PARAM_REGEX, param_name)
        if indexed_param:
            param_name = indexed_param.group('param_name')
            if param_name not in current_mlx_config:
                return False
            indexed_value = re.match(ARRAY_PARAM_VALUE_REGEX,
                                     current_mlx_config[param_name])
            if not (indexed_value):
                return False
            value_first_index = int(indexed_value.group('first_index'))
            value_last_index = int(indexed_value.group('last_index'))
            param_index = indexed_param.group('index')
            if param_index:
                if int(param_index) in range(value_first_index,
                                             value_last_index):
                    return True
            else:
                param_first_index = int(indexed_param.group('first_index'))
                param_last_index = int(indexed_param.group('last_index'))
                if param_first_index in range(
                        value_first_index, value_last_index) \
                        and param_last_index in range(value_first_index,
                                                      value_last_index) \
                        and param_first_index < param_last_index:
                    return True
            return False
        else:
            return param_name in current_mlx_config

    def validate_config(self):
        """Validate that the firmware settings is supported by mstflint

        package and with current firmware image
        :returns: None
        :raises:    UnSupportedConfigByMstflintPackage
        :raises:    UnSupportedConfigByFW
        """
        LOG.info('Validating config for device %s',
                 self.nvidia_dev.dev_pci)
        for key, value in self.params.items():
            if not self._param_supp_by_config_tool(key):
                err = 'Configuraiton: %s is not supported by mstconfig, ' \
                      'please update to the latest mstflint package.' % key

                LOG.error(err)
                raise UnSupportedConfigByMstflintPackage(error_msg=_(err))

            if not self._param_supp_by_fw(key):
                err = 'Configuraiton %s for device %s is not supported with ' \
                      'current fw' % (key, self.nvidia_dev.dev_pci)
                LOG.error(err)
                raise UnSupportedConfigByFW(error_msg=_(err))

    def set_config(self):
        """Set device configurations

        :param conf_dict:   a dict of:
                            {'PARAM_NAME': 'Param value to set', ...}
        :returns:           None
        :raises:            processutils.ProcessExecutionError
        """
        LOG.info('Setting config for device %s', self.nvidia_dev.dev_pci)
        current_mlx_config = self._get_device_conf_dict()
        params_to_set = []
        for key, value in self.params.items():
            if re.match(ARRAY_PARAM_REGEX, key):
                params_to_set.append('%s=%s' % (key, value))
            else:
                try:
                    # Handle integer values
                    if int(value) != int(current_mlx_config.get(key)):
                        # Aggregate all configurations required to be modified
                        params_to_set.append('%s=%s' % (key, value))
                    else:
                        LOG.info('value of %s for device %s is already '
                                 'configured as %s no need to update it',
                                 key, self.nvidia_dev.dev_pci, value)
                except ValueError:
                    # Handle other values
                    # E.G:
                    # SRIOV_EN                            False(0)
                    # LINK_TYPE_P1                        ETH(2)
                    if str(value).lower() not in \
                            str(current_mlx_config.get(key)).lower():
                        # Aggregate all configurations required to be modified
                        params_to_set.append('%s=%s' % (key, value))
                    else:
                        LOG.info('value of %s for device %s  is already '
                                 'configured as %s, no need to update it',
                                 key, self.nvidia_dev.dev_pci, value)
        if len(params_to_set) > 0:
            try:
                cmd = ['mstconfig', '-d', self.nvidia_dev.dev_pci, '-y', 'set']
                cmd.extend(params_to_set)
                LOG.info('Setting configurations for device: %s',
                         )
                utils.execute(*cmd)
                LOG.info('Set device configurations: Setting %s '
                         'done successfully',
                         ' '.join(params_to_set))
            except processutils.ProcessExecutionError as e:
                LOG.error('Failed to set configuration of device %s, '
                          ' %s: %s', self.nvidia_dev.dev_pci,
                          params_to_set, e)
                raise e

        else:
            LOG.info('Set device configurations: No operation required')


class NvidiaNicsConfig(object):
    """A class of nvidia nics config which manages the user provided

     nics firmware settings
     """

    def __init__(self, nvidia_nics, settings):
        self.settings = settings
        self.nvidia_nics = nvidia_nics
        self.settings_map = {}
        self._nvidia_nics_to_be_reset_list = []
        self._nvidia_nics_config_list = []

    def create_settings_map(self):
        """Filter the user provided nics firmware settings according

        to the system nics IDs, and create a map of IDs on the system and
        user provided nics firmware settings.
        Duplicate IDs  and settings without IDs are not allowed
        :returns:   None
        :raises:    DuplicateDeviceID
        :raises:    InvalidFirmwareSettingsConfig
        """
        ids_list = self.nvidia_nics.get_ids_list()
        for setting in self.settings:
            if (setting.get('deviceID')
                    and setting.get('deviceID') in ids_list
                    and not self.settings_map.get(setting.get('deviceID'))):
                self.settings_map[setting.get('deviceID')] = setting
            elif setting.get('deviceID') and setting.get('deviceID') in \
                    ids_list:
                err = 'duplicate settings for device ID %s ' % \
                      setting.get('deviceID')
                LOG.error(err)
                raise DuplicateDeviceID(error_msg=_(err))
            elif setting.get('deviceID'):
                LOG.debug('There are no devices with ID %s on the system',
                          setting.get('deviceID'))
            else:
                err = 'There is no deviceID provided for this settings'
                LOG.error(err)
                raise InvalidFirmwareSettingsConfig(error_msg=_(err))

    def prepare_nvidia_nic_config(self):
        """Expand the settings map per devices PCI and create a list

        of all NvidiaNicConfig per PCI of nvidia nics on the system.
        Also create a list of all devices that require firmware reset
        :returns:   None
        """
        seen_nics = set()
        for nic in self.nvidia_nics:
            if self.settings_map.get(nic.dev_id):
                params = {}
                prefix = nic.dev_pci[:-1]
                is_seen_nic = prefix in seen_nics
                if not is_seen_nic:
                    seen_nics.add(prefix)
                    if self.settings_map[nic.dev_id].get('globalConfig'):
                        params.update(self.settings_map[nic.dev_id].get(
                            'globalConfig'))
                    if nic.dev_ops.is_image_changed():
                        self._nvidia_nics_to_be_reset_list.append(nic)
                is_first_device = nic.dev_pci[-1] == '0'
                if is_first_device and self.settings_map[nic.dev_id].get(
                        'function0Config'):
                    params.update(self.settings_map[nic.dev_id].get(
                        'function0Config'))
                elif not is_first_device and self.settings_map[nic.dev_id].get(
                        'function1Config'):
                    params.update(self.settings_map[nic.dev_id].get(
                        'function1Config'))
                if params:
                    device_config = NvidiaNicConfig(nic, params)
                    self._nvidia_nics_config_list.append(device_config)

    def reset_nvidia_nics(self):
        """Reset firmware image for all nics in _nvidia_nics_to_be_reset_list

        :returns:   None
        """
        for nvidia_nic in self._nvidia_nics_to_be_reset_list:
            nvidia_nic.dev_ops.reset_device()

    def validate_settings_config(self):
        """Validate firmware settings for all nics in _nvidia_nics_config_list

        :returns:   None
        """
        for nvidia_nic_config in self._nvidia_nics_config_list:
            nvidia_nic_config.validate_config()

    def set_settings_config(self):
        """Set firmware settings for all nics in _nvidia_nics_config_list

        :returns:    None
        """
        for nvidia_nic_config in self._nvidia_nics_config_list:
            nvidia_nic_config.set_config()

    def is_not_empty_reset_list(self):
        """Check if _nvidia_nics_to_be_reset_list is empty or not

        :returns:   bool, True if the list is not empty
        """
        return bool(len(self._nvidia_nics_to_be_reset_list))


def update_nvidia_nic_firmware_image(images):
    """Update nvidia nic firmware image from user provided list images

    :param images:     list of images
    :raises:    InvalidFirmwareImageConfig
    """
    if not type(images) is list:
        err = 'The images must be a list of images, %s' % images
        raise InvalidFirmwareImageConfig(error_msg=_(err))
    check_prereq()
    nvidia_fw_images = NvidiaFirmwareImages(images)
    nvidia_fw_images.validate_images_schema()
    nvidia_nics = NvidiaNics()
    nvidia_nics.discover()
    nvidia_fw_images.filter_images(nvidia_nics.get_psids_list())
    nvidia_fw_images.apply_net_firmware_update(nvidia_nics)


def update_nvidia_nic_firmware_settings(settings):
    """Update nvidia nic firmware settings from user provided list of settings

    :param settings:     list of settings
    :raises:    InvalidFirmwareSettingsConfig
    """
    if not type(settings) is list:
        err = 'The settings must be  list of settings, %s' % settings
        raise InvalidFirmwareSettingsConfig(error_msg=_(err))
    check_prereq()
    nvidia_nics = NvidiaNics()
    nvidia_nics.discover()
    nvidia_nics_config = NvidiaNicsConfig(nvidia_nics, settings)
    nvidia_nics_config.create_settings_map()
    nvidia_nics_config.prepare_nvidia_nic_config()
    if nvidia_nics_config.is_not_empty_reset_list():
        nvidia_nics_config.reset_nvidia_nics()
    nvidia_nics_config.validate_settings_config()
    nvidia_nics_config.set_settings_config()

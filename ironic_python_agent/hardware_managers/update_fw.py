import logging
import os
import re
import shutil
import tempfile
import threading
import six
from six.moves import html_parser
from six.moves.urllib import error as urlError
from six.moves.urllib import request as urlRequest
from oslo_concurrency import processutils
import yaml

FW_VERSION_REGEX = r'FW Version:\s*\t*(?P<fw_ver>\d+\.\d+\.\d+)'
RUNNING_FW_VERSION_REGEX = r'FW Version\(Running\):\s*\t*(?P<fw_ver>\d+\.\d+\.\d+)'
ARRAY_PARAM_REGEX = r'(?P<param_name>\w+)\[\d+\]'
PSID_REGEX = r'PSID:\s*\t*(?P<psid>\w+)'

logging.basicConfig(
    filename='/var/log/nvidia_nics_fw_process.log',
    filemode='w',
    level=logging.INFO)
LOG = logging.getLogger('nvidia_nics_fw_process')


def check_prereq():
    """ Check that all needed tools are available in the system.
    :return: None
    """
    try:
        # check for mstflint
        run_command('mstflint', '-v')
        # check for mstconfig
        run_command('mstconfig', '-v')
        # check for mstfwreset
        run_command('mstfwreset', '-v')
        # check for lspci
        run_command('lspci', '--version')
    except Exception as e:
        LOG.error("Failed Prerequisite check. %s", str(e))
        raise e


def run_command(*cmd, **kwargs):
    try:
        out, err = processutils.execute(*cmd, **kwargs)
    except processutils.ProcessExecutionError as e:
        LOG.error("Failed to execute %s, %s", ' '.join(cmd), str(e))
        raise e
    if err:
        LOG.warning("Got stderr output: %s" % err)
    LOG.debug(out)
    return out


def parse_mstflint_query_output(out):
    """ Parse Mstflint query output
    For now just extract 'FW Version' and 'PSID'
    :param out: mstflint query output
    :return: dictionary of query attributes
    """
    query_info = {}
    for line in out.split('\n'):
        fw_ver = re.match(FW_VERSION_REGEX, line)
        psid = re.match(PSID_REGEX, line)
        running_fw_ver = re.match(RUNNING_FW_VERSION_REGEX, line)
        if fw_ver:
            query_info["fw_ver"] = fw_ver.group('fw_ver')
        if running_fw_ver:
            query_info["running_fw_ver"] = running_fw_ver.group('fw_ver')
        if psid:
            query_info["psid"] = psid.group('psid')
    return query_info


class NvidiaNicFirmwareOps(object):
    """ Perform various Firmware related operations on nic device
    """

    def __init__(self, dev):
        self.dev = dev
        self.dev_info = {}

    def query_device(self, force=False):
        """ Get firmware information from nic device
        :param force: force device query, even if query was executed in
                      previous calls.
        :return: dict of firmware image attributes
        """
        if not force and self.dev_info.get('device', '') == self.dev:
            return self.dev_info
        self.dev_info = {'device': self.dev}
        cmd = ['mstflint', '-d', self.dev, '-qq', 'query']
        out = run_command(*cmd)
        self.dev_info = parse_mstflint_query_output(out)
        return self.dev_info

    def get_nic_psid(self):
        return self.query_device().get('psid')

    def need_update(self, image_info):
        """ Check if nic device requires firmware update
        :param image_info: image_info dict as returned from
                           NvidiaNicFirmwareBinary.get_info()
        :return: bool, True if update is needed
        """
        if not self.dev_info:
            self.query_device()
        LOG.info("Device firmware version: %s, Image firmware version: %s" %
                 (self.dev_info['fw_ver'], image_info['fw_ver']))
        return self.dev_info['fw_ver'] < image_info['fw_ver']

    def need_reset_before_config(self):
        """ Check if device requires firmware reset before applying any
        configurations on the device.
        :return: bool, True if reset is needed
        """
        self.query_device(force=True)
        next_boot_image = 'running_fw_ver' in self.dev_info and \
                                self.dev_info['running_fw_ver'] != self.dev_info['fw_ver']
        return next_boot_image


    def burn_firmware(self, image_path):
        """ Burn firmware on device
        :param image_path: firmware binary file path
        :return: None
        """
        LOG.info("Updating firmware image (%s) for device: %s",
                 image_path, self.dev)
        cmd = ["mstflint", "-d", self.dev, "-i", image_path,
               "-y", "burn"]
        print(cmd)
        #        run_command(*cmd)
        LOG.info("Device %s: Successfully updated.", self.dev)

    def reset_device(self):
        """ Reset firmware
        :return: None
        """
        LOG.info("Device %s: Performing firmware reset.", self.dev)
        cmd = ["mstfwreset", "-d", self.dev, "-y", "reset"]
        print(cmd)
        #run_command(*cmd)
        LOG.info("Device %s: Firmware successfully reset.", self.dev)


class NvidiaNic(object):
    """ A class of nvidia nic contains pci, device ID and device PSID
    """

    def __init__(self, dev_pci, dev_id, dev_psid):
        self.dev = dev_pci
        self.dev_id = dev_id
        self.dev_psid = dev_psid


class NvidiaNics(object):
    """ Discover and retrieve Nvidia Nics on the system.
    Can be used as an iterator once discover has been called.
    """

    def __init__(self):
        self._devs = []

    def discover(self):
        """ Discover Nvidia Nics in the system.
        :return: None
        """
        if self._devs:
            return self._devs
        devs = []
        cmd = ['lspci', '-Dn', '-d', '15b3:']
        out = run_command(*cmd)
        for line in out.split('\n'):
            if not line:
                continue
            dev_pci = line.split()[0]
            dev_id = line.split('15b3:')[1].split()[0]
            dev_ops = NvidiaNicFirmwareOps(dev_pci)
            dev_psid = dev_ops.get_nic_psid()
            devs.append(NvidiaNic(dev_pci, dev_id, dev_psid))
        self._devs = devs

    def __iter__(self):
        return self._devs.__iter__()


class NvidiaNicFirmwareBinary(object):
    def __init__(self, local_bin_path):
        self.bin_path = local_bin_path
        self.image_info = {}

    def get_info(self):
        """ Get firmware information from binary
        Caller should wrap this call under try catch to skip non compliant
        firmware binaries.
        :return: dict of firmware image attributes
        """
        if self.image_info.get('file_path', '') == self.bin_path:
            return self.image_info
        self.image_info = {'file_path': self.bin_path}
        cmd = ['mstflint', '-i', self.bin_path, 'query']
        out = run_command(*cmd)
        self.image_info.update(parse_mstflint_query_output(out))
        return self.image_info


class NvidiaFirmwareBinariesFetcher(object):
    """ A class for fetching firmware binaries form a directory
    provided by a URL link
    Note: URL MUST point to a directory and end with '/'
    e.g http://www.mysite.com/nvidia_fw_bins/
    """
    dest_dir = tempfile.mkdtemp(suffix="openstack_nvidia_firmware")

    class FileHTMLParser(html_parser.HTMLParser):
        """ A crude HTML Parser to extract files from an HTTP response.
        """

        def __init__(self, suffix):
            # HTMLParser is Old style class dont use super() method
            html_parser.HTMLParser.__init__(self)
            self.matches = []
            self.suffix = suffix

        def handle_starttag(self, tag, attrs):
            for name, val in attrs:
                if name == 'href' and val.endswith(self.suffix):
                    self.matches.append(val)

    def __init__(self, url):
        self.url = url

    def __del__(self):
        self._cleanup_dest_dir()

    def _cleanup_dest_dir(self):
        if os.path.exists(NvidiaFirmwareBinariesFetcher.dest_dir):
            shutil.rmtree(NvidiaFirmwareBinariesFetcher.dest_dir)

    def _get_file_from_url(self, file_name):
        try:
            full_path = self.url + "/" + file_name
            LOG.info("Downloading file: %s to %s", full_path,
                     NvidiaFirmwareBinariesFetcher.dest_dir)
            url_data = urlRequest.urlopen(full_path)
        except urlError.HTTPError as e:
            LOG.error("Failed to download data: %s", str(e))
            raise e
        dest_file_path = os.path.join(NvidiaFirmwareBinariesFetcher.dest_dir,
                                      file_name)
        with open(dest_file_path, 'wb') as f:
            f.write(url_data.read())
        return dest_file_path

    def _get_file_create_bin_obj(self, file_name, fw_bins):
        """ This wrapper method will download a firmware binary,
        create NvidiaNicFirmwareBinary object and append to the provided
        fw_bins list.
        :return: None
        """
        try:
            dest_file_path = self._get_file_from_url(file_name)
            fw_bin = NvidiaNicFirmwareBinary(dest_file_path)
            # Note: Pre query image, to skip incompatible files
            # in case of Error
            fw_bin.get_info()
            fw_bins.append(fw_bin)
        except Exception as e:
            LOG.warning("Failed to download and query %s, skipping file. "
                        "%s", file_name, str(e))

    def get_firmware_binaries(self):
        """ Get Firmware binaries
        :return: list containing the files downloaded
        """
        # get list of files
        # download into dest_dir
        # for each file, create NvidiaNicFirmwareBinary
        # return list of the NvidiaNicFirmwareBinary
        if not self.url.endswith('/'):
            LOG.error("Bad URL provided (%s), expected URL to be a directory",
                      self.url)
            raise RuntimeError('Failed to get firmware binaries, '
                               'expected directory URL path '
                               '(e.g "http://<your_ip>/nvidia_fw_bins/"). '
                               'Given URL path: %s', self.url)
        try:
            index_data = str(urlRequest.urlopen(self.url).read())
        except urlError.HTTPError as err:
            LOG.error(err)
            raise err
        parser = NvidiaFirmwareBinariesFetcher.FileHTMLParser(suffix=".bin")
        parser.feed(index_data)
        parser.close()
        if not parser.matches:
            LOG.warning("No bin Files found in the provided URL: %s", self.url)
        fw_bins = []
        threads = []
        for file_name in parser.matches:
            # TODO(adrianc) fetch files async with co-routines,
            # may need to limit thread count
            t = threading.Thread(target=self._get_file_create_bin_obj,
                                 args=(file_name, fw_bins))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        return fw_bins


def read_yaml_cfgs(YAML_CONFIG):
    """ Read config yaml file from a url and return list of cfgs
    
    :param YAML_CONFIG: 
    :return: list of cfgs 
    """
    response = urlRequest.urlopen(YAML_CONFIG)
    cfgs = yaml.load(response)
    return cfgs


def filter_cfgs(nvidia_nics, cfgs):
    pcis_to_be_processed = {}
    force_update_dict = {}
    for cfg in cfgs:
        seen_nics = set()
        temp_pci_list = []
        if cfg.get("pcis_list"):
            pci_set = set(cfg.get("pcis_list"))
            for dev in nvidia_nics:
                if dev.dev in pci_set:
                    temp_pci_list.append(dev)

        elif cfg.get("psids_list"):
            psid_set = set(cfg.get("psids_list"))
            for dev in nvidia_nics:
                if dev.dev_psid in psid_set:
                    temp_pci_list.append(dev)
        else:
            for dev in nvidia_nics:
                if dev.dev_id == cfg.get("device_id"):
                    temp_pci_list.append(dev)

        for dev in temp_pci_list:
            params = {}
            force_fw_update = False
            prefix = dev.dev[:-1]
            is_seen_nic = prefix in seen_nics
            first_device = prefix + "0"
            if not is_seen_nic:
                seen_nics.add(prefix)
                if cfg.get("general_config"):
                    params.update(cfg.get("general_config"))
                    print((cfg.get("general_config")))
                # read force_fw_update only for the first time you see one port of the prefix
            force_update_dict[first_device] = force_update_dict.get(first_device) or cfg.get("force_fw_update", False)

            is_first_device = dev.dev[-1] == '0'
            if is_first_device and cfg.get("device0_config"):
                params.update(cfg.get("device0_config"))
            elif not is_first_device and cfg.get("device1_config"):
                params.update(cfg.get("device1_config"))

            # dev is known and params are knowى
            # filter out already set configs
            # read existing fw params (params)
            if params:
                if pcis_to_be_processed.get(dev.dev):
                    pcis_to_be_processed[dev.dev].update(params)
                else:
                    pcis_to_be_processed[dev.dev] = params

    return pcis_to_be_processed, force_update_dict


class NvidiaNicConfig(object):
    """ Get/Set Nvidia nics configurations
    """

    def __init__(self, pci_dev):
        self.pci_dev = pci_dev
        self._tool_confs = None
        # NOTE(adrianc) ATM contains only array type parameter metadata

    def _mstconfig_parse_data(self, data):
        # Parsing the mstconfig out to json
        data = list(filter(None, data.split('\n')))
        r = {}
        c = 0
        for line in data:
            c += 1
            if 'Configurations:' in line:
                break
        for i in range(c, len(data)):
            d = list(filter(None, data[i].strip().split()))
            r[d[0]] = d[1]
        return r

    def get_device_conf_dict(self, *args):
        """ Get device Configurations
        :param param_name: if provided retireve only given configuration
        :return:  dict {"PARAM_NAME": "Param value", ....}
        """
        LOG.info("Getting configurations for device: %s" % self.pci_dev)
        cmd = ["mstconfig", "-d", self.pci_dev, "q"]
        if args:
            cmd.extend(args)
        out = run_command(*cmd)
        return self._mstconfig_parse_data(out)

    def param_supp_by_config_tool(self, param_name):
        """ Check if configuration tool supports the provided configuration
        parameter.
        :param param_name: configuration name
        :return: bool
        """
        if self._tool_confs is None:
            self._tool_confs = run_command(
                "mstconfig", "-d", self.pci_dev, "i")
        # trim any array index if present
        indexed_param = re.match(ARRAY_PARAM_REGEX, param_name)
        if indexed_param:
            param_name = indexed_param.group('param_name')
        return param_name in self._tool_confs

    def set_config(self, conf_dict):
        """ Set device configurations
        :param conf_dict: a dictionary of:
                          {"PARAM_NAME": "Param value to set", ...}
        :return: None
        """
        current_mlx_config = self.get_device_conf_dict()
        params_to_set = []
        for key, value in conf_dict.items():
            if not self.param_supp_by_config_tool(key):
                LOG.error(
                    "Configuraiton: %s is not supported by mstconfig,"
                    " please update to the latest mstflint package." % key)
                continue
            if current_mlx_config.get(key):
                if str(value).lower() not in str(current_mlx_config.get(key)).lower():
                    # Aggregate all configurations required to be modified
                    params_to_set.append("%s=%s" % (key, value))
                else:
                    LOG.info("value of %s for device %s is already configured as %s, no need to update it" % (
                        key, self.pci_dev, value))
            else:
                LOG.debug("config %s for device %s is not supported with current fw, skipping setting it..." % (
                    key, self.pci_dev))
        if params_to_set:
            cmd = ["mstconfig", "-d", self.pci_dev, "-y", "set"]
            cmd.extend(params_to_set)
            LOG.info("Setting configurations for device: %s" % self.pci_dev)
            run_command(*cmd)
            LOG.info("Set device configurations: Setting %s done successfully",
                     " ".join(params_to_set))
        else:
            LOG.info("Set device configurations: No operation required")


def fw_update_if_needed(psid_map, force_update_dict):
    for dev, force_update in force_update_dict.items():
        try:
            LOG.info("Processing Device: %s for update", dev)
            dev_ops = NvidiaNicFirmwareOps(dev)
            dev_query = dev_ops.query_device()
            dev_psid = dev_query['psid']
            if dev_psid in psid_map:
                if force_update or dev_ops.need_update(psid_map[dev_psid]):
                    dev_ops.burn_firmware(psid_map[dev_psid]['file_path'])
                else:
                    LOG.info("Firmware update is not required for Device.")
            else:
                LOG.info("No firmware binary found for device %s with "
                         "PSID: %s, skipping...", dev, dev_psid)
            # check if reset is required.
            # Note: device Reset is required if a newer firmware version was burnt
            # and current firmware does not support some mandatory configurations.
            if dev_ops.need_reset_before_config():
                dev_ops.reset_device()
        except Exception as e:
            LOG.error("Failed to process device %s. %s", dev, str(e))


def set_devices_config(psid_map, pcis_to_be_processed):
    for dev, params in pcis_to_be_processed.items():
        try:
            LOG.info("Processing Device: %s for setting config", dev)
            device_config = NvidiaNicConfig(dev)
            # set device configurations
            device_config.set_config(params)
            LOG.info("Device %s processed successfully.", dev)
        except Exception as e:
            LOG.error("Failed to process device %s. %s", dev, str(e))


def process_devices(psid_map, pcis_to_be_processed, force_update_dict):
    fw_update_if_needed(psid_map, force_update_dict)

    set_devices_config(psid_map, pcis_to_be_processed)


def get_psid_map(BIN_DIR_URL):
    psid_map = {}
    if BIN_DIR_URL:
        binary_getter = NvidiaFirmwareBinariesFetcher(BIN_DIR_URL)
        fw_binaries = binary_getter.get_firmware_binaries()
        for fw_bin in fw_binaries:
            image_info = fw_bin.get_info()
            if psid_map.get(image_info['psid']):
                if psid_map[image_info['psid']]['fw_ver'] < image_info['fw_ver']:
                    psid_map[image_info['psid']] = image_info
            else:
                psid_map[image_info['psid']] = image_info
    return psid_map


def main(BIN_DIR_URL, YAML_CONFIG):
    check_prereq()
    nvidia_nics = NvidiaNics()
    nvidia_nics.discover()
    psid_map = get_psid_map(BIN_DIR_URL)
    cfgs = read_yaml_cfgs(YAML_CONFIG)
    pcis_to_be_processed, force_update_dict = filter_cfgs(nvidia_nics, cfgs)
    process_devices(psid_map, pcis_to_be_processed, force_update_dict)


BIN_DIR_URL = 'http://10.7.12.161/fw/'
YAML_CONFIG = 'http://10.7.12.161/config.yaml'
main(BIN_DIR_URL, YAML_CONFIG)


# Copyright (C) 2017 Intel Corporation
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

from oslo_concurrency import processutils
from oslo_log import log as logging

from ironic_python_agent import utils


LOG = logging.getLogger(__name__)


def collect_dmidecode_info(data, failures):
    """Collect detailed processor, memory and bios info.

    The data is gathered using dmidecode utility.

    :param data: mutable dict that we'll send to inspector
    :param failures: AccumulatedFailures object
    """
    try:
        shret, _err = utils.execute('dmidecode', '-t', 'bios',
                                    '-t', 'processor', '-t', 'memory')
    except (processutils.ProcessExecutionError, OSError) as exc:
        failures.add('failed to run dmidecode: %s', exc)
        return

    data['dmi'] = {}
    try:
        data['dmi'] = parse_dmi(shret)
    except (ValueError, IndexError) as exc:
        LOG.warning('Failed to collect dmidecode info: %s', exc)


def parse_dmi(data):
    """Parse the dmidecode output.

    Returns a dict.
    """
    TYPE = {
        'bios': 0,
        'cpu': 4,
        'memory': 16,
        'devices': 17,
    }

    dmi_info = {
        'bios': {},
        'cpu': [],
        'memory': {'devices': []},
    }

    memorydata, devicedata = [], []

    # Dmi data blocks are separated by a blank line.
    # First line in each block starts with 'Handle 0x'.
    for infoblock in data.split('\n\n'):
        if not len(infoblock):
            continue

        if not infoblock.startswith('Handle 0x'):
            continue

        try:
            # Determine DMI type value. Handle line will look like this:
            # Handle 0x0018, DMI type 17, 27 bytes
            dmi_type = int(infoblock.split(',', 2)[1].strip()[
                           len('DMI type'):])
        except (ValueError, IndexError) as exc:
            LOG.warning('Failed to parse Handle type in dmi output: %s',
                        exc)
            continue

        if dmi_type in TYPE.values():
            sectiondata = _parse_handle_block(infoblock)

            if dmi_type == TYPE['bios']:
                dmi_info['bios'] = sectiondata
            elif dmi_type == TYPE['cpu']:
                dmi_info['cpu'].append(sectiondata)
            elif dmi_type == TYPE['memory']:
                memorydata.append(sectiondata)
            elif dmi_type == TYPE['devices']:
                devicedata.append(sectiondata)

    return _save_data(dmi_info, memorydata, devicedata)


def _parse_handle_block(lines):
    rows = {}
    list_value = False
    for line in lines.splitlines():
        line = line.strip()
        if ':' in line:
            list_value = False
            k, v = [i.strip() for i in line.split(':', 1)]
            if v:
                rows[k] = v
            else:
                rows[k] = []
                list_value = True
        elif 'Handle 0x' in line:
            rows['Handle'] = line
        elif list_value:
            rows[k].append(line)

    return rows


def _save_data(dmi_info, memorydata, devicedata):
    if memorydata:
        try:
            device_count = sum([int(d['Number Of Devices'])
                               for d in memorydata])
            dmi_info['memory'] = memorydata[0]
            dmi_info['memory']['Number Of Devices'] = device_count
            dmi_info['memory'].pop('Handle')
        except KeyError as exc:
            LOG.warning('Failed to process memory dmi data: %s', exc)
            raise

    if devicedata:
        dmi_info['memory']['devices'] = devicedata

    return dmi_info

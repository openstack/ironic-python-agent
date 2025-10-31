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
import copy
import re
from urllib import parse as urlparse

from oslo_log import log as logging
from oslo_utils import specs_matcher
from oslo_utils import strutils
from oslo_utils import units


LOG = logging.getLogger(__name__)


# A dictionary in the form {hint name: hint type}
VALID_ROOT_DEVICE_HINTS = {
    'size': int, 'model': str, 'wwn': str, 'serial': str, 'vendor': str,
    'wwn_with_extension': str, 'wwn_vendor_extension': str, 'name': str,
    'rotational': bool, 'hctl': str, 'by_path': str, 'tran': str,
}

ROOT_DEVICE_HINTS_GRAMMAR = specs_matcher.make_grammar()


def _extract_hint_operator_and_values(hint_expression, hint_name):
    """Extract the operator and value(s) of a root device hint expression.

    A root device hint expression could contain one or more values
    depending on the operator. This method extracts the operator and
    value(s) and returns a dictionary containing both.

    :param hint_expression: The hint expression string containing value(s)
                            and operator (optionally).
    :param hint_name: The name of the hint. Used for logging.
    :raises: ValueError if the hint_expression is empty.
    :returns: A dictionary containing:

        :op: The operator. An empty string in case of None.
        :values: A list of values stripped and converted to lowercase.
    """
    expression = str(hint_expression).strip().lower()
    if not expression:
        raise ValueError(f'Root device hint {hint_name} expression is empty')

    # parseString() returns a list of tokens which the operator (if
    # present) is always the first element.
    ast = ROOT_DEVICE_HINTS_GRAMMAR.parseString(expression)
    if len(ast) <= 1:
        # hint_expression had no operator
        return {'op': '', 'values': [expression]}

    op = ast[0]
    return {'values': [v.strip() for v in re.split(op, expression) if v],
            'op': op}


def _normalize_hint_expression(hint_expression, hint_name):
    """Normalize a string type hint expression.

    A string-type hint expression contains one or more operators and
    one or more values: [<op>] <value> [<op> <value>]*. This normalizes
    the values by url-encoding white spaces and special characters. The
    operators are not normalized. For example: the hint value of "<or>
    foo bar <or> bar" will become "<or> foo%20bar <or> bar".

    :param hint_expression: The hint expression string containing value(s)
                            and operator (optionally).
    :param hint_name: The name of the hint. Used for logging.
    :raises: ValueError if the hint_expression is empty.
    :returns: A normalized string.
    """
    hdict = _extract_hint_operator_and_values(hint_expression, hint_name)
    result = hdict['op'].join([' %s ' % urlparse.quote(t)
                               for t in hdict['values']])
    return (hdict['op'] + result).strip()


def _append_operator_to_hints(root_device):
    """Add an equal (s== or ==) operator to the hints.

    For backwards compatibility, for root device hints where no operator
    means equal, this method adds the equal operator to the hint. This is
    needed when using oslo.utils.specs_matcher methods.

    :param root_device: The root device hints dictionary.
    """
    for name, expression in root_device.items():
        # NOTE(lucasagomes): The specs_matcher from oslo.utils does not
        # support boolean, so we don't need to append any operator
        # for it.
        if VALID_ROOT_DEVICE_HINTS[name] is bool:
            continue

        expression = str(expression)
        ast = ROOT_DEVICE_HINTS_GRAMMAR.parseString(expression)
        if len(ast) > 1:
            continue

        op = 's== %s' if VALID_ROOT_DEVICE_HINTS[name] is str else '== %s'
        root_device[name] = op % expression

    return root_device


def parse_root_device_hints(root_device):
    """Parse the root_device property of a node.

    Parses and validates the root_device property of a node. These are
    hints for how a node's root device is created. The 'size' hint
    should be a positive integer. The 'rotational' hint should be a
    Boolean value.

    :param root_device: the root_device dictionary from the node's property.
    :returns: a dictionary with the root device hints parsed or
              None if there are no hints.
    :raises: ValueError, if some information is invalid.

    """
    if not root_device:
        return

    root_device = copy.deepcopy(root_device)

    invalid_hints = set(root_device) - set(VALID_ROOT_DEVICE_HINTS)
    if invalid_hints:
        raise ValueError('The hints "%(invalid_hints)s" are invalid. '
                         'Valid hints are: "%(valid_hints)s"' %
                         {'invalid_hints': ', '.join(invalid_hints),
                          'valid_hints': ', '.join(VALID_ROOT_DEVICE_HINTS)})

    for name, expression in root_device.items():
        hint_type = VALID_ROOT_DEVICE_HINTS[name]
        if hint_type is str:
            if not isinstance(expression, str):
                raise ValueError(
                    'Root device hint "%(name)s" is not a string value. '
                    'Hint expression: %(expression)s' %
                    {'name': name, 'expression': expression})
            root_device[name] = _normalize_hint_expression(expression, name)

        elif hint_type is int:
            for v in _extract_hint_operator_and_values(expression,
                                                       name)['values']:
                try:
                    integer = int(v)
                except ValueError:
                    raise ValueError(
                        'Root device hint "%(name)s" is not an integer '
                        'value. Current value: %(expression)s' %
                        {'name': name, 'expression': expression})

                if integer <= 0:
                    raise ValueError(
                        'Root device hint "%(name)s" should be a positive '
                        'integer. Current value: %(expression)s' %
                        {'name': name, 'expression': expression})

        elif hint_type is bool:
            try:
                root_device[name] = strutils.bool_from_string(
                    expression, strict=True)
            except ValueError:
                raise ValueError(
                    'Root device hint "%(name)s" is not a Boolean value. '
                    'Current value: %(expression)s' %
                    {'name': name, 'expression': expression})

    return _append_operator_to_hints(root_device)


def find_devices_by_hints(devices, root_device_hints):
    """Find all devices that match the root device hints.

    Try to find devices that match the root device hints. In order
    for a device to be matched it needs to satisfy all the given hints.

    :param devices: A list of dictionaries representing the devices
                    containing one or more of the following keys:

        :name: (String) The device name, e.g /dev/sda
        :size: (Integer) Size of the device in *bytes*
        :model: (String) Device model
        :vendor: (String) Device vendor name
        :serial: (String or List[String]) Device serial number(s)
        :wwn: (String or List[String]) Unique storage identifier(s)
        :wwn_with_extension: (String or List[String]): Unique storage
                             identifier(s) with the vendor extension appended
        :wwn_vendor_extension: (String or List[String]): United vendor
                               storage identifier(s)
        :rotational: (Boolean) Whether it's a rotational device or
                     not. Useful to distinguish HDDs (rotational) and SSDs
                     (not rotational).
        :hctl: (String): The SCSI address: Host, channel, target and lun.
                         For example: '1:0:0:0'.
        :by_path: (String): The alternative device name,
                  e.g. /dev/disk/by-path/pci-0000:00

    :param root_device_hints: A dictionary with the root device hints.
    :raises: ValueError, if some information is invalid.
    :returns: A generator with all matching devices as dictionaries.
    """
    LOG.debug('Trying to find devices from "%(devs)s" that match the '
              'device hints "%(hints)s"',
              {'devs': ', '.join([d.get('name') for d in devices]),
               'hints': root_device_hints})
    parsed_hints = parse_root_device_hints(root_device_hints)
    for dev in devices:
        device_name = dev.get('name')

        for hint in parsed_hints:
            hint_type = VALID_ROOT_DEVICE_HINTS[hint]
            device_value = dev.get(hint)
            hint_value = parsed_hints[hint]

            # Handle device attributes that are a list of strings
            # (serial, wwn, wwn_with_extension, and wwn_vendor_extension).
            if hint_type is str and isinstance(device_value, list):
                # NOTE(mostepha): Device value is a list. Consider it matched
                # if any value in the list matches the hint.
                device_values = [v for v in device_value if v is not None]
                if not device_values:
                    LOG.warning(
                        'The attribute "%(attr)s" of the device "%(dev)s" '
                        'has an empty value. Skipping device.',
                        {'attr': hint, 'dev': device_name})
                    break

                matched = False
                for val in device_values:
                    try:
                        normalized_val = _normalize_hint_expression(val, hint)
                        if specs_matcher.match(normalized_val, hint_value):
                            LOG.info('The attribute "%(attr)s" of device '
                                     '"%(dev)s" matched hint %(hint)s with '
                                     'value "%(value)s"',
                                     {'attr': hint, 'dev': device_name,
                                      'hint': hint_value, 'value': val})
                            matched = True
                            break
                    except ValueError:
                        # Skip invalid/empty values in the list
                        continue

                # Continue to next hint if any value matched. Otherwise, break
                # and try the next device.
                if matched:
                    continue
                else:
                    LOG.info('None of the values %(values)s for attribute '
                             '"%(attr)s" of device "%(dev)s" match the hint '
                             '%(hint)s',
                             {'values': device_values, 'attr': hint,
                              'dev': device_name, 'hint': hint_value})
                    break

            if hint_type is str:
                try:
                    device_value = _normalize_hint_expression(device_value,
                                                              hint)
                except ValueError:
                    LOG.warning(
                        'The attribute "%(attr)s" of the device "%(dev)s" '
                        'has an empty value. Skipping device.',
                        {'attr': hint, 'dev': device_name})
                    break

            if hint == 'size':
                # Since we don't support units yet we expect the size
                # in GiB for now
                device_value = device_value / units.Gi

            LOG.debug('Trying to match the device hint "%(hint)s" '
                      'with a value of "%(hint_value)s" against the same '
                      'device\'s (%(dev)s) attribute with a value of '
                      '"%(dev_value)s"', {'hint': hint, 'dev': device_name,
                                          'hint_value': hint_value,
                                          'dev_value': device_value})

            # NOTE(lucasagomes): Boolean hints are not supported by
            # specs_matcher.match(), so we need to do the comparison
            # ourselves
            if hint_type is bool:
                try:
                    device_value = strutils.bool_from_string(device_value,
                                                             strict=True)
                except ValueError:
                    LOG.warning('The attribute "%(attr)s" (with value '
                                '"%(value)s") of device "%(dev)s" is not '
                                'a valid Boolean. Skipping device.',
                                {'attr': hint, 'value': device_value,
                                 'dev': device_name})
                    break
                if device_value == hint_value:
                    continue

            elif specs_matcher.match(device_value, hint_value):
                continue

            LOG.debug('The attribute "%(attr)s" (with value "%(value)s") '
                      'of device "%(dev)s" does not match the hint %(hint)s',
                      {'attr': hint, 'value': device_value,
                       'dev': device_name, 'hint': hint_value})
            break
        else:
            yield dev


def match_root_device_hints(devices, root_device_hints):
    """Try to find a device that matches the root device hints.

    Try to find a device that matches the root device hints. In order
    for a device to be matched it needs to satisfy all the given hints.

    :param devices: A list of dictionaries representing the devices
                    containing one or more of the following keys:

        :name: (String) The device name, e.g /dev/sda
        :size: (Integer) Size of the device in *bytes*
        :model: (String) Device model
        :vendor: (String) Device vendor name
        :serial: (String or List[String]) Device serial number(s)
        :wwn: (String or List[String]) Unique storage identifier(s)
        :wwn_with_extension: (String or List[String]): Unique storage
                             identifier(s) with the vendor extension appended
        :wwn_vendor_extension: (String or List[String]): United vendor
                               storage identifier(s)
        :rotational: (Boolean) Whether it's a rotational device or
                     not. Useful to distinguish HDDs (rotational) and SSDs
                     (not rotational).
        :hctl: (String): The SCSI address: Host, channel, target and lun.
                         For example: '1:0:0:0'.
        :by_path: (String): The alternative device name,
                  e.g. /dev/disk/by-path/pci-0000:00

    :param root_device_hints: A dictionary with the root device hints.
    :raises: ValueError, if some information is invalid.
    :returns: The first device to match all the hints or None.
    """
    try:
        dev = next(find_devices_by_hints(devices, root_device_hints))
    except StopIteration:
        LOG.warning('No device found that matches the root device hints %s',
                    root_device_hints)
    else:
        LOG.info('Root device found! The device "%s" matches the root '
                 'device hints %s', dev, root_device_hints)
        return dev

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

from ironic_python_agent import device_hints
from ironic_python_agent.tests.unit import base


class ParseRootDeviceTestCase(base.IronicAgentTest):

    def test_parse_root_device_hints_without_operators(self):
        root_device = {
            'wwn': '123456', 'model': 'FOO model', 'size': 12345,
            'serial': 'foo-serial', 'vendor': 'foo VENDOR with space',
            'name': '/dev/sda', 'wwn_with_extension': '123456111',
            'wwn_vendor_extension': '111', 'rotational': True,
            'hctl': '1:0:0:0', 'by_path': '/dev/disk/by-path/1:0:0:0'}
        result = device_hints.parse_root_device_hints(root_device)
        expected = {
            'wwn': 's== 123456', 'model': 's== foo%20model',
            'size': '== 12345', 'serial': 's== foo-serial',
            'vendor': 's== foo%20vendor%20with%20space',
            'name': 's== /dev/sda', 'wwn_with_extension': 's== 123456111',
            'wwn_vendor_extension': 's== 111', 'rotational': True,
            'hctl': 's== 1%3A0%3A0%3A0',
            'by_path': 's== /dev/disk/by-path/1%3A0%3A0%3A0'}
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_with_operators(self):
        root_device = {
            'wwn': 's== 123456', 'model': 's== foo MODEL', 'size': '>= 12345',
            'serial': 's!= foo-serial', 'vendor': 's== foo VENDOR with space',
            'name': '<or> /dev/sda <or> /dev/sdb',
            'wwn_with_extension': 's!= 123456111',
            'wwn_vendor_extension': 's== 111', 'rotational': True,
            'hctl': 's== 1:0:0:0', 'by_path': 's== /dev/disk/by-path/1:0:0:0'}

        # Validate strings being normalized
        expected = copy.deepcopy(root_device)
        expected['model'] = 's== foo%20model'
        expected['vendor'] = 's== foo%20vendor%20with%20space'
        expected['hctl'] = 's== 1%3A0%3A0%3A0'
        expected['by_path'] = 's== /dev/disk/by-path/1%3A0%3A0%3A0'

        result = device_hints.parse_root_device_hints(root_device)
        # The hints already contain the operators, make sure we keep it
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_string_compare_operator_name(self):
        root_device = {'name': 's== /dev/sdb'}
        # Validate strings being normalized
        expected = copy.deepcopy(root_device)
        result = device_hints.parse_root_device_hints(root_device)
        # The hints already contain the operators, make sure we keep it
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_no_hints(self):
        result = device_hints.parse_root_device_hints({})
        self.assertIsNone(result)

    def test_parse_root_device_hints_convert_size(self):
        for size in (12345, '12345'):
            result = device_hints.parse_root_device_hints({'size': size})
            self.assertEqual({'size': '== 12345'}, result)

    def test_parse_root_device_hints_invalid_size(self):
        for value in ('not-int', -123, 0):
            self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                              {'size': value})

    def test_parse_root_device_hints_int_or(self):
        expr = '<or> 123 <or> 456 <or> 789'
        result = device_hints.parse_root_device_hints({'size': expr})
        self.assertEqual({'size': expr}, result)

    def test_parse_root_device_hints_int_or_invalid(self):
        expr = '<or> 123 <or> non-int <or> 789'
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'size': expr})

    def test_parse_root_device_hints_string_or_space(self):
        expr = '<or> foo <or> foo bar <or> bar'
        expected = '<or> foo <or> foo%20bar <or> bar'
        result = device_hints.parse_root_device_hints({'model': expr})
        self.assertEqual({'model': expected}, result)

    def _parse_root_device_hints_convert_rotational(self, values,
                                                    expected_value):
        for value in values:
            result = device_hints.parse_root_device_hints(
                {'rotational': value})
            self.assertEqual({'rotational': expected_value}, result)

    def test_parse_root_device_hints_convert_rotational(self):
        self._parse_root_device_hints_convert_rotational(
            (True, 'true', 'on', 'y', 'yes'), True)

        self._parse_root_device_hints_convert_rotational(
            (False, 'false', 'off', 'n', 'no'), False)

    def test_parse_root_device_hints_invalid_rotational(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'rotational': 'not-bool'})

    def test_parse_root_device_hints_invalid_wwn(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'wwn': 123})

    def test_parse_root_device_hints_invalid_wwn_with_extension(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'wwn_with_extension': 123})

    def test_parse_root_device_hints_invalid_wwn_vendor_extension(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'wwn_vendor_extension': 123})

    def test_parse_root_device_hints_invalid_model(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'model': 123})

    def test_parse_root_device_hints_invalid_serial(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'serial': 123})

    def test_parse_root_device_hints_invalid_vendor(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'vendor': 123})

    def test_parse_root_device_hints_invalid_name(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'name': 123})

    def test_parse_root_device_hints_invalid_hctl(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'hctl': 123})

    def test_parse_root_device_hints_invalid_by_path(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'by_path': 123})

    def test_parse_root_device_hints_non_existent_hint(self):
        self.assertRaises(ValueError, device_hints.parse_root_device_hints,
                          {'non-existent': 'foo'})

    def test_extract_hint_operator_and_values_single_value(self):
        expected = {'op': '>=', 'values': ['123']}
        self.assertEqual(
            expected, device_hints._extract_hint_operator_and_values(
                '>= 123', 'size'))

    def test_extract_hint_operator_and_values_multiple_values(self):
        expected = {'op': '<or>', 'values': ['123', '456', '789']}
        expr = '<or> 123 <or> 456 <or> 789'
        self.assertEqual(
            expected,
            device_hints._extract_hint_operator_and_values(expr, 'size'))

    def test_extract_hint_operator_and_values_multiple_values_space(self):
        expected = {'op': '<or>', 'values': ['foo', 'foo bar', 'bar']}
        expr = '<or> foo <or> foo bar <or> bar'
        self.assertEqual(
            expected,
            device_hints._extract_hint_operator_and_values(expr, 'model'))

    def test_extract_hint_operator_and_values_no_operator(self):
        expected = {'op': '', 'values': ['123']}
        self.assertEqual(
            expected,
            device_hints._extract_hint_operator_and_values('123', 'size'))

    def test_extract_hint_operator_and_values_empty_value(self):
        self.assertRaises(
            ValueError,
            device_hints._extract_hint_operator_and_values, '', 'size')

    def test_extract_hint_operator_and_values_integer(self):
        expected = {'op': '', 'values': ['123']}
        self.assertEqual(
            expected,
            device_hints._extract_hint_operator_and_values(123, 'size'))

    def test__append_operator_to_hints(self):
        root_device = {'serial': 'foo', 'size': 12345,
                       'model': 'foo model', 'rotational': True}
        expected = {'serial': 's== foo', 'size': '== 12345',
                    'model': 's== foo model', 'rotational': True}

        result = device_hints._append_operator_to_hints(root_device)
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_or(self):
        expr = '<or> foo <or> foo bar <or> bar'
        expected = '<or> foo <or> foo%20bar <or> bar'
        result = device_hints._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_in(self):
        expr = '<in> foo <in> foo bar <in> bar'
        expected = '<in> foo <in> foo%20bar <in> bar'
        result = device_hints._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_op_space(self):
        expr = 's== test string with space'
        expected = 's== test%20string%20with%20space'
        result = device_hints._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_op_no_space(self):
        expr = 's!= SpongeBob'
        expected = 's!= spongebob'
        result = device_hints._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_no_op_space(self):
        expr = 'no operators'
        expected = 'no%20operators'
        result = device_hints._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_no_op_no_space(self):
        expr = 'NoSpace'
        expected = 'nospace'
        result = device_hints._normalize_hint_expression(expr, 'model')
        self.assertEqual(expected, result)

    def test_normalize_hint_expression_empty_value(self):
        self.assertRaises(
            ValueError, device_hints._normalize_hint_expression, '', 'size')


class MatchRootDeviceTestCase(base.IronicAgentTest):

    def setUp(self):
        super(MatchRootDeviceTestCase, self).setUp()
        self.devices = [
            {'name': '/dev/sda', 'size': 64424509440, 'model': 'ok model',
             'serial': 'fakeserial', 'wwn': 'wwn_1'},
            {'name': '/dev/sdb', 'size': 128849018880, 'model': 'big model',
             'serial': ['veryfakeserial', 'alsoveryfakeserial'],
             'rotational': 'yes', 'wwn': ['wwn_2', 'wwn_2_ext']},
            {'name': '/dev/sdc', 'size': 10737418240, 'model': 'small model',
             'serial': 'veryveryfakeserial', 'rotational': False,
             'wwn': 'wwn_3'},
        ]

    def test_match_root_device_hints_one_hint(self):
        root_device_hints = {'size': '>= 70'}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_rotational(self):
        root_device_hints = {'rotational': False}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdc', dev['name'])

    def test_match_root_device_hints_rotational_convert_devices_bool(self):
        root_device_hints = {'size': '>=100', 'rotational': True}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_multiple_hints(self):
        root_device_hints = {'size': '>= 50', 'model': 's==big model',
                             'serial': 's==veryfakeserial'}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_multiple_hints2(self):
        root_device_hints = {
            'size': '<= 20',
            'model': '<or> model 5 <or> foomodel <or> small model <or>',
            'serial': 's== veryveryfakeserial'}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdc', dev['name'])

    def test_match_root_device_hints_multiple_hints3(self):
        root_device_hints = {'rotational': False, 'model': '<in> small'}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdc', dev['name'])

    def test_match_root_device_hints_list_of_wwns(self):
        root_device_hints = {'wwn': 'wwn_2_ext'}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_no_operators(self):
        root_device_hints = {'size': '120', 'model': 'big model',
                             'serial': 'veryfakeserial'}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertEqual('/dev/sdb', dev['name'])

    def test_match_root_device_hints_no_device_found(self):
        root_device_hints = {'size': '>=50', 'model': 's==foo'}
        dev = device_hints.match_root_device_hints(
            self.devices, root_device_hints)
        self.assertIsNone(dev)

    def test_match_root_device_hints_empty_device_attribute(self):
        empty_dev = [{'name': '/dev/sda', 'model': ' '}]
        dev = device_hints.match_root_device_hints(
            empty_dev, {'model': 'foo'})
        self.assertIsNone(dev)

    def test_find_devices_all(self):
        root_device_hints = {'size': '>= 10'}
        devs = list(device_hints.find_devices_by_hints(self.devices,
                                                       root_device_hints))
        self.assertEqual(self.devices, devs)

    def test_find_devices_none(self):
        root_device_hints = {'size': '>= 100500'}
        devs = list(device_hints.find_devices_by_hints(self.devices,
                                                       root_device_hints))
        self.assertEqual([], devs)

    def test_find_devices_name(self):
        root_device_hints = {'name': 's== /dev/sda'}
        devs = list(device_hints.find_devices_by_hints(self.devices,
                                                       root_device_hints))
        self.assertEqual([self.devices[0]], devs)

    def test_find_devices_single_serial(self):
        root_device_hints = {'serial': 's== fakeserial'}
        devs = list(device_hints.find_devices_by_hints(self.devices,
                                                       root_device_hints))
        self.assertEqual([self.devices[0]], devs)

    def test_find_devices_multiple_serials(self):
        root_device_hints = {'serial': 's== alsoveryfakeserial'}
        devs = list(device_hints.find_devices_by_hints(self.devices,
                                                       root_device_hints))
        self.assertEqual([self.devices[1]], devs)

    def test_find_devices_single_wwn(self):
        root_device_hints = {'wwn': 's== wwn_1'}
        devs = list(device_hints.find_devices_by_hints(self.devices,
                                                       root_device_hints))
        self.assertEqual([self.devices[0]], devs)

    def test_find_devices_multiple_wwns(self):
        root_device_hints = {'wwn': 's== wwn_2'}
        devs = list(device_hints.find_devices_by_hints(self.devices,
                                                       root_device_hints))
        self.assertEqual([self.devices[1]], devs)

#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
from unittest import mock

from ironic_lib.tests import base
from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import imageutils

from ironic_python_agent import errors
from ironic_python_agent import qemu_img


CONF = cfg.CONF


class ImageInfoTestCase(base.IronicLibTestCase):

    @mock.patch.object(os.path, 'exists', return_value=False, autospec=True)
    def test_image_info_path_doesnt_exist_disabled(self, path_exists_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        self.assertRaises(FileNotFoundError, qemu_img.image_info, 'noimg')
        path_exists_mock.assert_called_once_with('noimg')

    @mock.patch.object(utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    @mock.patch.object(imageutils, 'QemuImgInfo', autospec=True)
    @mock.patch.object(os.path, 'exists', return_value=True, autospec=True)
    def test_image_info_path_exists_disabled(self, path_exists_mock,
                                             image_info_mock, execute_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        qemu_img.image_info('img')
        path_exists_mock.assert_called_once_with('img')
        execute_mock.assert_called_once_with(
            ['env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info', 'img',
             '--output=json'], prlimit=mock.ANY)
        image_info_mock.assert_called_once_with('out', format='json')

    @mock.patch.object(utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    @mock.patch.object(imageutils, 'QemuImgInfo', autospec=True)
    @mock.patch.object(os.path, 'exists', return_value=True, autospec=True)
    def test_image_info_path_exists_safe(
            self, path_exists_mock, image_info_mock, execute_mock):
        qemu_img.image_info('img', source_format='qcow2')
        path_exists_mock.assert_called_once_with('img')
        execute_mock.assert_called_once_with(
            ['env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info', 'img',
             '--output=json', '-f', 'qcow2'],
            prlimit=mock.ANY
        )
        image_info_mock.assert_called_once_with('out', format='json')

    @mock.patch.object(utils, 'execute', return_value=('out', 'err'),
                       autospec=True)
    @mock.patch.object(imageutils, 'QemuImgInfo', autospec=True)
    @mock.patch.object(os.path, 'exists', return_value=True, autospec=True)
    def test_image_info_path_exists_unsafe(
            self, path_exists_mock, image_info_mock, execute_mock):
        # Call without source_format raises
        self.assertRaises(errors.InvalidImage,
                          qemu_img.image_info, 'img')
        # safety valve! Don't run **anything** against the image without
        # source_format unless specifically permitted
        path_exists_mock.assert_not_called()
        execute_mock.assert_not_called()
        image_info_mock.assert_not_called()


class ConvertImageTestCase(base.IronicLibTestCase):

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_disabled(self, execute_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        qemu_img.convert_image('source', 'dest', 'out_format')
        execute_mock.assert_called_once_with(
            'qemu-img', 'convert', '-O',
            'out_format', 'source', 'dest',
            run_as_root=False,
            prlimit=mock.ANY,
            use_standard_locale=True,
            env_variables={'MALLOC_ARENA_MAX': '3'})

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_flags_disabled(self, execute_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        qemu_img.convert_image('source', 'dest', 'out_format',
                               cache='directsync', out_of_order=True,
                               sparse_size='0')
        execute_mock.assert_called_once_with(
            'qemu-img', 'convert', '-O',
            'out_format', '-t', 'directsync',
            '-S', '0', '-W', 'source', 'dest',
            run_as_root=False,
            prlimit=mock.ANY,
            use_standard_locale=True,
            env_variables={'MALLOC_ARENA_MAX': '3'})

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries_disabled(self, execute_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        ret_err = 'qemu: qemu_thread_create: Resource temporarily unavailable'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            ('', ''),
        ]

        qemu_img.convert_image('source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries_alternate_error_disabled(self, exe_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        ret_err = 'Failed to allocate memory: Cannot allocate memory\n'
        exe_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            ('', ''),
        ]

        qemu_img.convert_image('source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        exe_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries_and_fails_disabled(self, execute_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        ret_err = 'qemu: qemu_thread_create: Resource temporarily unavailable'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err),
        ]

        self.assertRaises(processutils.ProcessExecutionError,
                          qemu_img.convert_image,
                          'source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_just_fails_disabled(self, execute_mock):
        CONF.set_override('disable_deep_image_inspection', True)
        ret_err = 'Aliens'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err),
        ]

        self.assertRaises(processutils.ProcessExecutionError,
                          qemu_img.convert_image,
                          'source', 'dest', 'out_format')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image(self, execute_mock):
        qemu_img.convert_image('source', 'dest', 'out_format',
                               source_format='fmt')
        execute_mock.assert_called_once_with(
            'qemu-img', 'convert', '-O',
            'out_format', '-f', 'fmt',
            'source', 'dest',
            run_as_root=False,
            prlimit=mock.ANY,
            use_standard_locale=True,
            env_variables={'MALLOC_ARENA_MAX': '3'})

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_flags(self, execute_mock):
        qemu_img.convert_image('source', 'dest', 'out_format',
                               cache='directsync', out_of_order=True,
                               sparse_size='0', source_format='fmt')
        execute_mock.assert_called_once_with(
            'qemu-img', 'convert', '-O',
            'out_format', '-t', 'directsync',
            '-S', '0', '-f', 'fmt', '-W', 'source', 'dest',
            run_as_root=False,
            prlimit=mock.ANY,
            use_standard_locale=True,
            env_variables={'MALLOC_ARENA_MAX': '3'})

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries(self, execute_mock):
        ret_err = 'qemu: qemu_thread_create: Resource temporarily unavailable'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            ('', ''),
        ]

        qemu_img.convert_image('source', 'dest', 'out_format',
                               source_format='fmt')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', '-f', 'fmt', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries_alternate_error(self, execute_mock):
        ret_err = 'Failed to allocate memory: Cannot allocate memory\n'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            ('', ''),
        ]

        qemu_img.convert_image('source', 'dest', 'out_format',
                               source_format='fmt')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', '-f', 'fmt', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_retries_and_fails(self, execute_mock):
        ret_err = 'qemu: qemu_thread_create: Resource temporarily unavailable'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err), ('', ''),
            processutils.ProcessExecutionError(stderr=ret_err),
        ]

        self.assertRaises(processutils.ProcessExecutionError,
                          qemu_img.convert_image,
                          'source', 'dest', 'out_format', source_format='fmt')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', '-f', 'fmt', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
            mock.call('sync'),
            convert_call,
            mock.call('sync'),
            convert_call,
        ])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_convert_image_just_fails(self, execute_mock):
        ret_err = 'Aliens'
        execute_mock.side_effect = [
            processutils.ProcessExecutionError(stderr=ret_err),
        ]

        self.assertRaises(processutils.ProcessExecutionError,
                          qemu_img.convert_image,
                          'source', 'dest', 'out_format', source_format='fmt')
        convert_call = mock.call('qemu-img', 'convert', '-O',
                                 'out_format', '-f', 'fmt', 'source', 'dest',
                                 run_as_root=False,
                                 prlimit=mock.ANY,
                                 use_standard_locale=True,
                                 env_variables={'MALLOC_ARENA_MAX': '3'})
        execute_mock.assert_has_calls([
            convert_call,
        ])

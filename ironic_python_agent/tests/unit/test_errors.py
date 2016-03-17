#    Copyright (C) 2015 Yahoo! Inc. All Rights Reserved.
#
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

from oslotest import base as test_base

from ironic_python_agent import errors

DETAILS = 'details'
SAME_CL_DETAILS = 'same_as_class_details'
DIFF_CL_DETAILS = 'different_from_class_details'
SAME_CL_MSG = 'same_as_class_message'
SAME_DETAILS = 'same_as_DETAILS'
DEFAULT_DETAILS = 'default_resterror_details'


class TestError(errors.RESTError):
    message = 'message'

    def __init__(self, details=None):
        # Follows the pattern seen in most in error classes
        super(TestError, self).__init__(details)


class TestErrors(test_base.BaseTestCase):

    def test_RESTError(self):
        e = errors.RESTError()
        d = e.serialize()

        self.assertEqual("RESTError", e.type)
        self.assertEqual(errors.RESTError.status_code, e.code)
        self.assertEqual(errors.RESTError.message, e.message)
        self.assertEqual(errors.RESTError.details, e.details)

        self.assertEqual("RESTError", d['type'])
        self.assertEqual(errors.RESTError.status_code, d['code'])
        self.assertEqual(errors.RESTError.message, d['message'])
        self.assertEqual(errors.RESTError.details, d['details'])

    def test_RESTError_details(self):
        e = errors.RESTError(DETAILS)
        self.assertEqual("RESTError", e.type)
        self.assertEqual(500, e.code)
        self.assertEqual(errors.RESTError.message, e.message)
        self.assertEqual(DETAILS, e.details)

    def _test_class(self, obj, check_details):
        """Test that the object is created correctly

        :param obj: object to be tested
        :param check_details: how to check the object's details value.
                             One of SAME_CL_DETAILS, DIFF_CL_DETAILS,
                             SAME_CL_MSG, SAME_DETAILS

        """
        obj_info = "object info = %s" % obj.__dict__
        cls = obj.__class__
        d = obj.serialize()

        self.assertEqual(cls.__name__, obj.type, obj_info)
        self.assertEqual(cls.status_code, obj.code, obj_info)
        self.assertEqual(cls.message, obj.message, obj_info)

        self.assertEqual(cls.__name__, d['type'], obj_info)
        self.assertEqual(cls.status_code, d['code'], obj_info)
        self.assertEqual(cls.message, d['message'], obj_info)
        self.assertEqual(obj.details, d['details'], obj_info)

        if check_details == SAME_CL_DETAILS:
            self.assertEqual(cls.details, obj.details, obj_info)
        elif check_details == DIFF_CL_DETAILS:
            self.assertNotEqual(cls.details, obj.details, obj_info)
        elif check_details == SAME_CL_MSG:
            self.assertEqual(cls.message, obj.details, obj_info)
        elif check_details == SAME_DETAILS:
            self.assertEqual(DETAILS, obj.details, obj_info)
        elif check_details == DEFAULT_DETAILS:
            self.assertEqual(errors.RESTError.details, obj.details, obj_info)
        else:
            self.fail("unexpected value for check_details: %(chk)s, %(info)s" %
                      {'info': obj_info, 'chk': check_details})

    def test_error_classes(self):
        cases = [(errors.InvalidContentError(DETAILS), SAME_DETAILS),
                 (errors.NotFound(), SAME_CL_DETAILS),
                 (errors.CommandExecutionError(DETAILS), SAME_DETAILS),
                 (errors.InvalidCommandError(DETAILS), SAME_DETAILS),
                 (errors.InvalidCommandParamsError(DETAILS), SAME_DETAILS),
                 (errors.RequestedObjectNotFoundError('type_descr', 'obj_id'),
                  DIFF_CL_DETAILS),
                 (errors.IronicAPIError(DETAILS), SAME_DETAILS),
                 (errors.HeartbeatError(DETAILS), SAME_DETAILS),
                 (errors.LookupNodeError(DETAILS), SAME_DETAILS),
                 (errors.LookupAgentIPError(DETAILS), SAME_DETAILS),
                 (errors.ImageDownloadError('image_id', DETAILS),
                     DIFF_CL_DETAILS),
                 (errors.ImageChecksumError(
                     'image_id', '/foo/image_id', 'incorrect', 'correct'),
                  DIFF_CL_DETAILS),
                 (errors.ImageWriteError('device', 'exit_code', 'stdout',
                                         'stderr'),
                  DIFF_CL_DETAILS),
                 (errors.ConfigDriveTooLargeError('filename', 'filesize'),
                  DIFF_CL_DETAILS),
                 (errors.ConfigDriveWriteError('device', 'exit_code', 'stdout',
                                               'stderr'),
                  DIFF_CL_DETAILS),
                 (errors.SystemRebootError('exit_code', 'stdout', 'stderr'),
                  DIFF_CL_DETAILS),
                 (errors.BlockDeviceEraseError(DETAILS), SAME_DETAILS),
                 (errors.BlockDeviceError(DETAILS), SAME_DETAILS),
                 (errors.VirtualMediaBootError(DETAILS), SAME_DETAILS),
                 (errors.UnknownNodeError(), DEFAULT_DETAILS),
                 (errors.UnknownNodeError(DETAILS), SAME_DETAILS),
                 (errors.HardwareManagerNotFound(), DEFAULT_DETAILS),
                 (errors.HardwareManagerNotFound(DETAILS), SAME_DETAILS),
                 (errors.HardwareManagerMethodNotFound('method'),
                  DIFF_CL_DETAILS),
                 (errors.IncompatibleHardwareMethodError(), DEFAULT_DETAILS),
                 (errors.IncompatibleHardwareMethodError(DETAILS),
                  SAME_DETAILS),
                 ]
        for (obj, check_details) in cases:
            self._test_class(obj, check_details)

    def test_error_string(self):
        err = TestError('test error')
        self.assertEqual('message: test error', str(err))
        self.assertEqual('TestError(\'message: test error\')', repr(err))

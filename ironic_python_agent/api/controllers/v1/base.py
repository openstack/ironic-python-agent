# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import six
from wsme import types as wtypes


class ExceptionType(wtypes.UserType):
    basetype = wtypes.DictType
    name = 'exception'

    def validate(self, value):
        if not isinstance(value, BaseException):
            raise ValueError('Value is not an exception')
        return value

    def tobasetype(self, value):
        """Turn an Exception into a dict."""
        return {
            'type': value.__class__.__name__,
            'code': getattr(value, 'status_code', 500),
            'message': str(value),
            'details': getattr(value, 'details', ''),
        }

    frombasetype = tobasetype


exception_type = ExceptionType()


class MultiType(wtypes.UserType):
    """A complex type that represents one or more types.

    Used for validating that a value is an instance of one of the types.

    :param \*types: Variable-length list of types.

    """
    def __init__(self, *types):
        self.types = types

    def __str__(self):
        return ' | '.join(map(str, self.types))

    def validate(self, value):
        for t in self.types:
            if t is wtypes.text and isinstance(value, wtypes.bytes):
                value = value.decode()
            if isinstance(value, t):
                return value
        else:
            raise ValueError(
                "Wrong type. Expected '{type}', got '{value}'".format(
                    type=self.types, value=type(value)))


json_type = MultiType(list, dict, six.integer_types, wtypes.text)


class APIBase(wtypes.Base):
    pass

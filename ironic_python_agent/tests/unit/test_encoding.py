#    Copyright (C) 2015 Intel Corporation
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

from ironic_python_agent import encoding


class SerializableTesting(encoding.Serializable):
    serializable_fields = ('jack', 'jill')

    def __init__(self, jack, jill):
        self.jack = jack
        self.jill = jill


class SerializableComparableTesting(encoding.SerializableComparable):
    serializable_fields = ('jack', 'jill')

    def __init__(self, jack, jill):
        self.jack = jack
        self.jill = jill


class TestSerializable(test_base.BaseTestCase):
    def test_baseclass_serialize(self):
        obj = encoding.Serializable()
        self.assertEqual({}, obj.serialize())

    def test_childclass_serialize(self):
        expected = {'jack': 'hello', 'jill': 'world'}
        obj = SerializableTesting('hello', 'world')
        self.assertEqual(expected, obj.serialize())


class TestSerializableComparable(test_base.BaseTestCase):

    def test_childclass_equal(self):
        obj1 = SerializableComparableTesting('hello', 'world')
        obj2 = SerializableComparableTesting('hello', 'world')
        self.assertEqual(obj1, obj2)

    def test_childclass_notequal(self):
        obj1 = SerializableComparableTesting('hello', 'world')
        obj2 = SerializableComparableTesting('hello', 'world2')
        self.assertNotEqual(obj1, obj2)

    def test_childclass_hash(self):
        # Ensure __hash__ is None
        obj = SerializableComparableTesting('hello', 'world')
        self.assertIsNone(obj.__hash__)

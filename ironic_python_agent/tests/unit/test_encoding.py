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

import json

from ironic_lib import exception as lib_exc

from ironic_python_agent import encoding
from ironic_python_agent.tests.unit import base


class SerializableTesting(encoding.Serializable):
    serializable_fields = ('jack', 'jill')

    def __init__(self, jack, jill):
        """
        Initialize the simulation.

        Args:
            self: (todo): write your description
            jack: (todo): write your description
            jill: (todo): write your description
        """
        self.jack = jack
        self.jill = jill


class SerializableComparableTesting(encoding.SerializableComparable):
    serializable_fields = ('jack', 'jill')

    def __init__(self, jack, jill):
        """
        Initialize the simulation.

        Args:
            self: (todo): write your description
            jack: (todo): write your description
            jill: (todo): write your description
        """
        self.jack = jack
        self.jill = jill


class TestSerializable(base.IronicAgentTest):
    def test_baseclass_serialize(self):
        """
        Serialize the base class serialize ().

        Args:
            self: (todo): write your description
        """
        obj = encoding.Serializable()
        self.assertEqual({}, obj.serialize())

    def test_childclass_serialize(self):
        """
        Serialize the serialize of the test.

        Args:
            self: (todo): write your description
        """
        expected = {'jack': 'hello', 'jill': 'world'}
        obj = SerializableTesting('hello', 'world')
        self.assertEqual(expected, obj.serialize())


class TestSerializableComparable(base.IronicAgentTest):

    def test_childclass_equal(self):
        """
        Test if the object s child classes.

        Args:
            self: (todo): write your description
        """
        obj1 = SerializableComparableTesting('hello', 'world')
        obj2 = SerializableComparableTesting('hello', 'world')
        self.assertEqual(obj1, obj2)

    def test_childclass_notequal(self):
        """
        Test if the child class.

        Args:
            self: (todo): write your description
        """
        obj1 = SerializableComparableTesting('hello', 'world')
        obj2 = SerializableComparableTesting('hello', 'world2')
        self.assertNotEqual(obj1, obj2)

    def test_childclass_hash(self):
        """
        Set the child hash of the childclass_hash.

        Args:
            self: (todo): write your description
        """
        # Ensure __hash__ is None
        obj = SerializableComparableTesting('hello', 'world')
        self.assertIsNone(obj.__hash__)


class TestEncoder(base.IronicAgentTest):

    encoder = encoding.RESTJSONEncoder()

    def test_encoder(self):
        """
        Serialize the test encoder

        Args:
            self: (todo): write your description
        """
        expected = {'jack': 'hello', 'jill': 'world'}
        obj = SerializableTesting('hello', 'world')
        self.assertEqual(expected, json.loads(self.encoder.encode(obj)))

    def test_ironic_lib(self):
        """
        Test whether the test.

        Args:
            self: (todo): write your description
        """
        obj = lib_exc.InstanceDeployFailure(reason='boom')
        encoded = json.loads(self.encoder.encode(obj))
        self.assertEqual(500, encoded['code'])
        self.assertEqual('InstanceDeployFailure', encoded['type'])
        self.assertIn('boom', encoded['message'])

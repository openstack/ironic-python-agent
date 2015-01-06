# Copyright 2011 Justin Santa Barbara
# Copyright 2012 Hewlett-Packard Development Company, L.P.
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

import errno
import os
import tempfile
import testtools

from oslo_concurrency import processutils

from ironic_python_agent import utils


class ExecuteTestCase(testtools.TestCase):
    """This class is a copy of the same class in openstack/ironic."""

    def test_retry_on_failure(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If stdin fails to get passed during one of the runs, make a note.
if ! grep -q foo
then
    echo 'failure' > "$1"
fi
# If stdin has failed to get passed during this or a previous run, exit early.
if grep failure "$1"
then
    exit 1
fi
runs="$(cat $1)"
if [ -z "$runs" ]
then
    runs=0
fi
runs=$(($runs + 1))
echo $runs > "$1"
exit 1
''')
            fp.close()
            os.chmod(tmpfilename, 0o755)
            try:
                self.assertRaises(processutils.ProcessExecutionError,
                                  utils.execute,
                                  tmpfilename, tmpfilename2, attempts=10,
                                  process_input='foo',
                                  delay_on_retry=False)
            except OSError as e:
                if e.errno == errno.EACCES:
                    self.skipTest("Permissions error detected. "
                                  "Are you running with a noexec /tmp?")
                else:
                    raise
            fp = open(tmpfilename2, 'r')
            runs = fp.read()
            fp.close()
            self.assertNotEqual(runs.strip(), 'failure', 'stdin did not '
                                                          'always get passed '
                                                          'correctly')
            runs = int(runs.strip())
            self.assertEqual(10, runs,
                              'Ran %d times instead of 10.' % (runs,))
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)

    def test_unknown_kwargs_raises_error(self):
        self.assertRaises(processutils.UnknownArgumentError,
                          utils.execute,
                          '/usr/bin/env', 'true',
                          this_is_not_a_valid_kwarg=True)

    def test_check_exit_code_boolean(self):
        utils.execute('/usr/bin/env', 'false', check_exit_code=False)
        self.assertRaises(processutils.ProcessExecutionError,
                          utils.execute,
                          '/usr/bin/env', 'false', check_exit_code=True)

    def test_no_retry_on_success(self):
        fd, tmpfilename = tempfile.mkstemp()
        _, tmpfilename2 = tempfile.mkstemp()
        try:
            fp = os.fdopen(fd, 'w+')
            fp.write('''#!/bin/sh
# If we've already run, bail out.
grep -q foo "$1" && exit 1
# Mark that we've run before.
echo foo > "$1"
# Check that stdin gets passed correctly.
grep foo
''')
            fp.close()
            os.chmod(tmpfilename, 0o755)
            try:
                utils.execute(tmpfilename,
                              tmpfilename2,
                              process_input='foo',
                              attempts=2)
            except OSError as e:
                if e.errno == errno.EACCES:
                    self.skipTest("Permissions error detected. "
                                  "Are you running with a noexec /tmp?")
                else:
                    raise
        finally:
            os.unlink(tmpfilename)
            os.unlink(tmpfilename2)

#!/bin/sh
# put other system startup commands here

#exec > /tmp/installlogs 2>&1
set -x

echo "Starting bootlocal script:"
date

export HOME=/root

# Maybe save some RAM?
#rm -rf /tmp/builtin

# Install IPA and dependecies
if ! type "ironic-python-agent" > /dev/null ; then
  python /tmp/get-pip.py --no-wheel --no-index --find-links=file:///tmp/wheelhouse ironic_python_agent
fi

# Run IPA
ironic-python-agent

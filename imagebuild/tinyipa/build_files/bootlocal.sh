#!/bin/sh
# put other system startup commands here

#exec > /tmp/installlogs 2>&1
set -x

echo "Starting bootlocal script:"
date

export HOME=/root

# Start SSHd
if [ -f /usr/local/etc/init.d/openssh ]; then
    echo "Starting OpenSSH server:"
    /usr/local/etc/init.d/openssh start
fi

# Maybe save some RAM?
#rm -rf /tmp/builtin

# Install IPA and dependecies
if ! type "ironic-python-agent" > /dev/null ; then
    python /tmp/get-pip.py --no-wheel --no-index --find-links=file:///tmp/wheelhouse ironic_python_agent
fi

export PYTHONOPTIMIZE=1

# Run IPA
echo "Starting Ironic Python Agent:"
date
ironic-python-agent 2>&1 | tee /var/log/ironic-python-agent.log

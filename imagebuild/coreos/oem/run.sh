#!/bin/bash

set -e

# CoreOS by default only has an OEM partition of 2GB. This isn't large enough
# for some images. If you need something larger, uncomment the following line
# to remount it with a larger size.
# Note: When CoreOS changes to r/w /, instead of remounting here, rootflags=
# in the kernelk command line will be used to set the size.
#mount -o remount,size=20G /media/state

cd /usr/share/oem/

mkdir -pm 0700 /home/core/.ssh

# TODO: Use proper https://github.com/coreos/init/blob/master/bin/update-ssh-keys script
if [[ -e authorized_keys ]]; then
  cat authorized_keys >> /home/core/.ssh/authorized_keys
fi

chown -R core:core /home/core/.ssh/

mkdir -p /media/state/ironic-python-agent
tar -x -C /media/state/ironic-python-agent -f container.tar.gz

systemctl enable --runtime /usr/share/oem/system/*
systemctl start ironic-python-agent.service

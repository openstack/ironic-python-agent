#!/bin/bash

set -e

# CoreOS by default only has an OEM partition of 2GB. This isn't large enough
# for some images. Remount it with a larger size. Note: When CoreOS changes to 
# r/w /, instead of remounting here, we'll use rootflags= to set the size.
mount -o remount,size=20G /media/state

cd /usr/share/oem/

mkdir -pm 0700 /home/core/.ssh

# TODO: Use proper https://github.com/coreos/init/blob/master/bin/update-ssh-keys script
if [[ -e authorized_keys ]]; then
  cat authorized_keys >> /home/core/.ssh/authorized_keys
fi

chown -R core:core /home/core/.ssh/

# We have to wait until docker is started to proceed
# In a perfect world I'd use inotifywait, but that doesn't exist on coreos
while [ ! -e /var/run/docker.sock ]; do
  sleep 1;
done

# TODO: Use docker import (and export the image) to shrink image size
docker load < container.tar.gz

systemctl enable --runtime /usr/share/oem/system/*
systemctl start teeth-agent.service

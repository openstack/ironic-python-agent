#!/bin/bash -xe
#
# This builds a CoreOS IPA image, assuming dependencies are installed
#
# The system this runs on needs these binaries available, most of which
# are installed by default on Ubuntu Trusty:
#  - docker
#  - gzip / gunzip
#  - uuidgen
#  - cpio
#  - find (gnu)
#  - grep
#  - gpg (to validate key of downloaded CoreOS image)
#
# Alternatively, run full_trusty_build.bash which will install
# all requirements then perform the build.

if [[ -x /usr/bin/docker.io ]]; then
    sudo ln -sf /usr/bin/docker.io /usr/local/bin/docker
fi
cd imagebuild/coreos
sudo pip install -r requirements.txt
sudo make clean
sudo make

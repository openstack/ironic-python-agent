#!/bin/bash -xe
#
# From a base-trusty node, this should build a CoreOS IPA image
# suitable for use in testing or production.
#
sudo apt-get update
sudo apt-get install -y docker.io
sudo ln -sf /usr/bin/docker.io /usr/local/bin/docker
sudo sed -i '$acomplete -F _docker docker' /etc/bash_completion.d/docker.io
cd imagebuild/coreos/
pwd
make
tar czf ../../ipa-coreos.tar.gz UPLOAD/coreos_production_pxe_image-oem.cpio.gz UPLOAD/coreos_production_pxe.vmlinuz

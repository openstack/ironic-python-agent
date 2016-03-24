#!/bin/bash -xe
#
# From a base-trusty node, this should build a CoreOS IPA image
# suitable for use in testing or production.
#
if [ -x "/usr/bin/apt-get" ]; then
    sudo -E apt-get update
    # apparmor is an undeclared dependency for docker on ubuntu
    # https://github.com/docker/docker/issues/9745
    sudo -E apt-get install -y docker.io apparmor
elif [ -x "/usr/bin/yum" ]; then
    sudo -E yum install -y docker-io gpg
else
    echo "No supported package manager installed on system. Supported: apt, yum"
    exit 1
fi

imagebuild/coreos/build_coreos_image.sh

BUILD_DIR=imagebuild/coreos/UPLOAD
tar czf ipa-coreos.tar.gz $BUILD_DIR/coreos_production_pxe_image-oem.cpio.gz $BUILD_DIR/coreos_production_pxe.vmlinuz

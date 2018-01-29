#!/bin/bash -xe
#
# From a base-trusty node, this should build a CoreOS IPA image
# suitable for use in testing or production.
#

BRANCH_PATH=${BRANCH_PATH:-master}
# NOTE(lucasagomes): List of dependencies for Red Hat systems
REDHAT_PACKAGES="docker-io gpg"

if [ -x "/usr/bin/apt-get" ]; then
    sudo -E apt-get update
    # apparmor is an undeclared dependency for docker on ubuntu
    # https://github.com/docker/docker/issues/9745
    sudo -E apt-get install -y docker.io apparmor cgroup-lite
elif [ -x "/usr/bin/dnf" ]; then
    sudo -E dnf install -y $REDHAT_PACKAGES
elif [ -x "/usr/bin/yum" ]; then
    sudo -E yum install -y $REDHAT_PACKAGES
else
    echo "No supported package manager installed on system. Supported: apt, yum, dnf"
    exit 1
fi

imagebuild/coreos/build_coreos_image.sh

BUILD_DIR=imagebuild/coreos/UPLOAD
if [ "$BRANCH_PATH" != "master" ]; then
    # add the branch name
    mv $BUILD_DIR/coreos_production_pxe_image-oem.cpio.gz $BUILD_DIR/coreos_production_pxe_image-oem-$BRANCH_PATH.cpio.gz
    mv $BUILD_DIR/coreos_production_pxe.vmlinuz $BUILD_DIR/coreos_production_pxe-$BRANCH_PATH.vmlinuz
else
    # in the past, we published master without branch name
    # copy the files in this case such that both are published
    cp $BUILD_DIR/coreos_production_pxe_image-oem.cpio.gz $BUILD_DIR/coreos_production_pxe_image-oem-$BRANCH_PATH.cpio.gz
    cp $BUILD_DIR/coreos_production_pxe.vmlinuz $BUILD_DIR/coreos_production_pxe-$BRANCH_PATH.vmlinuz
fi

# Generate checksum files
pushd $BUILD_DIR > /dev/null
for x in *.vmlinuz *.cpio.gz; do
    sha256sum $x > $x.sha256
done
popd > /dev/null

tar czf ipa-coreos-$BRANCH_PATH.tar.gz $BUILD_DIR/coreos_production_pxe_image-oem-$BRANCH_PATH.cpio.gz $BUILD_DIR/coreos_production_pxe-$BRANCH_PATH.vmlinuz
if [ "$BRANCH_PATH" = "master" ]; then
    # again, publish with and without the branch on master for historical reasons
    cp ipa-coreos-$BRANCH_PATH.tar.gz ipa-coreos.tar.gz
fi

# Generate checksum files
for x in *.tar.gz; do
    sha256sum $x > $x.sha256
done

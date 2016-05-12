#!/bin/bash

set -ex
WORKDIR=$(readlink -f $0 | xargs dirname)
BUILDDIR="$WORKDIR/tinyipabuild"
BUILD_AND_INSTALL_TINYIPA=${BUILD_AND_INSTALL_TINYIPA:-false}

CHROOT_PATH="/tmp/overides:/usr/local/sbin:/usr/local/bin:/apps/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CHROOT_CMD="sudo chroot $BUILDDIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy"

TC=1001
STAFF=50

echo "Building tinyipa:"

# Ensure we have an extended sudo to prevent the need to enter a password over
# and over again.
sudo -v

# If an old build directory exists remove it
if [ -d "$BUILDDIR" ]; then
    sudo rm -rf "$BUILDDIR"
fi

##############################################
# Download and Cache Tiny Core Files
##############################################

cd $WORKDIR/build_files
wget -N http://distro.ibiblio.org/tinycorelinux/6.x/x86_64/release/distribution_files/corepure64.gz
wget -N http://distro.ibiblio.org/tinycorelinux/6.x/x86_64/release/distribution_files/vmlinuz64
cd $WORKDIR

########################################################
# Build Required Python Dependecies in a Build Directory
########################################################

# Make directory for building in
mkdir "$BUILDDIR"

# Extract rootfs from .gz file
( cd "$BUILDDIR" && zcat $WORKDIR/build_files/corepure64.gz | sudo cpio -i -H newc -d )

# Download get-pip into ramdisk
( cd "$BUILDDIR/tmp" && wget https://bootstrap.pypa.io/get-pip.py )

# Download TGT and Qemu-utils source
git clone https://github.com/fujita/tgt.git $BUILDDIR/tmp/tgt --depth=1 --branch v1.0.62
git clone https://github.com/qemu/qemu.git $BUILDDIR/tmp/qemu --depth=1 --branch v2.5.0

# Create directory for python local mirror
mkdir -p "$BUILDDIR/tmp/localpip"

# Download IPA and requirements
cd ../..
rm -rf *.egg-info
python setup.py sdist --dist-dir "$BUILDDIR/tmp/localpip" --quiet
cp requirements.txt $BUILDDIR/tmp/ipa-requirements.txt
cd $WORKDIR

sudo cp /etc/resolv.conf $BUILDDIR/etc/resolv.conf
sudo mount --bind /proc $BUILDDIR/proc
$CHROOT_CMD mkdir /etc/sysconfig/tcedir
$CHROOT_CMD chmod a+rwx /etc/sysconfig/tcedir
$CHROOT_CMD touch /etc/sysconfig/tcuser
$CHROOT_CMD chmod a+rwx /etc/sysconfig/tcuser

mkdir $BUILDDIR/tmp/overides
cp $WORKDIR/build_files/fakeuname $BUILDDIR/tmp/overides/uname

while read line; do
    sudo chroot --userspec=$TC:$STAFF $BUILDDIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy tce-load -wci $line
done < $WORKDIR/build_files/buildreqs.lst

sudo umount $BUILDDIR/proc

# Build python wheels
$CHROOT_CMD python /tmp/get-pip.py
$CHROOT_CMD pip install pbr
$CHROOT_CMD pip wheel --wheel-dir /tmp/wheels setuptools
$CHROOT_CMD pip wheel --wheel-dir /tmp/wheels pip
$CHROOT_CMD pip wheel --wheel-dir /tmp/wheels -r /tmp/ipa-requirements.txt
$CHROOT_CMD pip wheel --no-index --pre --wheel-dir /tmp/wheels --find-links=/tmp/localpip --find-links=/tmp/wheels ironic-python-agent

# Build tgt
rm -rf $WORKDIR/build_files/tgt.tcz
$CHROOT_CMD /bin/sh -c "cd /tmp/tgt && make && make install-programs install-conf install-scripts DESTDIR=/tmp/tgt-installed"
cd $WORKDIR/build_files && mksquashfs $BUILDDIR/tmp/tgt-installed tgt.tcz && md5sum tgt.tcz > tgt.tcz.md5.txt
# Build qemu-utils
rm -rf $WORKDIR/build_files/qemu-utils.tcz
$CHROOT_CMD /bin/sh -c "cd /tmp/qemu && ./configure --disable-system --disable-user --disable-linux-user --disable-bsd-user --disable-guest-agent && make && make install DESTDIR=/tmp/qemu-utils"
cd $WORKDIR/build_files && mksquashfs $BUILDDIR/tmp/qemu-utils qemu-utils.tcz && md5sum qemu-utils.tcz > qemu-utils.tcz.md5.txt
# Create qemu-utils.tcz.dep
echo "glib2.tcz" > qemu-utils.tcz.dep

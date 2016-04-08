#!/bin/bash

set -ex
WORKDIR=$(readlink -f $0 | xargs dirname)
BUILDDIR="$WORKDIR/tinyipabuild"
FINALDIR="$WORKDIR/tinyipafinal"
BUILD_AND_INSTALL_TINYIPA=${BUILD_AND_INSTALL_TINYIPA:-false}

TC=1001
STAFF=50

CHROOT_PATH="/tmp/overides:/usr/local/sbin:/usr/local/bin:/apps/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CHROOT_CMD="sudo chroot $FINALDIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy"
TC_CHROOT_CMD="sudo chroot --userspec=$TC:$STAFF $FINALDIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy"

echo "Finalising tinyipa:"

sudo -v

if [ -d "$FINALDIR" ]; then
    sudo rm -rf "$FINALDIR"
fi

mkdir "$FINALDIR"

# Extract rootfs from .gz file
( cd "$FINALDIR" && zcat $WORKDIR/build_files/corepure64.gz | sudo cpio -i -H newc -d )

# Download get-pip into ramdisk
( cd "$FINALDIR/tmp" && wget https://bootstrap.pypa.io/get-pip.py )

#####################################
# Setup Final Dir
#####################################

sudo cp /etc/resolv.conf $FINALDIR/etc/resolv.conf.old
sudo cp /etc/resolv.conf $FINALDIR/etc/resolv.conf

# Modify ldconfig for x86-64
$CHROOT_CMD cp /sbin/ldconfig /sbin/ldconfigold
printf '/sbin/ldconfigold $@ | sed "s/unknown/libc6,x86-64/"' | $CHROOT_CMD tee -a /sbin/ldconfignew
$CHROOT_CMD cp /sbin/ldconfignew /sbin/ldconfig
$CHROOT_CMD chmod u+x /sbin/ldconfig

# Copy python wheels from build to final dir
cp -Rp "$BUILDDIR/tmp/wheels" "$FINALDIR/tmp/wheelhouse"

mkdir -p $FINALDIR/tmp/builtin/optional
$CHROOT_CMD chown -R tc.staff /tmp/builtin
$CHROOT_CMD chmod -R a+w /tmp/builtin
$CHROOT_CMD ln -sf /tmp/builtin /etc/sysconfig/tcedir
echo "tc" | $CHROOT_CMD tee -a /etc/sysconfig/tcuser

cp $WORKDIR/build_files/tgt.* $FINALDIR/tmp/builtin/optional
cp $WORKDIR/build_files/qemu-utils.* $FINALDIR/tmp/builtin/optional

# Mount /proc for chroot commands
sudo mount --bind /proc $FINALDIR/proc

mkdir $FINALDIR/tmp/overides
cp $WORKDIR/build_files/fakeuname $FINALDIR/tmp/overides/uname

while read line; do
    $TC_CHROOT_CMD tce-load -wi $line
done < $WORKDIR/build_files/finalreqs.lst

echo "tgt.tcz" | $TC_CHROOT_CMD tee -a /tmp/builtin/onboot.lst
echo "qemu-utils.tcz" | $TC_CHROOT_CMD tee -a /tmp/builtin/onboot.lst

# If flag is set install the python now
if $BUILD_AND_INSTALL_TINYIPA ; then
    $CHROOT_CMD python /tmp/get-pip.py --no-wheel --no-index --find-links=file:///tmp/wheelhouse ironic_python_agent
    rm -rf $FINALDIR/tmp/wheelhouse
fi

# Unmount /proc and clean up everything
sudo umount $FINALDIR/proc
sudo umount $FINALDIR/tmp/tcloop/*
sudo rm -rf $FINALDIR/tmp/tcloop
sudo rm -rf $FINALDIR/usr/local/tce.installed
sudo mv $FINALDIR/etc/resolv.conf.old $FINALDIR/etc/resolv.conf
sudo rm $FINALDIR/etc/sysconfig/tcuser
sudo rm $FINALDIR/etc/sysconfig/tcedir

# Copy bootlocal.sh to opt
sudo cp "$WORKDIR/build_files/bootlocal.sh" "$FINALDIR/opt/."

# Disable ZSwap
sudo sed -i '/# Main/a NOZSWAP=1' "$FINALDIR/etc/init.d/tc-config"

# Rebuild build directory into gz file
( cd "$FINALDIR" && sudo find | sudo cpio -o -H newc | gzip -9 > "$WORKDIR/tinyipa.gz" )

# Copy vmlinuz to new name
cp "$WORKDIR/build_files/vmlinuz64" "$WORKDIR/tinyipa.vmlinuz"

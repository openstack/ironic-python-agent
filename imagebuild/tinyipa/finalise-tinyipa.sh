#!/bin/bash

set -ex
WORKDIR=$(readlink -f $0 | xargs dirname)
BUILDDIR="$WORKDIR/tinyipabuild"
FINALDIR="$WORKDIR/tinyipafinal"
BUILD_AND_INSTALL_TINYIPA=${BUILD_AND_INSTALL_TINYIPA:-true}
TINYCORE_MIRROR_URL=${TINYCORE_MIRROR_URL-"http://repo.tinycorelinux.net/"}

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

sudo cp -a $FINALDIR/opt/tcemirror $FINALDIR/opt/tcemirror.old
sudo sh -c "echo $TINYCORE_MIRROR_URL > $FINALDIR/opt/tcemirror"

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
    $TC_CHROOT_CMD tce-load -wic $line
done < $WORKDIR/build_files/finalreqs.lst

$TC_CHROOT_CMD tce-load -ic /tmp/builtin/optional/tgt.tcz
$TC_CHROOT_CMD tce-load -ic /tmp/builtin/optional/qemu-utils.tcz

# Ensure tinyipa picks up installed kernel modules
$CHROOT_CMD depmod -a `$WORKDIR/build_files/fakeuname -r`

# If flag is set install the python now
if $BUILD_AND_INSTALL_TINYIPA ; then
    $CHROOT_CMD python /tmp/get-pip.py --no-wheel --no-index --find-links=file:///tmp/wheelhouse ironic_python_agent
    rm -rf $FINALDIR/tmp/wheelhouse
    rm -rf $FINALDIR/tmp/get-pip.py
fi

# Unmount /proc and clean up everything
sudo umount $FINALDIR/proc
sudo rm -rf $FINALDIR/tmp/builtin
sudo rm -rf $FINALDIR/tmp/tcloop
sudo rm -rf $FINALDIR/usr/local/tce.installed
sudo mv $FINALDIR/opt/tcemirror.old $FINALDIR/opt/tcemirror
sudo mv $FINALDIR/etc/resolv.conf.old $FINALDIR/etc/resolv.conf
sudo rm $FINALDIR/etc/sysconfig/tcuser
sudo rm $FINALDIR/etc/sysconfig/tcedir

# Copy bootlocal.sh to opt
sudo cp "$WORKDIR/build_files/bootlocal.sh" "$FINALDIR/opt/."

# Disable ZSwap
sudo sed -i '/# Main/a NOZSWAP=1' "$FINALDIR/etc/init.d/tc-config"
# sudo cp $WORKDIR/build_files/tc-config $FINALDIR/etc/init.d/tc-config

# Precompile all python
set +e
$CHROOT_CMD /bin/bash -c "python -OO -m compileall /usr/local/lib/python2.7"
set -e
find $FINALDIR/usr/local/lib/python2.7 -name "*.py" -not -path "*ironic_python_agent/api/config.py" | sudo xargs rm
find $FINALDIR/usr/local/lib/python2.7 -name "*.pyc" | sudo xargs rm

# Delete unnecessary Babel .dat files
find $FINALDIR -path "*babel/locale-data/*.dat" -not -path "*en_US*" | sudo xargs rm

# Allow an extension to be added to the generated files by specifying
# $BRANCH_PATH e.g. export BRANCH_PATH=master results in tinyipa-master.gz etc
branch_ext=''
if [ -n "$BRANCH_PATH" ]; then
    branch_ext="-$BRANCH_PATH"
fi

# Rebuild build directory into gz file
( cd "$FINALDIR" && sudo find | sudo cpio -o -H newc | gzip -9 > "$WORKDIR/tinyipa${branch_ext}.gz" )

# Copy vmlinuz to new name
cp "$WORKDIR/build_files/vmlinuz64" "$WORKDIR/tinyipa${branch_ext}.vmlinuz"

# Create tar.gz containing tinyipa files
tar czf tinyipa${branch_ext}.tar.gz tinyipa${branch_ext}.gz tinyipa${branch_ext}.vmlinuz

# Output files with sizes created by this script
echo "Produced files:"
du -h tinyipa${branch_ext}.gz tinyipa${branch_ext}.tar.gz tinyipa${branch_ext}.vmlinuz

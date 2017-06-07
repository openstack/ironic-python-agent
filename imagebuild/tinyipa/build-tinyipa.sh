#!/bin/bash

set -ex
WORKDIR=$(readlink -f $0 | xargs dirname)
source ${WORKDIR}/tc-mirror.sh
BUILDDIR="$WORKDIR/tinyipabuild"
BUILD_AND_INSTALL_TINYIPA=${BUILD_AND_INSTALL_TINYIPA:-false}
TINYCORE_MIRROR_URL=${TINYCORE_MIRROR_URL:-}
TINYIPA_REQUIRE_BIOSDEVNAME=${TINYIPA_REQUIRE_BIOSDEVNAME:-false}
TINYIPA_REQUIRE_IPMITOOL=${TINYIPA_REQUIRE_IPMITOOL:-true}

CHROOT_PATH="/tmp/overides:/usr/local/sbin:/usr/local/bin:/apps/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CHROOT_CMD="sudo chroot $BUILDDIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy"

TC=1001
STAFF=50

# NOTE(moshele): Git < 1.7.10 requires a separate checkout, see LP #1590912
function clone_and_checkout {
    git clone $1 $2 --depth=1 --branch $3; cd $2; git checkout $3; cd -
}

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

# Find a working TC mirror if none is explicitly provided
choose_tc_mirror

cd $WORKDIR/build_files
wget -N $TINYCORE_MIRROR_URL/7.x/x86_64/release/distribution_files/corepure64.gz
wget -N $TINYCORE_MIRROR_URL/7.x/x86_64/release/distribution_files/vmlinuz64
cd $WORKDIR

########################################################
# Build Required Python Dependecies in a Build Directory
########################################################

# Make directory for building in
mkdir "$BUILDDIR"

# Extract rootfs from .gz file
( cd "$BUILDDIR" && zcat $WORKDIR/build_files/corepure64.gz | sudo cpio -i -H newc -d )

# Configure mirror
sudo sh -c "echo $TINYCORE_MIRROR_URL > $BUILDDIR/opt/tcemirror"

# Download get-pip into ramdisk
( cd "$BUILDDIR/tmp" && wget https://bootstrap.pypa.io/get-pip.py )

# Download TGT, Qemu-utils, Biosdevname and IPMItool source
clone_and_checkout "https://github.com/fujita/tgt.git" "${BUILDDIR}/tmp/tgt" "v1.0.62"
clone_and_checkout "https://github.com/qemu/qemu.git" "${BUILDDIR}/tmp/qemu" "v2.5.0"
if $TINYIPA_REQUIRE_BIOSDEVNAME; then
    wget -N -O - https://linux.dell.com/biosdevname/biosdevname-0.7.2/biosdevname-0.7.2.tar.gz | tar -xz -C "${BUILDDIR}/tmp" -f -
fi
if $TINYIPA_REQUIRE_IPMITOOL; then
    wget -N -O - https://sourceforge.net/projects/ipmitool/files/ipmitool/1.8.18/ipmitool-1.8.18.tar.gz/download | tar -xz -C "${BUILDDIR}/tmp" -f -
fi

# Create directory for python local mirror
mkdir -p "$BUILDDIR/tmp/localpip"

# Download IPA and requirements
cd ../..
rm -rf *.egg-info
python setup.py sdist --dist-dir "$BUILDDIR/tmp/localpip" --quiet
cp requirements.txt $BUILDDIR/tmp/ipa-requirements.txt

imagebuild/common/generate_upper_constraints.sh upper-constraints.txt
cp upper-constraints.txt $BUILDDIR/tmp/upper-constraints.txt
echo Using upper-constraints:
cat upper-constraints.txt
cd $WORKDIR

sudo cp /etc/resolv.conf $BUILDDIR/etc/resolv.conf

trap "sudo umount $BUILDDIR/proc; sudo umount $BUILDDIR/dev/pts" EXIT
sudo mount --bind /proc $BUILDDIR/proc
sudo mount --bind /dev/pts $BUILDDIR/dev/pts

if [ -d /opt/stack/new ]; then
    # Running in CI environment, make checkouts available
    $CHROOT_CMD mkdir -p /opt/stack/new
    for project in $(ls /opt/stack/new); do
        if grep -q "$project" $BUILDDIR/tmp/upper-constraints.txt &&
            [ -d "/opt/stack/new/$project/.git" ]; then
            sudo cp -R "/opt/stack/new/$project" $BUILDDIR/opt/stack/new/
        fi
    done
fi

$CHROOT_CMD mkdir /etc/sysconfig/tcedir
$CHROOT_CMD chmod a+rwx /etc/sysconfig/tcedir
$CHROOT_CMD touch /etc/sysconfig/tcuser
$CHROOT_CMD chmod a+rwx /etc/sysconfig/tcuser

mkdir $BUILDDIR/tmp/overides
cp $WORKDIR/build_files/fakeuname $BUILDDIR/tmp/overides/uname

while read line; do
    sudo chroot --userspec=$TC:$STAFF $BUILDDIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy tce-load -wci $line
done < $WORKDIR/build_files/buildreqs.lst

# Build python wheels
$CHROOT_CMD python /tmp/get-pip.py
$CHROOT_CMD pip install pbr
$CHROOT_CMD pip wheel -c /tmp/upper-constraints.txt --wheel-dir /tmp/wheels setuptools
$CHROOT_CMD pip wheel -c /tmp/upper-constraints.txt --wheel-dir /tmp/wheels pip
$CHROOT_CMD pip wheel -c /tmp/upper-constraints.txt --wheel-dir /tmp/wheels -r /tmp/ipa-requirements.txt
$CHROOT_CMD pip wheel -c /tmp/upper-constraints.txt --no-index --pre --wheel-dir /tmp/wheels --find-links=/tmp/localpip --find-links=/tmp/wheels ironic-python-agent
echo Resulting wheels:
ls -1 $BUILDDIR/tmp/wheels

# Build tgt
rm -rf $WORKDIR/build_files/tgt.tcz
$CHROOT_CMD /bin/sh -c "cd /tmp/tgt && make && make install-programs install-conf install-scripts DESTDIR=/tmp/tgt-installed"
find $BUILDDIR/tmp/tgt-installed/ -type f -executable | xargs file | awk -F ':' '/ELF/ {print $1}' | sudo xargs strip
cd $WORKDIR/build_files && mksquashfs $BUILDDIR/tmp/tgt-installed tgt.tcz && md5sum tgt.tcz > tgt.tcz.md5.txt

# Build qemu-utils
rm -rf $WORKDIR/build_files/qemu-utils.tcz
$CHROOT_CMD /bin/sh -c "cd /tmp/qemu && ./configure --disable-system --disable-user --disable-linux-user --disable-bsd-user --disable-guest-agent --disable-blobs && make && make install DESTDIR=/tmp/qemu-utils"
find $BUILDDIR/tmp/qemu-utils/ -type f -executable | xargs file | awk -F ':' '/ELF/ {print $1}' | sudo xargs strip
cd $WORKDIR/build_files && mksquashfs $BUILDDIR/tmp/qemu-utils qemu-utils.tcz && md5sum qemu-utils.tcz > qemu-utils.tcz.md5.txt
# Create qemu-utils.tcz.dep
echo "glib2.tcz" > qemu-utils.tcz.dep

# Build biosdevname
if $TINYIPA_REQUIRE_BIOSDEVNAME; then
    rm -rf $WORKDIR/build_files/biosdevname.tcz
    $CHROOT_CMD /bin/sh -c "cd /tmp/biosdevname-* && ./configure && make && make install DESTDIR=/tmp/biosdevname-installed"
    find $BUILDDIR/tmp/biosdevname-installed/ -type f -executable | xargs file | awk -F ':' '/ELF/ {print $1}' | sudo xargs strip
    cd $WORKDIR/build_files && mksquashfs $BUILDDIR/tmp/biosdevname-installed biosdevname.tcz && md5sum biosdevname.tcz > biosdevname.tcz.md5.txt
fi

if $TINYIPA_REQUIRE_IPMITOOL; then
    rm -rf $WORKDIR/build_files/ipmitool.tcz
    $CHROOT_CMD /bin/sh -c "cd /tmp/ipmitool-* && ./configure && make && make install DESTDIR=/tmp/ipmitool"
    find $BUILDDIR/tmp/ipmitool/ -type f -executable | xargs file | awk -F ':' '/ELF/ {print $1}' | sudo xargs strip
    cd $WORKDIR/build_files && mksquashfs $BUILDDIR/tmp/ipmitool ipmitool.tcz && md5sum ipmitool.tcz > ipmitool.tcz.md5.txt
fi

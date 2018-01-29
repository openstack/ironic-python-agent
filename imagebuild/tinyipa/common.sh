#!/bin/bash

WORKDIR=$(readlink -f $0 | xargs dirname)
source ${WORKDIR}/tc-mirror.sh

# Allow an extension to be added to the generated files by specifying
# $BRANCH_PATH e.g. export BRANCH_PATH=master results in tinyipa-master.gz etc
BRANCH_EXT=''
if [ -n "$BRANCH_PATH" ]; then
    BRANCH_EXT="-$BRANCH_PATH"
fi
export BRANCH_EXT

TC=1001
STAFF=50

CHROOT_PATH="/tmp/overides:/usr/local/sbin:/usr/local/bin:/apps/bin:/usr/sbin:/usr/bin:/sbin:/bin"
CHROOT_CMD="sudo chroot $DST_DIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy"
TC_CHROOT_CMD="sudo chroot --userspec=$TC:$STAFF $DST_DIR /usr/bin/env -i PATH=$CHROOT_PATH http_proxy=$http_proxy https_proxy=$https_proxy no_proxy=$no_proxy"

function setup_tce {
    # Setup resolv.conf, add mirrors, mount proc
    local dst_dir="$1"

    # Find a working TC mirror if none is explicitly provided
    choose_tc_mirror

    sudo cp $dst_dir/etc/resolv.conf $dst_dir/etc/resolv.conf.old
    sudo cp /etc/resolv.conf $dst_dir/etc/resolv.conf

    sudo cp -a $dst_dir/opt/tcemirror $dst_dir/opt/tcemirror.old
    sudo sh -c "echo $TINYCORE_MIRROR_URL > $dst_dir/opt/tcemirror"

    mkdir -p $dst_dir/tmp/builtin/optional
    $CHROOT_CMD chown -R tc.staff /tmp/builtin
    $CHROOT_CMD chmod -R a+w /tmp/builtin
    $CHROOT_CMD ln -sf /tmp/builtin /etc/sysconfig/tcedir
    echo "tc" | $CHROOT_CMD tee -a /etc/sysconfig/tcuser

    # Mount /proc for chroot commands
    sudo mount --bind /proc $dst_dir/proc
}

function cleanup_tce {
    local dst_dir="$1"

    # Unmount /proc and clean up everything
    sudo umount $dst_dir/proc
    sudo rm -rf $dst_dir/tmp/builtin
    sudo rm -rf $dst_dir/tmp/tcloop
    sudo rm -rf $dst_dir/usr/local/tce.installed
    sudo mv $dst_dir/opt/tcemirror.old $dst_dir/opt/tcemirror
    sudo mv $dst_dir/etc/resolv.conf.old $dst_dir/etc/resolv.conf
    sudo rm $dst_dir/etc/sysconfig/tcuser
    sudo rm $dst_dir/etc/sysconfig/tcedir
}

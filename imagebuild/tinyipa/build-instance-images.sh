#!/bin/bash

set -ex
WORKDIR=$(readlink -f $0 | xargs dirname)
DST_DIR=$(mktemp -d)
source ${WORKDIR}/common.sh
PARTIMG="$WORKDIR/tiny-instance-part${BRANCH_EXT}.img"
UECFILE="$WORKDIR/tiny-instance-uec${BRANCH_EXT}.tar.gz"
fs_type='ext4'

sudo rm -rf $PARTIMG $UECFILE
sudo truncate --size=150M $PARTIMG

sudo mkfs."${fs_type}" -F "$PARTIMG" -L "root"
sudo mount -o loop "$PARTIMG" "$DST_DIR/"

# Extract rootfs from .gz file
( cd "$DST_DIR" && zcat $WORKDIR/build_files/corepure64.gz | sudo cpio -i -H newc -d )

setup_tce $DST_DIR

$TC_CHROOT_CMD tce-load -wci grub2-multi.tcz

cleanup_tce $DST_DIR
sudo umount $DST_DIR/

pushd $DST_DIR/
cp $WORKDIR/tinyipa${BRANCH_EXT}.gz $DST_DIR/tinyipa-initrd
cp $WORKDIR/tinyipa${BRANCH_EXT}.vmlinuz $DST_DIR/tinyipa-vmlinuz
cp $PARTIMG $DST_DIR/

tar -czf $UECFILE ./

popd

sudo rm -rf $DST_DIR

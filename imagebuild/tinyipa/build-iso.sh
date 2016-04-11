#!/bin/sh

set -ex
WORKDIR=$(readlink -f $0 | xargs dirname)

cd $WORKDIR/build_files
wget -N https://www.kernel.org/pub/linux/utils/boot/syslinux/syslinux-4.06.tar.gz && tar zxf syslinux-4.06.tar.gz

cd $WORKDIR
rm -rf newiso
mkdir -p newiso/boot/isolinux
cp build_files/syslinux-4.06/core/isolinux.bin newiso/boot/isolinux/.
cp build_files/isolinux.cfg newiso/boot/isolinux/.
cp tinyipa.gz newiso/boot/corepure64.gz
cp tinyipa.vmlinuz newiso/boot/vmlinuz64
genisoimage -l -r -J -R -V TC-custom -no-emul-boot -boot-load-size 4 -boot-info-table -b boot/isolinux/isolinux.bin -c boot/isolinux/boot.cat -o tinyipa.iso newiso

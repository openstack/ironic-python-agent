#!/bin/bash
#
# This should work with almost any image that uses MBR partitioning and doesn't already
# have 3 or more partitions.

set -e

usage() {
  [[ -z "$1" ]] || echo -e "USAGE ERROR: $@\n"
  echo "`basename $0`: CONFIGDRIVE_DIR IMAGEFILE DEVICE"
  echo "  - This script images DEVICE with IMAGEFILE and injects"
  echo "    CONFIGDRIVE_DIR contents as an iso9660 filesystem on a partition"
  echo "    at the end of the device"
  exit 1
}

CONFIGDRIVE_DIR="$1"
IMAGEFILE="$2"
DEVICE="$3"

[[ -d $CONFIGDRIVE_DIR ]] || usage "$1 (CONFIGDRIVE_DIR) is not a directory"
[[ -f $IMAGEFILE ]] || usage "$2 (IMAGEFILE) is not a file"
[[ -b $DEVICE ]] || usage "$3 (DEVICE) is not a block device"

qemu-img convert -O raw $IMAGEFILE $DEVICE

# Create small partition at the end of the device
parted -a optimal -s -- $DEVICE mkpart primary ext2 -16MiB -0

# Find partition we just created 
# Dump all partitions, ignore empty ones, then get the last partition ID
ISO_PARTITION=`sfdisk --dump $DEVICE | grep -v '0,' | tail -n1 | awk '{print $1}'`

# This generates the ISO image of the config drive.
genisoimage \
 -o ${ISO_PARTITION} \
 -ldots \
 -input-charset 'utf-8' \
 -allow-lowercase \
 -allow-multidot \
 -l \
 -publisher "teeth" \
 -J \
 -r \
 -V 'config-2' \
 ${CONFIGDRIVE_DIR}

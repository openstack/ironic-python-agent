#!/bin/bash

set -e

log() {
  echo "`basename $0`: $@"
}

usage() {
  [[ -z "$1" ]] || echo -e "USAGE ERROR: $@\n"
  echo "`basename $0`: CONFIGDRIVE_DIR DEVICE"
  echo "  - This script injects CONFIGDRIVE_DIR contents as an iso9660"
  echo "    filesystem on a partition at the end of DEVICE."
  exit 1
}

CONFIGDRIVE_DIR="$1"
DEVICE="$2"

[[ -d $CONFIGDRIVE_DIR ]] || usage "$CONFIGDRIVE_DIR (CONFIGDRIVE_DIR) is not a directory"
[[ -b $DEVICE ]] || usage "$DEVICE (DEVICE) is not a block device"

# Create small partition at the end of the device
log "Adding configdrive partition to $DEVICE"
parted -a optimal -s -- $DEVICE mkpart primary ext2 -16MiB -0

# Find partition we just created
# Dump all partitions, ignore empty ones, then get the last partition ID
ISO_PARTITION=`sfdisk --dump $DEVICE | grep -v ' 0,' | tail -n1 | awk '{print $1}'`

# This generates the ISO image of the config drive.
log "Writing Configdrive contents in $CONFIGDRIVE_DIR to $ISO_PARTITION"
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

log "${DEVICE} imaged successfully!"

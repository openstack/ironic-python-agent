#!/bin/bash
#
# This should work with almost any image that uses MBR partitioning and doesn't already
# have 3 or more partitions.

set -e

log() {
  echo "`basename $0`: $@"
}

usage() {
  [[ -z "$1" ]] || echo -e "USAGE ERROR: $@\n"
  echo "`basename $0`: IMAGEFILE DEVICE"
  echo "  - This script images DEVICE with IMAGEFILE"
  exit 1
}

IMAGEFILE="$1"
DEVICE="$2"

[[ -f $IMAGEFILE ]] || usage "$IMAGEFILE (IMAGEFILE) is not a file"
[[ -b $DEVICE ]] || usage "$DEVICE (DEVICE) is not a block device"

# In production this will be replaced with secure erasing the drives
# For now we need to ensure there aren't any old (GPT) partitions on the drive
log "Erasing existing mbr from ${DEVICE}"
dd if=/dev/zero of=$DEVICE bs=512 count=10

# Converts image to raw and writes to device
log "Imaging $IMAGEFILE onto $DEVICE"
qemu-img convert -O raw $IMAGEFILE $DEVICE

log "${DEVICE} imaged successfully!"

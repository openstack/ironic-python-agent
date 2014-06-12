#!/bin/bash

# Copyright 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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

## Doing two steps allows us to use dd, which allows us to tweak things like
## blocksize and allows use of direct io
# Converts image to raw
log "Converting $IMAGEFILE to RAW format"
qemu-img convert -O raw $IMAGEFILE /tmp/image.raw

# Write image onto device
log "Imaging $DEVICE"
dd if=/tmp/image.raw of=$DEVICE bs=64K oflag=direct

log "${DEVICE} imaged successfully!"

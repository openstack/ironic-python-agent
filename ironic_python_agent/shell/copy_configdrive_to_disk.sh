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

# This should work with almost any image that uses MBR partitioning and
# doesn't already have 3 or more partitions -- or else you'll no longer
# be able to create extended partitions on the disk.

log() {
  echo "`basename $0`: $@"
}

fail() {
  log "Error $@"
  exit 1
}

usage() {
  [[ -z "$1" ]] || echo -e "USAGE ERROR: $@\n"
  echo "`basename $0`: CONFIGDRIVE DEVICE"
  echo "  - This script injects CONFIGDRIVE contents as an iso9660"
  echo "    filesystem on a partition at the end of DEVICE."
  exit 1
}

CONFIGDRIVE="$1"
DEVICE="$2"

[[ -f $CONFIGDRIVE ]] || usage "$CONFIGDRIVE (CONFIGDRIVE) is not a regular file"
[[ -b $DEVICE ]] || usage "$DEVICE (DEVICE) is not a block device"

# We need to run partprobe to ensure all partitions are visible so the
# following blkid command returns partitions just imaged to the device
/sbin/partprobe $DEVICE || fail "running partprobe against $DEVICE"

# Check for preexisting partition for configdrive
EXISTING_PARTITION=`/sbin/blkid -l -o device $DEVICE -t LABEL=config-2`
if [[ $? == 0 ]]; then
  log "Existing configdrive found on ${DEVICE} at ${EXISTING_PARTITION}"
  ISO_PARTITION=$EXISTING_PARTITION
else
  # Create small partition at the end of the device
  log "Adding configdrive partition to $DEVICE"
  parted -a optimal -s -- $DEVICE mkpart primary ext2 -64MiB -0 || fail "creating configdrive on ${DEVICE}"

  # Find partition we just created
  # Dump all partitions, ignore empty ones, then get the last partition ID
  ISO_PARTITION=`sfdisk --dump $DEVICE | grep -v ' 0,' | tail -n1 | awk '{print $1}'` || fail "finding ISO partition created on ${DEVICE}"
fi

# This writes the ISO image to the config drive.
log "Writing Configdrive contents in $CONFIGDRIVE to $ISO_PARTITION"
dd if=$CONFIGDRIVE of=$ISO_PARTITION bs=64K oflag=direct || fail "writing Configdrive to ${ISO_PARTITION}"

log "${DEVICE} imaged successfully!"

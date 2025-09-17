#!/bin/bash

set -euo pipefail

STAGE="$IPA_DEPLOYMENT_STAGE"
DEVICE="$IPA_TARGET_DEVICE"
MARKER_FILE="/ipa.hello"

case "$STAGE" in
    pre)
        echo "=== Pre-deployment stage ===" | tee "$MARKER_FILE"
        echo "Timestamp: $(date -Iseconds)" | tee -a "$MARKER_FILE"
        echo "Target device: $DEVICE" | tee -a "$MARKER_FILE"
        echo "Hostname: $(hostname)" | tee -a "$MARKER_FILE"
        echo "IP addresses:" | tee -a "$MARKER_FILE"
        ip addr show | grep 'inet ' | tee -a "$MARKER_FILE"
        echo "Disk info:" | tee -a "$MARKER_FILE"
        lsblk "$DEVICE" | tee -a "$MARKER_FILE"
        echo "Memory info:" | tee -a "$MARKER_FILE"
        free -h | tee -a "$MARKER_FILE"
        echo "=== End pre-deployment ===" | tee -a "$MARKER_FILE"
        echo "Pre-deployment marker created at $MARKER_FILE"
        ;;

    post)
        if [[ ! -f "$MARKER_FILE" ]]; then
            echo "ERROR: Pre-deployment marker file not found at $MARKER_FILE"
            exit 1
        fi

        echo "=== Post-deployment stage ===" | tee -a "$MARKER_FILE"
        echo "Post-deployment timestamp: $(date -Iseconds)" | tee -a "$MARKER_FILE"

        ROOT_PARTITION=$(blkid -t PARTLABEL=root -o device 2>/dev/null | head -1 || true)
        if [[ -z "$ROOT_PARTITION" ]]; then
            echo "ERROR: Could not find root partition with PARTLABEL=root on device $DEVICE"
            echo "Available partitions:"
            lsblk "$DEVICE"
            blkid | grep "$DEVICE"
            exit 1
        fi

        MOUNT_POINT="/mnt/root-$(date +%s)"
        mkdir -p "$MOUNT_POINT"

        echo "Mounting root partition $ROOT_PARTITION to $MOUNT_POINT"
        mount "$ROOT_PARTITION" "$MOUNT_POINT"

        TARGET_FILE="$MOUNT_POINT/$MARKER_FILE"
        mkdir -p "$(dirname "$TARGET_FILE")"
        cp "$MARKER_FILE" "$TARGET_FILE"

        chmod 644 "$TARGET_FILE"

        echo "Deployment marker copied to $TARGET_FILE"
        echo "=== End post-deployment ===" | tee -a "$TARGET_FILE"

        sync
        umount "$MOUNT_POINT"
        rmdir "$MOUNT_POINT"

        echo "Post-deployment completed successfully"
        ;;

    *)
        echo "ERROR: Unknown deployment stage: $STAGE"
        exit 1
        ;;
esac
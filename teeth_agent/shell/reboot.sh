#!/bin/bash
#
# This script reboots by echoing into /proc/sysrq_trigger.

set -e

echo "s" > /proc/sysrq-trigger
echo "b" > /proc/sysrq-trigger

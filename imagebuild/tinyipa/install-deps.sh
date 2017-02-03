#!/bin/bash

COMMON_PACKAGES="wget python-pip unzip sudo gawk"
APT_PACKAGES="${COMMON_PACKAGES} squashfs-tools"
YUM_PACKAGES="${COMMON_PACKAGES} squashfs-tools"
ZYPPER_PACKAGES="${COMMON_PACKAGES} squashfs"

echo "Installing dependencies:"

# first zypper in case zypper-aptitude is installed
if [ -x "/usr/bin/zypper" ]; then
    sudo -E zypper -n install -l ${ZYPPER_PACKAGES}
elif [ -x "/usr/bin/apt-get" ]; then
    sudo -E apt-get update
    sudo -E apt-get install -y ${APT_PACKAGES}
elif [ -x "/usr/bin/dnf" ]; then
    sudo -E dnf install -y ${YUM_PACKAGES}
elif [ -x "/usr/bin/yum" ]; then
    sudo -E yum install -y ${YUM_PACKAGES}
else
    echo "No supported package manager installed on system. Supported: apt, yum, dnf, zypper"
    exit 1
fi

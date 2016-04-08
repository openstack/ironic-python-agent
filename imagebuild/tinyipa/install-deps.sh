#!/bin/bash

PACKAGES="wget python-pip unzip sudo gawk squashfs-tools"

echo "Installing dependencies:"

if [ -x "/usr/bin/apt-get" ]; then
    sudo -E apt-get update
    sudo -E apt-get install -y $PACKAGES
elif [ -x "/usr/bin/dnf" ]; then
    sudo -E dnf install -y $PACKAGES
elif [ -x "/usr/bin/yum" ]; then
    sudo -E yum install -y $PACKAGES
else
    echo "No supported package manager installed on system. Supported: apt, yum, dnf"
    exit 1
fi

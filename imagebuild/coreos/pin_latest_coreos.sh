#!/bin/bash -xe

HERE=$(dirname $0)

CHANNEL="stable"
ARCH="amd64-usr"
VERSION="current"

URL="https://${CHANNEL}.release.core-os.net/${ARCH}/${VERSION}/version.txt"

wget $URL -O "${HERE}/version.txt"

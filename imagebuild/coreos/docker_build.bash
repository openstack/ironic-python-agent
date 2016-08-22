#!/bin/bash
#
# docker_build.bash - Prepares and outputs a tarball'd docker repository
#                     suitable for injection into a coreos pxe image
#

set -e

OUTPUT_FILE="oem/container.tar.gz"
IPA_ROOT=$(readlink -f $(dirname $0)/../../)

# If there's already a container.tar.gz, don't overwrite it -- instead, bail
if [[ -e "${OUTPUT_FILE}" ]]; then
  echo "${OUTPUT_FILE} already exists. Will not overwrite. Exiting."
  exit 1
fi

# Build the docker image
# Everything from ${IPA_ROOT} will be available under /tmp/ironic-python-agent in Docker
cd ${IPA_ROOT}

imagebuild/common/generate_upper_constraints.sh ${IPA_ROOT}/upper-constraints.txt

docker build -t oemdocker .
cd -

# Create a UUID to identify the build
CONTAINER_UUID=`uuidgen`

# Export the oemdocker repository to a tarball so it can be embedded in CoreOS
# TODO: Investigate running a container and using "export" to flatten the
#       image to shrink the CoreOS fs size. This will also require run.sh to
#       use docker import instead of docker load as well.
docker run oemdocker echo $CONTAINER_UUID
CONTAINER=`docker ps -a --no-trunc |grep $CONTAINER_UUID|awk '{print $1}'|head -n1`
echo $CONTAINER
docker export $CONTAINER | gzip > ${OUTPUT_FILE}

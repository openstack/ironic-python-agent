#!/bin/bash
#
# docker_build.bash - Prepares and outputs a tarball'd docker repository
#                     suitable for injection into a coreos pxe image
#

set -e

OUTPUT_FILE="oem/container.tar.gz"

# If there's already a container.tar.gz, don't overwrite it -- instead, bail
if [[ -e "${OUTPUT_FILE}" ]]; then
  echo "${OUTPUT_FILE} already exists. Will not overwrite. Exiting."
  exit 1
fi

# Build the docker image
cd ../../

# TODO(jlvilla): Once Docker 1.9 is widely deployed, switch to using the 'ARG'
# command which was added in Docker 1.9. Currently Ubuntu 14.04 uses Docker
# 1.6. Using the ARG command will be a much cleaner solution.
mv proxy.sh .proxy.sh.save || true
# Create a temporary proxy.sh script, that will be used by the Dockerfile.
# Since we are calling 'docker build' we can not use --env-file/--env as those
# are arguments to 'docker run'
echo '#!/bin/sh' > proxy.sh
echo 'echo Running: $*' >> proxy.sh
echo "http_proxy=${http_proxy:-} https_proxy=${https_proxy:-} no_proxy=${no_proxy:-} "'$*' >> proxy.sh
chmod 0755 proxy.sh

docker build -t oemdocker .

# Restore saved copy
mv .proxy.sh.save proxy.sh || true

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

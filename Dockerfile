FROM jayofdoom/docker-ubuntu-14.04

# The add is before the RUN to ensure we get the latest version of packages
# Docker will cache RUN commands, but because the SHA1 of the dir will be
# different it will not cache this layer
ADD . /tmp/ironic-python-agent

# Install requirements: Python for ironic-python-agent, others for putting an
# image on disk
RUN apt-get update && apt-get -y install \
    python python-pip python-dev \
    qemu-utils parted util-linux genisoimage git

# Install requirements separately, because pip understands a git+https url
# while setuptools doesn't
RUN pip install -r /tmp/ironic-python-agent/requirements.txt

# This will succeed because all the dependencies were installed previously
RUN pip install /tmp/ironic-python-agent

CMD [ "/usr/local/bin/ironic-python-agent" ]

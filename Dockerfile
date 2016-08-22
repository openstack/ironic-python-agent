FROM debian:jessie

# The add is before the RUN to ensure we get the latest version of packages
# Docker will cache RUN commands, but because the SHA1 of the dir will be
# different it will not cache this layer
ADD . /tmp/ironic-python-agent

# Add 'backports' for qemu-utils
RUN echo 'deb http://httpredir.debian.org/debian jessie-backports main' > /etc/apt/sources.list.d/backports.list

# Install requirements: Python for ironic-python-agent, others for putting an
# image on disk
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends gdisk python2.7 python2.7-dev \
        python-pip qemu-utils parted hdparm util-linux genisoimage git gcc \
        bash coreutils tgt dmidecode ipmitool && \
    apt-get --only-upgrade -t jessie-backports install -y qemu-utils

# Some cleanup
RUN apt-get -y autoremove && \
    apt-get clean

# Before cleaning mark packages that are required so they are not removed
RUN apt-mark manual python-setuptools
RUN apt-mark manual python-minimal

# Install requirements separately, because pip understands a git+https url
# while setuptools doesn't
RUN pip install --upgrade pip
RUN pip install -c /tmp/ironic-python-agent/upper-constraints.txt -r /tmp/ironic-python-agent/requirements.txt

# This will succeed because all the dependencies were installed previously
RUN pip install -c /tmp/ironic-python-agent/upper-constraints.txt /tmp/ironic-python-agent

# Remove no longer needed packages
RUN apt-get -y purge gcc-4.6 gcc python2.7-dev git && \
    apt-get -y autoremove && \
    apt-get clean
RUN rm -rf /tmp/ironic-python-agent
RUN rm -rf /var/lib/apt/lists/*

CMD [ "/usr/local/bin/ironic-python-agent" ]

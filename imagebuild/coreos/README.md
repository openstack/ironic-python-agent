# teeth-agent CoreOS Image builder.

Builds a CoreOS image suitable for running the teeth-agent on a server.

# Requirements

Must be run from a linux machine with a working docker installation and python-pip

Run the following locally or from a virtualenv to install the python requirements
```
pip install -r requirements.txt
``` 

# Instructions

To create a docker repository and embed it into a CoreOS pxe image:
```
make
```

To just create the docker repository in oem/container.tar.gz:
```
make docker
``` 

To embed the oem/ directory into a CoreOS pxe image:

Note: In order to have the ability to ssh into the created image, you need to
pass ssh keys in via the kernel command line for CoreOS, or create
oem/authorized_keys with the keys you need added before building the image.
```
make coreos
```

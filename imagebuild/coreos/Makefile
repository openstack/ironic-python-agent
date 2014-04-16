default: docker coreos

docker: 
	./docker_build.bash

coreos:
	mkdir -p UPLOAD
	./coreos-oem-inject.py oem UPLOAD

clean:
	rm -rf ironic-python-agent
	rm -f oem/container.tar.gz
	rm -f UPLOAD/coreos_production_pxe_image-oem.cpio.gz
	rm -f UPLOAD/coreos_production_pxe.vmlinuz
	rm -rf ../.image_cache

docker_clean:
	./docker_clean.bash

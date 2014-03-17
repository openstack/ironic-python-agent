default: docker coreos

docker: 
	./docker_build.bash

coreos:
	mkdir UPLOAD
	./coreos-oem-inject.py oem UPLOAD

clean:
	rm -rf teeth-agent
	rm -f oem/container.tar.gz
	rm -f UPLOAD/coreos_production_pxe_image-oem.cpio.gz
	rm -f UPLOAD/coreos_production_pxe.vmlinuz

docker_clean:
	./docker_clean.bash

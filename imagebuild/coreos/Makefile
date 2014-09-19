BUILD_DIR=UPLOAD
KERNEL=$(BUILD_DIR)/coreos_production_pxe.vmlinuz
INITRD=$(BUILD_DIR)/coreos_production_pxe_image-oem.cpio.gz

default: docker coreos

docker: 
	./docker_build.bash

coreos:
	mkdir -p $(BUILD_DIR)
	./coreos-oem-inject.py oem $(BUILD_DIR)

clean:
	rm -rf ironic-python-agent
	rm -f oem/container.tar.gz
	rm -f $(INITRD)
	rm -f $(KERNEL)
	rm -rf ../.image_cache

docker_clean:
	./docker_clean.bash

iso: docker coreos
	./iso-image-create -o $(BUILD_DIR)/ipa-coreos.iso -i $(INITRD) -k $(KERNEL)

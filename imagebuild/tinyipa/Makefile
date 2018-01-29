.PHONY: default all dependencies build finalise addssh iso clean clean_build clean_iso
default: dependencies build finalise instance-images

all: dependencies build finalise iso instance-images

dependencies:
	./install-deps.sh

build:
	./build-tinyipa.sh

finalise:
	./finalise-tinyipa.sh

addssh:
	./add-ssh-tinyipa.sh

iso:
	./build-iso.sh

instance-images:
	./build-instance-images.sh

clean: clean_build clean_iso

clean_build:
	sudo -v
	sudo rm -rf tinyipabuild
	sudo rm -rf tinyipafinal
	sudo rm -rf tinyipaaddssh
	rm -f *tinyipa*.vmlinuz
	rm -f *tinyipa*.gz
	rm -f *tinyipa*.sha256
	rm -f build_files/corepure64.gz
	rm -f build_files/vmlinuz64
	rm -f build_files/*.tcz
	rm -f build_files/*.tcz.*
	rm -f tiny-instance-part*.img
	rm -f tiny-instance-uec*.tar.gz

clean_iso:
	rm -rf newiso
	rm -f build_files/syslinux-4.06.tar.gz
	rm -rf build_files/syslinux-4.06
	rm -f tinyipa.iso

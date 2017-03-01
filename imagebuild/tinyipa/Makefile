.PHONY: default all dependencies build finalise iso clean clean_build clean_iso
default: dependencies build finalise

all: dependencies build finalise iso

dependencies:
	./install-deps.sh

build:
	./build-tinyipa.sh

finalise:
	./finalise-tinyipa.sh

iso:
	./build-iso.sh

clean: clean_build clean_iso

clean_build:
	sudo -v
	sudo rm -rf tinyipabuild
	sudo rm -rf tinyipafinal
	rm -f tinyipa*.vmlinuz
	rm -f tinyipa*.gz
	rm -f tinyipa*.sha256
	rm -f build_files/corepure64.gz
	rm -f build_files/vmlinuz64
	rm -f build_files/*.tcz
	rm -f build_files/*.tcz.*

clean_iso:
	rm -rf newiso
	rm -f build_files/syslinux-4.06.tar.gz
	rm -rf build_files/syslinux-4.06
	rm -f tinyipa.iso

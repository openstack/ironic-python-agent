#!/usr/bin/env python

import os
import sys
import time
import requests
import tempfile
import shutil
from plumbum import local, cmd

COREOS_VERSION="197.0.0"

COREOS_ARCH="amd64-generic"
COREOS_BASE_URL="http://storage.core-os.net/coreos/{}/{}".format(COREOS_ARCH, COREOS_VERSION)
COREOS_PXE_DIGESTS="coreos_production_pxe_image.cpio.gz.DIGESTS.asc"
COREOS_PXE_KERNEL="coreos_production_pxe.vmlinuz"
COREOS_PXE_IMAGE="coreos_production_pxe_image.cpio.gz"
COREOS_PXE_IMAGE_URL = "{}/{}".format(COREOS_BASE_URL, COREOS_PXE_IMAGE)
COREOS_PXE_KERNEL_URL = "{}/{}".format(COREOS_BASE_URL, COREOS_PXE_KERNEL)
COREOS_PXE_DIGESTS_URL = "{}/{}".format(COREOS_BASE_URL, COREOS_PXE_DIGESTS)



def get_etag(cache_name):
    etag_file = "{}.etag".format(cache_name)
    if not os.path.exists(etag_file):
        return None
    with open(etag_file, 'rb') as fp:
        etag = fp.read()
    etag.strip()
    return etag

def save_etag(cache_name, etag):
    etag_file = "{}.etag".format(cache_name)
    with open(etag_file, 'w+b') as fp:
        fp.write(etag)

def cache_file(cache_name, remote_url):
    print("{} <- {}".format(cache_name, remote_url))
    etag = get_etag(cache_name)
    headers = {}
    if etag:
        headers['If-None-Match'] = etag

    start = time.time()
    r = requests.get(remote_url, headers=headers)

    if r.status_code == 304:
        print("[etag-match]")
        return

    if r.status_code != 200:
        raise RuntimeError('Failed to download {}, got HTTP {} Status Code.'.format(remote_url, r.status_code))

    with open(cache_name, 'w+b') as fp:
        fp.write(r.content)

    print("{} bytes in {} seconds".format(len(r.content), time.time() - start))
    save_etag(cache_name, r.headers['etag'])

def inject_oem(archive, oem_dir, output_file):
    d = tempfile.mkdtemp(prefix="oem-inject")
    try:
        with local.cwd(d):
            dest_oem_dir = os.path.join(d, 'usr', 'share', 'oem')
            uz = cmd.gunzip["-c", archive]
            extract = cmd.cpio["-iv"]
            chain = uz | extract
            print chain
            chain()

            shutil.copytree(oem_dir, dest_oem_dir)

            find = cmd.find['.', '-depth', '-print']
            cpio = cmd.cpio['-o', '-H', 'newc']
            gz = cmd.gzip
            chain = find | cmd.sort | cpio | gz > output_file
            print chain
            chain()
    finally:
        shutil.rmtree(d)
    return output_file

def validate_digests(digests, target, hash_type='sha1'):
    with local.cwd(os.path.dirname(digests)):
        gethashes = cmd.grep['-i', '-A1', '^# {} HASH$'.format(hash_type), digests]
        forthis = cmd.grep[os.path.basename(target)]
        viasum = local[hash_type + "sum"]['-c', '/dev/stdin']
        chain = gethashes | forthis | viasum
        print chain
        chain()

def main():
    if len(sys.argv) != 3:
        print("usage: {} [oem-directory-to-inject] [output-directory]".format(os.path.basename(__file__)))
        return

    oem_dir = os.path.abspath(os.path.expanduser(sys.argv[1]))
    output_dir = os.path.abspath(os.path.expanduser(sys.argv[2]))

    if not os.path.exists(oem_dir):
        print("Error: {} doesn't exist.".format(oem_dir))
        return

    if not os.path.exists(os.path.join(oem_dir, 'run.sh')):
        print("Error: {} is missing oem.sh".format(oem_dir))
        return

    here = os.path.abspath(os.path.dirname(__file__))

    top_cache_dir = os.path.join(os.path.dirname(here), ".image_cache")
    cache_dir = os.path.join(top_cache_dir, COREOS_ARCH, COREOS_VERSION)

    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    orig_cpio = os.path.join(cache_dir, COREOS_PXE_IMAGE)
    digests = os.path.join(cache_dir, COREOS_PXE_DIGESTS)
    kernel = os.path.join(cache_dir, COREOS_PXE_KERNEL)

    cache_file(digests, COREOS_PXE_DIGESTS_URL)
    gpg_verify_file(digests)
    cache_file(kernel, COREOS_PXE_KERNEL_URL)
    validate_digests(digests, kernel)
    cache_file(orig_cpio, COREOS_PXE_IMAGE_URL)
    validate_digests(digests, orig_cpio)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output_kernel = os.path.join(output_dir, os.path.basename(kernel))
    output_cpio = os.path.join(output_dir, os.path.basename(orig_cpio).replace('.cpio.gz', '-oem.cpio.gz'))
    inject_oem(orig_cpio, oem_dir, output_cpio)
    shutil.copy(kernel, output_kernel)

def gpg_verify_file(ascfile):
    d = tempfile.mkdtemp(prefix="oem-gpg-validate")
    try:
        tmpring = os.path.join(d, 'tmp.gpg')
        key = os.path.join(d, 'coreos.key')
        with open(key, 'w+b') as fp:
            fp.write(gpg_key())

        i = cmd.gpg['--batch',
                '--no-default-keyring',
                '--keyring',
                tmpring,
                '--import',
                key]
        print(i)
        i()

        r = cmd.gpg['--batch',
                '--no-default-keyring',
                '--keyring',
                tmpring,
                '--verify',
                ascfile]
        print(r)
        r()

    finally:
        shutil.rmtree(d)

def gpg_key():
    GPG_LONG_ID="50E0885593D2DCB4"
    GPG_KEY="""-----BEGIN PGP PUBLIC KEY BLOCK-----
    Version: GnuPG v2.0.20 (GNU/Linux)

    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
    BeiJ6tEeDHDzdA==
    =4Qn0
    -----END PGP PUBLIC KEY BLOCK-----
    """
    return GPG_KEY

if __name__ == "__main__":
    main()

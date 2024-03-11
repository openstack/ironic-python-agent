#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging
import os

from ironic_lib import utils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import imageutils
from oslo_utils import units
import tenacity

from ironic_python_agent import errors

"""
Imported from ironic_lib/qemu-img.py from commit
c3d59dfffc9804273b49c0556ee09419a35917c1

See https://bugs.launchpad.net/ironic/+bug/2071740 for more details as to why
it moved.

This module also exists in the Ironic repo. Do not modify this module
without also modifying that module.
"""

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

# Limit the memory address space to 1 GiB when running qemu-img
QEMU_IMG_LIMITS = None


def _qemu_img_limits():
    global QEMU_IMG_LIMITS
    if QEMU_IMG_LIMITS is None:
        QEMU_IMG_LIMITS = processutils.ProcessLimits(
            address_space=CONF.disk_utils.image_convert_memory_limit
            * units.Mi)
    return QEMU_IMG_LIMITS


def _retry_on_res_temp_unavailable(exc):
    if (isinstance(exc, processutils.ProcessExecutionError)
            and ('Resource temporarily unavailable' in exc.stderr
                 or 'Cannot allocate memory' in exc.stderr)):
        return True
    return False


def image_info(path, source_format=None):
    """Return an object containing the parsed output from qemu-img info.

    This must only be called on images already validated as safe by the
    format inspector.

    :param path: The path to an image you need information on
    :param source_format: The format of the source image. If this is omitted
                          when deep inspection is enabled, this will raise
                          InvalidImage.
    """
    # NOTE(JayF): This serves as a final exit hatch: if we have deep
    # image inspection enabled, but someone calls this method without an
    # explicit disk_format, there's no way for us to do the call securely.
    if not source_format and not CONF.disable_deep_image_inspection:
        msg = ("Security: qemu_img.image_info called unsafely while deep "
               "image inspection is enabled. This should not be possible, "
               "please contact Ironic developers.")
        raise errors.InvalidImage(details=msg)

    if not os.path.exists(path):
        raise FileNotFoundError("File %s does not exist" % path)

    cmd = [
        'env', 'LC_ALL=C', 'LANG=C',
        'qemu-img', 'info', path,
        '--output=json'
    ]

    if source_format:
        cmd += ['-f', source_format]

    out, err = utils.execute(cmd, prlimit=_qemu_img_limits())
    return imageutils.QemuImgInfo(out, format='json')


@tenacity.retry(
    retry=tenacity.retry_if_exception(_retry_on_res_temp_unavailable),
    stop=tenacity.stop_after_attempt(CONF.disk_utils.image_convert_attempts),
    reraise=True)
def convert_image(source, dest, out_format, run_as_root=False, cache=None,
                  out_of_order=False, sparse_size=None, source_format=None):
    """Convert image to other format.

    This method is only to be run against images who have passed
    format_inspector's safety check, and with the format reported by it
    passed in. Any other usage is a major security risk.
    """
    cmd = ['qemu-img', 'convert', '-O', out_format]
    if cache is not None:
        cmd += ['-t', cache]
    if sparse_size is not None:
        cmd += ['-S', sparse_size]

    if source_format is not None:
        cmd += ['-f', source_format]
    elif not CONF.disable_deep_image_inspection:
        # NOTE(JayF): This serves as a final exit hatch: if we have deep
        # image inspection enabled, but someone calls this method without an
        # explicit disk_format, there's no way for us to do the conversion
        # securely.
        msg = ("Security: qemu_img.convert_image called unsafely while deep "
               "image inspection is enabled. This should not be possible, "
               "please notify Ironic developers.")
        LOG.error(msg)
        raise errors.InvalidImage(details=msg)

    if out_of_order:
        cmd.append('-W')
    cmd += [source, dest]
    # NOTE(TheJulia): Statically set the MALLOC_ARENA_MAX to prevent leaking
    # and the creation of new malloc arenas which will consume the system
    # memory. If limited to 1, qemu-img consumes ~250 MB of RAM, but when
    # another thread tries to access a locked section of memory in use with
    # another thread, then by default a new malloc arena is created,
    # which essentially balloons the memory requirement of the machine.
    # Default for qemu-img is 8 * nCPU * ~250MB (based on defaults +
    # thread/code/process/library overhead. In other words, 64 GB. Limiting
    # this to 3 keeps the memory utilization in happy cases below the overall
    # threshold which is in place in case a malicious image is attempted to
    # be passed through qemu-img.
    env_vars = {'MALLOC_ARENA_MAX': '3'}
    try:
        utils.execute(*cmd, run_as_root=run_as_root,
                      prlimit=_qemu_img_limits(),
                      use_standard_locale=True,
                      env_variables=env_vars)
    except processutils.ProcessExecutionError as e:
        if ('Resource temporarily unavailable' in e.stderr
            or 'Cannot allocate memory' in e.stderr):
            LOG.debug('Failed to convert image, retrying. Error: %s', e)
            # Sync disk caches before the next attempt
            utils.execute('sync')
        raise

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


HDPARM_INFO_TEMPLATE = (
    '/dev/sda:\n'
    '\n'
    'ATA device, with non-removable media\n'
    '\tModel Number:       7 PIN  SATA FDM\n'
    '\tSerial Number:      20131210000000000023\n'
    '\tFirmware Revision:  SVN406\n'
    '\tTransport:          Serial, ATA8-AST, SATA 1.0a, SATA II Extensions, '
    'SATA Rev 2.5, SATA Rev 2.6, SATA Rev 3.0\n'
    'Standards: \n'
    '\tSupported: 9 8 7 6 5\n'
    '\tLikely used: 9\n'
    'Configuration: \n'
    '\tLogical\t\tmax\tcurrent\n'
    '\tcylinders\t16383\t16383\n'
    '\theads\t\t16\t16\n'
    '\tsectors/track\t63\t63\n'
    '\t--\n'
    '\tCHS current addressable sectors:   16514064\n'
    '\tLBA    user addressable sectors:   60579792\n'
    '\tLBA48  user addressable sectors:   60579792\n'
    '\tLogical  Sector size:                   512 bytes\n'
    '\tPhysical Sector size:                   512 bytes\n'
    '\tLogical Sector-0 offset:                  0 bytes\n'
    '\tdevice size with M = 1024*1024:       29579 MBytes\n'
    '\tdevice size with M = 1000*1000:       31016 MBytes (31 GB)\n'
    '\tcache/buffer size  = unknown\n'
    '\tForm Factor: 2.5 inch\n'
    '\tNominal Media Rotation Rate: Solid State Device\n'
    'Capabilities: \n'
    '\tLBA, IORDY(can be disabled)\n'
    '\tQueue depth: 32\n'
    '\tStandby timer values: spec\'d by Standard, no device specific '
    'minimum\n'
    '\tR/W multiple sector transfer: Max = 1\tCurrent = 1\n'
    '\tDMA: mdma0 mdma1 mdma2 udma0 udma1 udma2 udma3 udma4 *udma5\n'
    '\t     Cycle time: min=120ns recommended=120ns\n'
    '\tPIO: pio0 pio1 pio2 pio3 pio4\n'
    '\t     Cycle time: no flow control=120ns  IORDY flow '
    'control=120ns\n'
    'Commands/features: \n'
    '\tEnabled\tSupported:\n'
    '\t   *\tSMART feature set\n'
    '\t    \tSecurity Mode feature set\n'
    '\t   *\tPower Management feature set\n'
    '\t   *\tWrite cache\n'
    '\t   *\tLook-ahead\n'
    '\t   *\tHost Protected Area feature set\n'
    '\t   *\tWRITE_BUFFER command\n'
    '\t   *\tREAD_BUFFER command\n'
    '\t   *\tNOP cmd\n'
    '\t    \tSET_MAX security extension\n'
    '\t   *\t48-bit Address feature set\n'
    '\t   *\tDevice Configuration Overlay feature set\n'
    '\t   *\tMandatory FLUSH_CACHE\n'
    '\t   *\tFLUSH_CACHE_EXT\n'
    '\t   *\tWRITE_{DMA|MULTIPLE}_FUA_EXT\n'
    '\t   *\tWRITE_UNCORRECTABLE_EXT command\n'
    '\t   *\tGen1 signaling speed (1.5Gb/s)\n'
    '\t   *\tGen2 signaling speed (3.0Gb/s)\n'
    '\t   *\tGen3 signaling speed (6.0Gb/s)\n'
    '\t   *\tNative Command Queueing (NCQ)\n'
    '\t   *\tHost-initiated interface power management\n'
    '\t   *\tPhy event counters\n'
    '\t   *\tDMA Setup Auto-Activate optimization\n'
    '\t    \tDevice-initiated interface power management\n'
    '\t   *\tSoftware settings preservation\n'
    '\t    \tunknown 78[8]\n'
    '\t   *\tSMART Command Transport (SCT) feature set\n'
    '\t   *\tSCT Error Recovery Control (AC3)\n'
    '\t   *\tSCT Features Control (AC4)\n'
    '\t   *\tSCT Data Tables (AC5)\n'
    '\t   *\tData Set Management TRIM supported (limit 2 blocks)\n'
    'Security: \n'
    '\tMaster password revision code = 65534\n'
    '\t%(supported)s\n'
    '\t%(enabled)s\n'
    '\t%(locked)s\n'
    '\t%(frozen)s\n'
    '\tnot\texpired: security count\n'
    '\t%(enhanced_erase)s\n'
    '\t24min for SECURITY ERASE UNIT. 24min for ENHANCED SECURITY '
    'ERASE UNIT.\n'
    'Checksum: correct\n'
)

BLK_DEVICE_TEMPLATE = (
    'KNAME="sda" MODEL="TinyUSB Drive" SIZE="3116853504" '
    'ROTA="0" TYPE="disk" SERIAL="123" UUID="F531-BDC3" PARTUUID=""\n'
    'KNAME="sdb" MODEL="Fastable SD131 7" SIZE="10737418240" '
    'ROTA="0" TYPE="disk" UUID="9a5e5cca-e03d-4cbd-9054-9e6ca9048222" '
    'PARTUUID=""\n'
    'KNAME="sdc" MODEL="NWD-BLP4-1600   " SIZE="1765517033472" '
    ' ROTA="0" TYPE="disk" UUID="" PARTUUID=""\n'
    'KNAME="sdd" MODEL="NWD-BLP4-1600   " SIZE="1765517033472" '
    ' ROTA="0" TYPE="disk" UUID="" PARTUUID=""\n'
    'KNAME="loop0" MODEL="" SIZE="109109248" ROTA="1" TYPE="loop" UUID="" '
    'PARTUUID=""\n'
    'KNAME="zram0" MODEL="" SIZE="" ROTA="0" TYPE="disk" UUID="" PARTUUID=""\n'
    'KNAME="ram0" MODEL="" SIZE="8388608" ROTA="0" TYPE="disk" UUID="" '
    'PARTUUID=""\n'
    'KNAME="ram1" MODEL="" SIZE="8388608" ROTA="0" TYPE="disk" UUID="" '
    'PARTUUID=""\n'
    'KNAME="ram2" MODEL="" SIZE="8388608" ROTA="0" TYPE="disk" UUID="" '
    'PARTUUID=""\n'
    'KNAME="ram3" MODEL="" SIZE="8388608" ROTA="0" TYPE="disk" UUID="" '
    'PARTUUID=""\n'
    'KNAME="fd1" MODEL="magic" SIZE="4096" ROTA="1" TYPE="disk" UUID="" '
    'PARTUUID=""\n'
    'KNAME="sdf" MODEL="virtual floppy" SIZE="0" ROTA="1" TYPE="disk" UUID="" '
    'PARTUUID=""'
)

# NOTE(pas-ha) largest device is 1 byte smaller than 4GiB
BLK_DEVICE_TEMPLATE_SMALL = (
    'KNAME="sda" MODEL="TinyUSB Drive" SIZE="3116853504" '
    'ROTA="0" TYPE="disk" UUID="F531-BDC3" PARTUUID=""\n'
    'KNAME="sdb" MODEL="AlmostBigEnough Drive" SIZE="4294967295" '
    'ROTA="0" TYPE="disk" UUID="" PARTUUID=""'
)

# NOTE(TheJulia): This list intentionally contains duplicates
# as the code filters them out by kernel device name.
# NOTE(dszumski): We include some partitions here to verify that
# they are filtered out when not requested. It is assumed that
# ROTA has been set to 0 on some software RAID devices for testing
# purposes. In practice is appears to inherit from the underyling
# devices, so in this example it would normally be 1.
RAID_BLK_DEVICE_TEMPLATE = (
    'KNAME="sda" MODEL="DRIVE 0" SIZE="1765517033472" '
    'ROTA="1" TYPE="disk" UUID="" PARTUUID=""\n'
    'KNAME="sda1" MODEL="DRIVE 0" SIZE="107373133824" '
    'ROTA="1" TYPE="part" UUID="" PARTUUID=""\n'
    'KNAME="sdb" MODEL="DRIVE 1" SIZE="1765517033472" '
    'ROTA="1" TYPE="disk" UUID="" PARTUUID=""\n'
    'KNAME="sdb" MODEL="DRIVE 1" SIZE="1765517033472" '
    'ROTA="1" TYPE="disk" UUID="" PARTUUID=""\n'
    'KNAME="sdb1" MODEL="DRIVE 1" SIZE="107373133824" '
    'ROTA="1" TYPE="part" UUID="" PARTUUID=""\n'
    'KNAME="md0p1" MODEL="RAID" SIZE="107236818944" '
    'ROTA="0" TYPE="md" UUID="" PARTUUID=""\n'
    'KNAME="md0" MODEL="RAID" SIZE="1765517033470" '
    'ROTA="0" TYPE="raid1" UUID="" PARTUUID=""\n'
    'KNAME="md0" MODEL="RAID" SIZE="1765517033470" '
    'ROTA="0" TYPE="raid1" UUID="" PARTUUID=""\n'
    'KNAME="md1" MODEL="RAID" SIZE="" ROTA="0" TYPE="raid1" UUID="" '
    'PARTUUID=""'
)

SHRED_OUTPUT_0_ITERATIONS_ZERO_FALSE = ()

SHRED_OUTPUT_1_ITERATION_ZERO_TRUE = (
    'shred: /dev/sda: pass 1/2 (random)...\n'
    'shred: /dev/sda: pass 1/2 (random)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 1/2 (random)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 1/2 (random)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 1/2 (random)...29GiB/29GiB 100%\n'
    'shred: /dev/sda: pass 2/2 (000000)...\n'
    'shred: /dev/sda: pass 2/2 (000000)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 2/2 (000000)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 2/2 (000000)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 2/2 (000000)...29GiB/29GiB 100%\n'
)

SHRED_OUTPUT_2_ITERATIONS_ZERO_FALSE = (
    'shred: /dev/sda: pass 1/2 (random)...\n'
    'shred: /dev/sda: pass 1/2 (random)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 1/2 (random)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 1/2 (random)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 1/2 (random)...29GiB/29GiB 100%\n'
    'shred: /dev/sda: pass 2/2 (random)...\n'
    'shred: /dev/sda: pass 2/2 (random)...4.9GiB/29GiB 17%\n'
    'shred: /dev/sda: pass 2/2 (random)...15GiB/29GiB 51%\n'
    'shred: /dev/sda: pass 2/2 (random)...20GiB/29GiB 69%\n'
    'shred: /dev/sda: pass 2/2 (random)...29GiB/29GiB 100%\n'
)


LSCPU_OUTPUT = """
Architecture:          x86_64
CPU op-mode(s):        32-bit, 64-bit
Byte Order:            Little Endian
CPU(s):                4
On-line CPU(s) list:   0-3
Thread(s) per core:    1
Core(s) per socket:    4
Socket(s):             1
NUMA node(s):          1
Vendor ID:             GenuineIntel
CPU family:            6
Model:                 45
Model name:            Intel(R) Xeon(R) CPU E5-2609 0 @ 2.40GHz
Stepping:              7
CPU MHz:               1290.000
CPU max MHz:           2400.0000
CPU min MHz:           1200.0000
BogoMIPS:              4800.06
Virtualization:        VT-x
L1d cache:             32K
L1i cache:             32K
L2 cache:              256K
L3 cache:              10240K
NUMA node0 CPU(s):     0-3
"""

LSCPU_OUTPUT_NO_MAX_MHZ = """
Architecture:          x86_64
CPU op-mode(s):        32-bit, 64-bit
Byte Order:            Little Endian
CPU(s):                12
On-line CPU(s) list:   0-11
Thread(s) per core:    2
Core(s) per socket:    6
Socket(s):             1
NUMA node(s):          1
Vendor ID:             GenuineIntel
CPU family:            6
Model:                 63
Model name:            Intel(R) Xeon(R) CPU E5-1650 v3 @ 3.50GHz
Stepping:              2
CPU MHz:               1794.433
BogoMIPS:              6983.57
Virtualization:        VT-x
L1d cache:             32K
L1i cache:             32K
L2 cache:              256K
L3 cache:              15360K
NUMA node0 CPU(s):     0-11
"""

# NOTE(dtanstur): flags list stripped down for sanity reasons
CPUINFO_FLAGS_OUTPUT = """
flags           : fpu vme de pse
"""

LSHW_JSON_OUTPUT_V1 = ("""
{
  "id": "fuzzypickles",
  "product": "ABC123 (GENERIC_SERVER)",
  "vendor": "GENERIC",
  "serial": "1234567",
  "width": 64,
  "capabilities": {
    "smbios-2.7": "SMBIOS version 2.7",
    "dmi-2.7": "DMI version 2.7",
    "vsyscall32": "32-bit processes"
  },
  "children": [
    {
      "id": "core",
      "description": "Motherboard",
      "product": "ABC123",
      "vendor": "GENERIC",
      "serial": "ABCDEFGHIJK",
      "children": [
        {
          "id": "memory",
          "class": "memory",
          "description": "System Memory",
          "units": "bytes",
          "size": 4294967296,
          "children": [
            {
              "id": "bank:0",
              "class": "memory",
              "physid": "0",
              "units": "bytes",
              "size": 2147483648,
              "width": 64,
              "clock": 1600000000
            },
            {
              "id": "bank:1",
              "class": "memory",
              "physid": "1"
            },
            {
              "id": "bank:2",
              "class": "memory",
              "physid": "2",
              "units": "bytes",
              "size": 1073741824,
              "width": 64,
              "clock": 1600000000
            },
            {
              "id": "bank:3",
              "class": "memory",
              "physid": "3",
              "units": "bytes",
              "size": 1073741824,
              "width": 64,
              "clock": 1600000000
            }
          ]
        },
        {
          "id": "cpu:0",
          "class": "processor",
          "claimed": true,
          "product": "Intel Xeon E312xx (Sandy Bridge)",
          "vendor": "Intel Corp.",
          "physid": "1",
          "businfo": "cpu@0",
          "width": 64,
          "capabilities": {
            "fpu": "mathematical co-processor",
            "fpu_exception": "FPU exceptions reporting",
            "wp": true,
            "mmx": "multimedia extensions (MMX)"
          }
        }
      ]
    },
    {
      "id": "network:0",
      "class": "network",
      "claimed": true,
      "description": "Ethernet interface",
      "physid": "1",
      "logicalname": "ovs-tap",
      "serial": "1c:90:c0:f9:4e:a1",
      "units": "bit/s",
      "size": 10000000000,
      "configuration": {
        "autonegotiation": "off",
        "broadcast": "yes",
        "driver": "veth",
        "driverversion": "1.0",
        "duplex": "full",
        "link": "yes",
        "multicast": "yes",
        "port": "twisted pair",
        "speed": "10Gbit/s"
      },
      "capabilities": {
        "ethernet": true,
        "physical": "Physical interface"
      }
    }
  ]
}
""", "")

LSHW_JSON_OUTPUT_V2 = ("""
{
  "id" : "bumblebee",
  "class" : "system",
  "claimed" : true,
  "handle" : "DMI:0001",
  "description" : "Rack Mount Chassis",
  "product" : "ABCD",
  "vendor" : "ABCD",
  "version" : "1234",
  "serial" : "1234",
  "width" : 64,
  "configuration" : {
    "boot" : "normal",
    "chassis" : "rackmount",
    "family" : "Intel Grantley EP",
    "sku" : "NULL",
    "uuid" : "00010002-0003-0004-0005-000600070008"
  },
  "capabilities" : {
    "smbios-2.8" : "SMBIOS version 2.8",
    "dmi-2.7" : "DMI version 2.7",
    "vsyscall32" : "32-bit processes"
  },
  "children" : [
    {
      "id" : "core",
      "class" : "bus",
      "claimed" : true,
      "handle" : "DMI:0002",
      "description" : "Motherboard",
      "product" : "ABCD",
      "vendor" : "ABCD",
      "physid" : "0",
      "version" : "1234",
      "serial" : "1234",
      "slot" : "NULL",
      "children" : [
        {
          "id" : "memory:0",
          "class" : "memory",
          "claimed" : true,
          "handle" : "DMI:004A",
          "description" : "System Memory",
          "physid" : "4a",
          "slot" : "System board or motherboard",
          "children" : [
            {
              "id" : "bank:0",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:004C",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "0",
              "serial" : "101B6543",
              "slot" : "DIMM_A0",
              "units" : "bytes",
              "size" : 17179869184,
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:1",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:004E",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "1",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A1"
            },
            {
              "id" : "bank:2",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:004F",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "2",
              "serial" : "101B654E",
              "slot" : "DIMM_A2",
              "units" : "bytes",
              "size" : 17179869184,
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:3",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0051",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "3",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A3"
            }
          ]
        },
        {
          "id" : "memory:1",
          "class" : "memory",
          "claimed" : true,
          "handle" : "DMI:0052",
          "description" : "System Memory",
          "physid" : "52",
          "slot" : "System board or motherboard",
          "children" : [
            {
              "id" : "bank:0",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0054",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "0",
              "serial" : "101B6545",
              "slot" : "DIMM_A4",
              "units" : "bytes",
              "size" : 17179869184,
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:1",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0056",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "1",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A5"
            },
            {
              "id" : "bank:2",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0057",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "2",
              "serial" : "101B6540",
              "slot" : "DIMM_A6",
              "units" : "bytes",
              "size" : 17179869184,
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:3",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0059",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "3",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A7"
            }
          ]
        },
        {
          "id" : "memory:4",
          "class" : "memory",
          "physid" : "1"
        },
        {
          "id" : "memory:5",
          "class" : "memory",
          "physid" : "2"
        }
      ]
    }
  ]
}
""", "")

LSHW_JSON_OUTPUT_NO_MEMORY_BANK_SIZE = ("""
{
  "id" : "bumblebee",
  "class" : "system",
  "claimed" : true,
  "handle" : "DMI:0001",
  "description" : "Rack Mount Chassis",
  "product" : "ABCD",
  "vendor" : "ABCD",
  "version" : "1234",
  "serial" : "1234",
  "width" : 64,
  "configuration" : {
    "boot" : "normal",
    "chassis" : "rackmount",
    "family" : "Intel Grantley EP",
    "sku" : "NULL",
    "uuid" : "00010002-0003-0004-0005-000600070008"
  },
  "capabilities" : {
    "smbios-2.8" : "SMBIOS version 2.8",
    "dmi-2.7" : "DMI version 2.7",
    "vsyscall32" : "32-bit processes"
  },
  "children" : [
    {
      "id" : "core",
      "class" : "bus",
      "claimed" : true,
      "handle" : "DMI:0002",
      "description" : "Motherboard",
      "product" : "ABCD",
      "vendor" : "ABCD",
      "physid" : "0",
      "version" : "1234",
      "serial" : "1234",
      "slot" : "NULL",
      "children" : [
        {
          "id" : "memory:0",
          "class" : "memory",
          "claimed" : true,
          "handle" : "DMI:004A",
          "description" : "System Memory",
          "physid" : "4a",
          "slot" : "System board or motherboard",
          "units" : "bytes",
          "size" : 34359738368,
          "children" : [
            {
              "id" : "bank:0",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:004C",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "0",
              "serial" : "101B6543",
              "slot" : "DIMM_A0",
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:1",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:004E",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "1",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A1"
            },
            {
              "id" : "bank:2",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:004F",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "2",
              "serial" : "101B654E",
              "slot" : "DIMM_A2",
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:3",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0051",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "3",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A3"
            }
          ]
        },
        {
          "id" : "memory:1",
          "class" : "memory",
          "claimed" : true,
          "handle" : "DMI:0052",
          "description" : "System Memory",
          "physid" : "52",
          "slot" : "System board or motherboard",
          "units" : "bytes",
          "size" : 34359738368,
          "children" : [
            {
              "id" : "bank:0",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0054",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "0",
              "serial" : "101B6545",
              "slot" : "DIMM_A4",
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:1",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0056",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "1",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A5"
            },
            {
              "id" : "bank:2",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0057",
              "description" : "DIMM Synchronous 2133 MHz (0.5 ns)",
              "product" : "36ASF2G72PZ-2G1A2",
              "vendor" : "Micron",
              "physid" : "2",
              "serial" : "101B6540",
              "slot" : "DIMM_A6",
              "width" : 64,
              "clock" : 2133000000
            },
            {
              "id" : "bank:3",
              "class" : "memory",
              "claimed" : true,
              "handle" : "DMI:0059",
              "description" : "DIMM Synchronous [empty]",
              "product" : "NO DIMM",
              "vendor" : "NO DIMM",
              "physid" : "3",
              "serial" : "NO DIMM",
              "slot" : "DIMM_A7"
            }
          ]
        },
        {
          "id" : "memory:4",
          "class" : "memory",
          "physid" : "1"
        },
        {
          "id" : "memory:5",
          "class" : "memory",
          "physid" : "2"
        }
      ]
    }
  ]
}
""", "")

LSHW_JSON_OUTPUT_ARM64 = ("""
{
  "id" : "debian",
  "class" : "system",
  "claimed" : true,
  "description" : "Computer",
  "width" : 64,
  "capabilities" : {
    "cp15_barrier" : true,
    "setend" : true,
    "swp" : true
  },
  "children" : [
    {
      "id" : "core",
      "class" : "bus",
      "claimed" : true,
      "description" : "Motherboard",
      "physid" : "0",
      "children" : [
        {
          "id" : "memory",
          "class" : "memory",
          "claimed" : true,
          "description" : "System memory",
          "physid" : "0",
          "units" : "bytes",
          "size" : 4143972352
        },
        {
          "id" : "cpu:0",
          "class" : "processor",
          "claimed" : true,
          "physid" : "1",
          "businfo" : "cpu@0",
          "capabilities" : {
            "fp" : "Floating point instructions",
            "asimd" : "Advanced SIMD",
            "evtstrm" : "Event stream",
            "aes" : "AES instructions",
            "pmull" : "PMULL instruction",
            "sha1" : "SHA1 instructions",
            "sha2" : "SHA2 instructions",
            "crc32" : "CRC extension",
            "cpuid" : true
          }
        },
        {
          "id" : "pci:0",
          "class" : "bridge",
          "claimed" : true,
          "handle" : "PCIBUS:0002:e9",
          "physid" : "100",
          "businfo" : "pci@0002:e8:00.0",
          "version" : "01",
          "width" : 32,
          "clock" : 33000000,
          "configuration" : {
            "driver" : "pcieport"
          },
          "capabilities" : {
            "pci" : true,
            "pm" : "Power Management",
            "msi" : "Message Signalled Interrupts",
            "pciexpress" : "PCI Express",
            "bus_master" : "bus mastering",
            "cap_list" : "PCI capabilities listing"
          }
        }
      ]
    },
    {
      "id" : "network:0",
      "class" : "network",
      "claimed" : true,
      "description" : "Ethernet interface",
      "physid" : "2",
      "logicalname" : "enahisic2i2",
      "serial" : "d0:ef:c1:e9:bf:33",
      "configuration" : {
        "autonegotiation" : "off",
        "broadcast" : "yes",
        "driver" : "hns",
        "driverversion" : "2.0",
        "firmware" : "N/A",
        "link" : "no",
        "multicast" : "yes",
        "port" : "fibre"
      },
      "capabilities" : {
        "ethernet" : true,
        "physical" : "Physical interface",
        "fibre" : "optical fibre"
      }
    }
  ]
}
""", "")

SMARTCTL_NORMAL_OUTPUT = ("""
smartctl 6.2 2017-02-27 r4394 [x86_64-linux-3.10.0-693.21.1.el7.x86_64] (local build)
Copyright (C) 2002-13, Bruce Allen, Christian Franke, www.smartmontools.org

ATA Security is:  Disabled, NOT FROZEN [SEC1]
""")  # noqa

SMARTCTL_UNAVAILABLE_OUTPUT = ("""
smartctl 6.2 2017-02-27 r4394 [x86_64-linux-3.10.0-693.21.1.el7.x86_64] (local build)
Copyright (C) 2002-13, Bruce Allen, Christian Franke, www.smartmontools.org

ATA Security is:  Unavailable
""")  # noqa


IPMITOOL_LAN6_PRINT_DYNAMIC_ADDR = """
IPv6 Dynamic Address 0:
    Source/Type:    DHCPv6
    Address:        2001:1234:1234:1234:1234:1234:1234:1234/64
    Status:         active
IPv6 Dynamic Address 1:
    Source/Type:    DHCPv6
    Address:        ::/0
    Status:         active
IPv6 Dynamic Address 2:
    Source/Type:    DHCPv6
    Address:        ::/0
    Status:         active
"""

IPMITOOL_LAN6_PRINT_STATIC_ADDR = """
IPv6 Static Address 0:
    Enabled:        yes
    Address:        2001:5678:5678:5678:5678:5678:5678:5678/64
    Status:         active
IPv6 Static Address 1:
    Enabled:        no
    Address:        ::/0
    Status:         disabled
IPv6 Static Address 2:
    Enabled:        no
    Address:        ::/0
    Status:         disabled
"""

MDADM_DETAIL_OUTPUT = ("""/dev/md0:
           Version : 1.0
     Creation Time : Fri Feb 15 12:37:44 2019
        Raid Level : raid1
        Array Size : 1048512 (1023.94 MiB 1073.68 MB)
     Used Dev Size : 1048512 (1023.94 MiB 1073.68 MB)
      Raid Devices : 2
     Total Devices : 2
       Persistence : Superblock is persistent

       Update Time : Fri Feb 15 12:38:02 2019
             State : clean
    Active Devices : 2
   Working Devices : 2
    Failed Devices : 0
     Spare Devices : 0

Consistency Policy : resync

              Name : abc.xyz.com:0  (local to host abc.xyz.com)
              UUID : 83143055:2781ddf5:2c8f44c7:9b45d92e
            Events : 17

    Number   Major   Minor   RaidDevice State
       0     253       64        0      active sync   /dev/vde1
       1     253       80        1      active sync   /dev/vdf1
""")

MDADM_DETAIL_OUTPUT_WHOLE_DEVICE = ("""/dev/md0:
           Version : 1.0
     Creation Time : Fri Feb 15 12:37:44 2019
        Raid Level : raid1
        Array Size : 1048512 (1023.94 MiB 1073.68 MB)
     Used Dev Size : 1048512 (1023.94 MiB 1073.68 MB)
      Raid Devices : 2
     Total Devices : 2
       Persistence : Superblock is persistent

       Update Time : Fri Feb 15 12:38:02 2019
             State : clean
    Active Devices : 2
   Working Devices : 2
    Failed Devices : 0
     Spare Devices : 0

Consistency Policy : resync

              Name : abc.xyz.com:0  (local to host abc.xyz.com)
              UUID : 83143055:2781ddf5:2c8f44c7:9b45d92e
            Events : 17

    Number   Major   Minor   RaidDevice State
       0     253       64        0      active sync   /dev/vde
       1     253       80        1      active sync   /dev/vdf
""")

MDADM_DETAIL_OUTPUT_NVME = ("""/dev/md0:
        Version : 1.2
  Creation Time : Wed Aug  7 13:47:27 2019
     Raid Level : raid1
     Array Size : 439221248 (418.87 GiB 449.76 GB)
  Used Dev Size : 439221248 (418.87 GiB 449.76 GB)
   Raid Devices : 2
  Total Devices : 2
    Persistence : Superblock is persistent

  Intent Bitmap : Internal

    Update Time : Wed Aug  7 14:37:21 2019
          State : clean
 Active Devices : 2
Working Devices : 2
 Failed Devices : 0
  Spare Devices : 0

           Name : rescue:0  (local to host rescue)
           UUID : abe222bc:98735860:ab324674:e4076313
         Events : 426

    Number   Major   Minor   RaidDevice State
       0     259        2        0      active sync   /dev/nvme0n1p1
       1     259        3        1      active sync   /dev/nvme1n1p1
""")


MDADM_DETAIL_OUTPUT_BROKEN_RAID0 = ("""/dev/md126:
           Version : 1.2
        Raid Level : raid0
     Total Devices : 1
       Persistence : Superblock is persistent

             State : inactive
   Working Devices : 1

              Name : prj6ogxgyzd:1
              UUID : b5e136c0:a7e379b7:db25e45d:4b63928b
            Events : 0

    Number   Major   Minor   RaidDevice

       -       8        2        -        /dev/sda2
""")


MDADM_EXAMINE_OUTPUT_MEMBER = ("""/dev/sda1:
          Magic : a92b4efc
        Version : 1.2
    Feature Map : 0x0
     Array UUID : 83143055:2781ddf5:2c8f44c7:9b45d92e
           Name : horse.cern.ch:1  (local to host abc.xyz.com)
  Creation Time : Tue Jun 11 12:43:37 2019
     Raid Level : raid1
   Raid Devices : 2

 Avail Dev Size : 2093056 sectors (1022.00 MiB 1071.64 MB)
     Array Size : 1046528 KiB (1022.00 MiB 1071.64 MB)
    Data Offset : 2048 sectors
   Super Offset : 8 sectors
   Unused Space : before=1968 sectors, after=0 sectors
          State : clean
    Device UUID : 88bf2723:d082f14f:f95e87cf:b7c59b83

    Update Time : Sun Sep 27 01:00:08 2020
  Bad Block Log : 512 entries available at offset 16 sectors
       Checksum : 340a1610 - correct
         Events : 178


   Device Role : Active device 0
   Array State : A. ('A' == active, '.' == missing, 'R' == replacing)
""")


MDADM_EXAMINE_OUTPUT_NON_MEMBER = ("""/dev/sdz1:
          Magic : a92b4efc
        Version : 1.2
    Feature Map : 0x0
     Array UUID : 83143055:2781ddf5:2c8f44c7:9b45d92f
           Name : horse.cern.ch:1  (local to host abc.xyz.com)
  Creation Time : Tue Jun 11 12:43:37 2019
     Raid Level : raid1
   Raid Devices : 2

 Avail Dev Size : 2093056 sectors (1022.00 MiB 1071.64 MB)
     Array Size : 1046528 KiB (1022.00 MiB 1071.64 MB)
    Data Offset : 2048 sectors
   Super Offset : 8 sectors
   Unused Space : before=1968 sectors, after=0 sectors
          State : clean
    Device UUID : 88bf2723:d082f14f:f95e87cf:b7c59b84

    Update Time : Sun Sep 27 01:00:08 2020
  Bad Block Log : 512 entries available at offset 16 sectors
       Checksum : 340a1610 - correct
         Events : 178


   Device Role : Active device 0
   Array State : A. ('A' == active, '.' == missing, 'R' == replacing)
""")


PROC_MOUNTS_OUTPUT = ("""
debugfs /sys/kernel/debug debugfs rw,relatime 0 0
/dev/sda2 / ext4 rw,relatime,errors=remount-ro 0 0
tmpfs /run/user/1000 tmpfs rw,nosuid,nodev,relatime  0 0
pstore /sys/fs/pstore pstore rw,nosuid,nodev,noexec,relatime 0 0
/dev/loop19 /snap/core/10126 squashfs ro,nodev,relatime 0 0
""")


PROC_MOUNTS_OUTPUT_NO_PSTORE = ("""
debugfs /sys/kernel/debug debugfs rw,relatime 0 0
/dev/sda2 / ext4 rw,relatime,errors=remount-ro 0 0
tmpfs /run/user/1000 tmpfs rw,nosuid,nodev,relatime  0 0
pstore /sys/fs/pstore qstore rw,nosuid,nodev,noexec,relatime 0 0
/dev/loop19 /snap/core/10126 squashfs ro,nodev,relatime 0 0
""")

NVME_CLI_INFO_TEMPLATE_CRYPTO_SUPPORTED = ("""
{
  "vid" : 5559,
  "ssvid" : 5559,
  "sn" : "1951B3444502        ",
  "mn" : "WDC PC SN730 SDBQNTY-256G-1001          ",
  "fr" : "11170101",
  "rab" : 4,
  "ieee" : 6980,
  "cmic" : 0,
  "mdts" : 7,
  "cntlid" : 8215,
  "ver" : 66304,
  "rtd3r" : 500000,
  "rtd3e" : 1000000,
  "oaes" : 512,
  "ctratt" : 2,
  "rrls" : 0,
  "crdt1" : 0,
  "crdt2" : 0,
  "crdt3" : 0,
  "oacs" : 23,
  "acl" : 4,
  "aerl" : 7,
  "frmw" : 20,
  "lpa" : 30,
  "elpe" : 255,
  "npss" : 4,
  "avscc" : 1,
  "apsta" : 1,
  "wctemp" : 357,
  "cctemp" : 361,
  "mtfa" : 50,
  "hmpre" : 0,
  "hmmin" : 0,
  "tnvmcap" : 256060514304,
  "unvmcap" : 0,
  "rpmbs" : 0,
  "edstt" : 26,
  "dsto" : 1,
  "fwug" : 1,
  "kas" : 0,
  "hctma" : 1,
  "mntmt" : 273,
  "mxtmt" : 357,
  "sanicap" : 1610612739,
  "hmminds" : 0,
  "hmmaxd" : 0,
  "nsetidmax" : 0,
  "anatt" : 0,
  "anacap" : 0,
  "anagrpmax" : 0,
  "nanagrpid" : 0,
  "sqes" : 102,
  "cqes" : 68,
  "maxcmd" : 0,
  "nn" : 1,
  "oncs" : 95,
  "fuses" : 0,
  "fna" : 4,
  "vwc" : 7,
  "awun" : 0,
  "awupf" : 0,
  "nvscc" : 1,
  "nwpc" : 0,
  "acwu" : 0,
  "sgls" : 0,
  "subnqn" : "nqn.2018-01.com.wdc:guid:E8238FA6BF53-0001-001B444A44C72385",
  "ioccsz" : 0,
  "iorcsz" : 0,
  "icdoff" : 0,
  "ctrattr" : 0,
  "msdbd" : 0,
  "psds" : [
    {
      "max_power" : 500,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 0,
      "read_lat" : 0,
      "write_tput" : 0,
      "write_lat" : 0,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 350,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 1,
      "read_lat" : 1,
      "write_tput" : 1,
      "write_lat" : 1,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 300,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 2,
      "read_lat" : 2,
      "write_tput" : 2,
      "write_lat" : 2,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 700,
      "flags" : 3,
      "entry_lat" : 4000,
      "exit_lat" : 10000,
      "read_tput" : 3,
      "read_lat" : 3,
      "write_tput" : 3,
      "write_lat" : 3,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 35,
      "flags" : 3,
      "entry_lat" : 4000,
      "exit_lat" : 40000,
      "read_tput" : 4,
      "read_lat" : 4,
      "write_tput" : 4,
      "write_lat" : 4,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    }
  ]
}
""")

NVME_CLI_INFO_TEMPLATE_USERDATA_SUPPORTED = ("""
{
  "vid" : 5559,
  "ssvid" : 5559,
  "sn" : "1951B3444502        ",
  "mn" : "WDC PC SN730 SDBQNTY-256G-1001          ",
  "fr" : "11170101",
  "rab" : 4,
  "ieee" : 6980,
  "cmic" : 0,
  "mdts" : 7,
  "cntlid" : 8215,
  "ver" : 66304,
  "rtd3r" : 500000,
  "rtd3e" : 1000000,
  "oaes" : 512,
  "ctratt" : 2,
  "rrls" : 0,
  "crdt1" : 0,
  "crdt2" : 0,
  "crdt3" : 0,
  "oacs" : 23,
  "acl" : 4,
  "aerl" : 7,
  "frmw" : 20,
  "lpa" : 30,
  "elpe" : 255,
  "npss" : 4,
  "avscc" : 1,
  "apsta" : 1,
  "wctemp" : 357,
  "cctemp" : 361,
  "mtfa" : 50,
  "hmpre" : 0,
  "hmmin" : 0,
  "tnvmcap" : 256060514304,
  "unvmcap" : 0,
  "rpmbs" : 0,
  "edstt" : 26,
  "dsto" : 1,
  "fwug" : 1,
  "kas" : 0,
  "hctma" : 1,
  "mntmt" : 273,
  "mxtmt" : 357,
  "sanicap" : 1610612739,
  "hmminds" : 0,
  "hmmaxd" : 0,
  "nsetidmax" : 0,
  "anatt" : 0,
  "anacap" : 0,
  "anagrpmax" : 0,
  "nanagrpid" : 0,
  "sqes" : 102,
  "cqes" : 68,
  "maxcmd" : 0,
  "nn" : 1,
  "oncs" : 95,
  "fuses" : 0,
  "fna" : 0,
  "vwc" : 7,
  "awun" : 0,
  "awupf" : 0,
  "nvscc" : 1,
  "nwpc" : 0,
  "acwu" : 0,
  "sgls" : 0,
  "subnqn" : "nqn.2018-01.com.wdc:guid:E8238FA6BF53-0001-001B444A44C72385",
  "ioccsz" : 0,
  "iorcsz" : 0,
  "icdoff" : 0,
  "ctrattr" : 0,
  "msdbd" : 0,
  "psds" : [
    {
      "max_power" : 500,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 0,
      "read_lat" : 0,
      "write_tput" : 0,
      "write_lat" : 0,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 350,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 1,
      "read_lat" : 1,
      "write_tput" : 1,
      "write_lat" : 1,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 300,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 2,
      "read_lat" : 2,
      "write_tput" : 2,
      "write_lat" : 2,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 700,
      "flags" : 3,
      "entry_lat" : 4000,
      "exit_lat" : 10000,
      "read_tput" : 3,
      "read_lat" : 3,
      "write_tput" : 3,
      "write_lat" : 3,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 35,
      "flags" : 3,
      "entry_lat" : 4000,
      "exit_lat" : 40000,
      "read_tput" : 4,
      "read_lat" : 4,
      "write_tput" : 4,
      "write_lat" : 4,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    }
  ]
}
""")

NVME_CLI_INFO_TEMPLATE_FORMAT_UNSUPPORTED = ("""
{
  "vid" : 5559,
  "ssvid" : 5559,
  "sn" : "1951B3444502        ",
  "mn" : "WDC PC SN730 SDBQNTY-256G-1001          ",
  "fr" : "11170101",
  "rab" : 4,
  "ieee" : 6980,
  "cmic" : 0,
  "mdts" : 7,
  "cntlid" : 8215,
  "ver" : 66304,
  "rtd3r" : 500000,
  "rtd3e" : 1000000,
  "oaes" : 512,
  "ctratt" : 2,
  "rrls" : 0,
  "crdt1" : 0,
  "crdt2" : 0,
  "crdt3" : 0,
  "oacs" : 0,
  "acl" : 4,
  "aerl" : 7,
  "frmw" : 20,
  "lpa" : 30,
  "elpe" : 255,
  "npss" : 4,
  "avscc" : 1,
  "apsta" : 1,
  "wctemp" : 357,
  "cctemp" : 361,
  "mtfa" : 50,
  "hmpre" : 0,
  "hmmin" : 0,
  "tnvmcap" : 256060514304,
  "unvmcap" : 0,
  "rpmbs" : 0,
  "edstt" : 26,
  "dsto" : 1,
  "fwug" : 1,
  "kas" : 0,
  "hctma" : 1,
  "mntmt" : 273,
  "mxtmt" : 357,
  "sanicap" : 1610612739,
  "hmminds" : 0,
  "hmmaxd" : 0,
  "nsetidmax" : 0,
  "anatt" : 0,
  "anacap" : 0,
  "anagrpmax" : 0,
  "nanagrpid" : 0,
  "sqes" : 102,
  "cqes" : 68,
  "maxcmd" : 0,
  "nn" : 1,
  "oncs" : 95,
  "fuses" : 0,
  "fna" : 0,
  "vwc" : 7,
  "awun" : 0,
  "awupf" : 0,
  "nvscc" : 1,
  "nwpc" : 0,
  "acwu" : 0,
  "sgls" : 0,
  "subnqn" : "nqn.2018-01.com.wdc:guid:E8238FA6BF53-0001-001B444A44C72385",
  "ioccsz" : 0,
  "iorcsz" : 0,
  "icdoff" : 0,
  "ctrattr" : 0,
  "msdbd" : 0,
  "psds" : [
    {
      "max_power" : 500,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 0,
      "read_lat" : 0,
      "write_tput" : 0,
      "write_lat" : 0,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 350,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 1,
      "read_lat" : 1,
      "write_tput" : 1,
      "write_lat" : 1,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 300,
      "flags" : 0,
      "entry_lat" : 0,
      "exit_lat" : 0,
      "read_tput" : 2,
      "read_lat" : 2,
      "write_tput" : 2,
      "write_lat" : 2,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 700,
      "flags" : 3,
      "entry_lat" : 4000,
      "exit_lat" : 10000,
      "read_tput" : 3,
      "read_lat" : 3,
      "write_tput" : 3,
      "write_lat" : 3,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    },
    {
      "max_power" : 35,
      "flags" : 3,
      "entry_lat" : 4000,
      "exit_lat" : 40000,
      "read_tput" : 4,
      "read_lat" : 4,
      "write_tput" : 4,
      "write_lat" : 4,
      "idle_power" : 0,
      "idle_scale" : 0,
      "active_power" : 0,
      "active_work_scale" : 0
    }
  ]
}
""")

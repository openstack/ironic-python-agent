#!/bin/sh
# The DHCP portion is now separated out, in order to not slow the boot down
# only to wait for slow network cards
. /etc/init.d/tc-functions

# This waits until all devices have registered
/sbin/udevadm settle --timeout=%UDEV_SETTLE_TIMEOUT%

NETDEVICES="$(awk -F: '/eth.:|tr.:/{print $1}' /proc/net/dev 2>/dev/null)"
echo "$0: Discovered network devices: $NETDEVICES"
for DEVICE in $NETDEVICES; do
  ifconfig $DEVICE | grep -q "inet addr"
  if [ "$?" != 0 ]; then
    echo -e "\nNetwork device $DEVICE detected, DHCP broadcasting for IP."
    trap 2 3 11
    /sbin/udhcpc -b -i $DEVICE -x hostname:$(/bin/hostname) -p /var/run/udhcpc.$DEVICE.pid 2>&1 &
    trap "" 2 3 11
    sleep 1
  fi
done


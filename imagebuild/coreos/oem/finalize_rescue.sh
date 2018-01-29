#!/bin/bash

create_rescue_user() {
    echo "Adding rescue user with root privileges..."
    crypted_pass=$(</etc/ipa-rescue-config/ipa-rescue-password)
    sudo useradd -m rescue -G sudo -p $crypted_pass
    sudo echo "rescue ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/rescue
}

setup_dhcp_network() {
    DHCP_CONFIG_TEMPLATE=/usr/share/oem/rescue-dhcp-config.network

    echo "Configuring DHCP networks on all interfaces..."
    echo "Removing all existing network configuration..."
    sudo rm /etc/systemd/network/*

    echo "Configuring all interfaces except loopback to DHCP..."
    for interface in $(ls /sys/class/net) ; do
        if [ $interface != "lo" ]; then
            sudo sed "s/RESCUE_NETWORK_INTERFACE/$interface/" $DHCP_CONFIG_TEMPLATE > /etc/systemd/network/50-$interface.network || true
        fi
    done

    sudo systemctl restart systemd-networkd
}

echo "Attempting to start rescue mode configuration..."
if [ -f /etc/ipa-rescue-config/ipa-rescue-password ]; then
    # NOTE(mariojv) An exit code of 0 is always forced here to avoid making IPA
    # restart after something fails. IPA should not restart when this script
    # executes to avoid exposing its API to a tenant network.
    create_rescue_user || exit 0
    setup_dhcp_network || exit 0
    # TODO(mariojv) Add support for configdrive and static networks
else
    echo "One or more of the files needed for rescue mode does not exist, not rescuing."
fi

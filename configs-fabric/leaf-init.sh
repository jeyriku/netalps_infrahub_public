#!/bin/sh
# Leaf kernel plumbing: VRF tenant1 + L3VNI 50001 + one VLAN/L2VNI with anycast gateway.
# Usage: sh /leaf-init.sh <vtep_ip> <vlan>   e.g. sh /leaf-init.sh 10.1.1.1 10
# Derived: L2VNI = 10000 + vlan, gateway = 192.168.1<vlan>.1/24
set -e
VTEP=$1
VLAN=$2
VNI=$((10000 + VLAN))

sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv6.conf.all.disable_ipv6=0
sysctl -w net.ipv4.conf.all.rp_filter=0
sysctl -w net.ipv4.conf.default.rp_filter=0

ip link add tenant1 type vrf table 1001
ip link set tenant1 up
ip link add br50001 type bridge
ip link set br50001 master tenant1 addrgenmode none
ip link add vxlan50001 type vxlan id 50001 local "$VTEP" dstport 4789 nolearning
ip link set vxlan50001 master br50001 addrgenmode none
ip link add "br$VLAN" type bridge
ip link set "br$VLAN" master tenant1 address 00:00:5e:00:01:01
ip addr add "192.168.1$VLAN.1/24" dev "br$VLAN"
ip link add "vxlan$VNI" type vxlan id "$VNI" local "$VTEP" dstport 4789 nolearning
ip link set "vxlan$VNI" master "br$VLAN" addrgenmode none
ip link set eth3 master "br$VLAN"
ip link set vxlan50001 up
ip link set br50001 up
ip link set "vxlan$VNI" up
ip link set "br$VLAN" up
ip link set eth1 up
ip link set eth2 up
ip link set eth3 up

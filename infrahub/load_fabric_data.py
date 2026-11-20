#!/usr/bin/env python3
"""
load_fabric_data.py — Load the DC fabric into Infrahub
======================================================
Loads the leaf-spine fabric (2 spines, 4 leaves) into Infrahub.

Usage:
  infrahubctl schema load infrahub/schema/fabric.yml --branch main
  INFRAHUB_ADDRESS=http://localhost:8000 INFRAHUB_TOKEN=satoken \\
      python infrahub/load_fabric_data.py
"""

import os
import argparse
import logging

from infrahub_sdk import InfrahubClientSync

from load_data import build_node_data, apply_record_to_node

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

INFRAHUB_ADDRESS = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
INFRAHUB_TOKEN   = os.environ.get("INFRAHUB_TOKEN",   "satoken")

VRFS = [
    {"name": "tenant1", "l3_vni": 50001},
]

DEVICES = [
    {"hostname": "spine-01", "role": "spine", "asn": 65000,
     "loopback_ip": "10.1.0.1/32", "clab_container": "clab-dc-fabric-spine-01"},
    {"hostname": "spine-02", "role": "spine", "asn": 65000,
     "loopback_ip": "10.1.0.2/32", "clab_container": "clab-dc-fabric-spine-02"},
    {"hostname": "leaf-01", "role": "leaf", "asn": 65101,
     "loopback_ip": "10.1.1.1/32", "clab_container": "clab-dc-fabric-leaf-01"},
    {"hostname": "leaf-02", "role": "leaf", "asn": 65102,
     "loopback_ip": "10.1.1.2/32", "clab_container": "clab-dc-fabric-leaf-02"},
    {"hostname": "leaf-03", "role": "leaf", "asn": 65103,
     "loopback_ip": "10.1.1.3/32", "clab_container": "clab-dc-fabric-leaf-03"},
    {"hostname": "leaf-04", "role": "leaf", "asn": 65104,
     "loopback_ip": "10.1.1.4/32", "clab_container": "clab-dc-fabric-leaf-04"},
]

# Spines: eth1-4 (one per leaf). Leaves: eth1 → spine-01, eth2 → spine-02.
INTERFACES = [{"device": d["hostname"], "name": f"eth{i}"}
              for d in DEVICES for i in range(1, 5 if d["role"] == "spine" else 3)]


def upsert(client: InfrahubClientSync, kind: str, records: list, key: str) -> dict:
    """Create or update each record (matched on `key`); return key value -> node."""
    nodes = {}
    for rec in records:
        name = rec[key]
        node = client.get(kind=kind, raise_when_missing=False, **{f"{key}__value": name})
        if node:
            if apply_record_to_node(node, rec):
                node.update()
                log.info("  [UPD]  %s — updated", name)
            else:
                log.info("  [SKIP] %s — already up to date", name)
        else:
            node = client.create(kind=kind, data=build_node_data(rec))
            node.save()
            log.info("  [OK]   %s — created", name)
        nodes[name] = node
    return nodes


def load_interfaces(client: InfrahubClientSync, device_map: dict) -> None:
    for iface in INTERFACES:
        device_name = iface["device"]
        iface_name  = iface["name"]

        existing = client.get(
            kind="NetalpsFabricInterface",
            raise_when_missing=False,
            device__hostname__value=device_name,
            name__value=iface_name,
        )
        if existing:
            log.info("  [SKIP] %s/%s — already exists", device_name, iface_name)
            continue

        data = build_node_data({"name": iface_name})
        data["device"] = device_map[device_name]
        node = client.create(kind="NetalpsFabricInterface", data=data)
        node.save()
        log.info("  [OK]   %s/%s — created", device_name, iface_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load DC fabric data into Infrahub")
    parser.add_argument("--address", default=INFRAHUB_ADDRESS,
                        help="Infrahub URL (default: %(default)s)")
    parser.add_argument("--token", default=INFRAHUB_TOKEN,
                        help="Infrahub API token (default: %(default)s)")
    args = parser.parse_args()

    log.info("Connecting to Infrahub: %s", args.address)
    client = InfrahubClientSync(address=args.address, config={"api_token": args.token})

    log.info("=== Loading VRFs ===")
    upsert(client, "NetalpsFabricVrf", VRFS, "name")

    log.info("=== Loading devices ===")
    device_map = upsert(client, "NetalpsFabricDevice", DEVICES, "hostname")

    log.info("=== Loading interfaces ===")
    load_interfaces(client, device_map)

    log.info("=== Loading complete — %d VRF(s), %d devices, %d interfaces ===",
             len(VRFS), len(DEVICES), len(INTERFACES))


if __name__ == "__main__":
    main()

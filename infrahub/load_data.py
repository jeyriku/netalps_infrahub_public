#!/usr/bin/env python3
"""
load_data.py — Chargement du SSOT Infrahub
==========================================
Loads the schema and network data (devices, interfaces) into Infrahub.
To be run ONCE after starting the Infrahub stack.

Loaded content:
  - 4 FRR routers (frr-rtr-01 to frr-rtr-04) with their interfaces and IPs
  - 2 Linux hosts (host-left, host-right)
  - OSPF parameters (area, passive, network type) and BFD per interface

Usage :
  cd /path/to/repo
  source bin/activate
  INFRAHUB_ADDRESS=http://localhost:8000 INFRAHUB_TOKEN=satoken \\
      python netalps_infrahub/infrahub/load_data.py

  # Or with default values (localhost:8000, token=satoken):
  python netalps_infrahub/infrahub/load_data.py

Prerequisites:
  - Infrahub stack started (cd infrahub && docker compose up -d)
  - Schema loaded:
      infrahubctl schema load infrahub/schema/network.yml
    or this script loads it automatically if --load-schema is passed.
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path

import yaml
from infrahub_sdk import InfrahubClientSync
from infrahub_sdk.exceptions import SchemaNotFoundError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────────

INFRAHUB_ADDRESS = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
INFRAHUB_TOKEN   = os.environ.get("INFRAHUB_TOKEN",   "satoken")
SCHEMA_FILE      = Path(__file__).parent / "schema" / "network.yml"
SCHEMA_KIND_DEVICE = "NetalpsNetworkDevice"
SCHEMA_KIND_INTERFACE = "NetalpsInterface"

# ─── Network data ──────────────────────────────────────────────────────────────
#
# Topology: chain of 4 FRR routers
#
#  host-left ─── rtr-01 ─── rtr-02 ─── rtr-03 ─── rtr-04 ─── host-right
#
# Liens P2P (OSPF area 0 + BFD) :
#   rtr-01 eth1 (10.0.12.1/30) ↔ rtr-02 eth1 (10.0.12.2/30)
#   rtr-02 eth2 (10.0.23.1/30) ↔ rtr-03 eth1 (10.0.23.2/30)
#   rtr-03 eth2 (10.0.34.1/30) ↔ rtr-04 eth1 (10.0.34.2/30)
# LAN (OSPF passif) :
#   rtr-01 eth2 (192.168.10.1/24) → host-left
#   rtr-04 eth2 (192.168.40.1/24) → host-right

DEVICES = [
    {
        "hostname": "frr-rtr-01",
        "role": "router",
        "loopback_ip": "10.0.0.1/32",
        "mgmt_ip": "172.20.36.11/24",
        "ospf_router_id": "10.0.0.1",
        "clab_container": "clab-frr-infrahub-demo-frr-rtr-01",
        "description": "Edge router — side host-left",
    },
    {
        "hostname": "frr-rtr-02",
        "role": "router",
        "loopback_ip": "10.0.0.2/32",
        "mgmt_ip": "172.20.36.12/24",
        "ospf_router_id": "10.0.0.2",
        "clab_container": "clab-frr-infrahub-demo-frr-rtr-02",
        "description": "Transit router (rtr-01 ↔ rtr-03)",
    },
    {
        "hostname": "frr-rtr-03",
        "role": "router",
        "loopback_ip": "10.0.0.3/32",
        "mgmt_ip": "172.20.36.13/24",
        "ospf_router_id": "10.0.0.3",
        "clab_container": "clab-frr-infrahub-demo-frr-rtr-03",
        "description": "Transit router (rtr-02 ↔ rtr-04)",
    },
    {
        "hostname": "frr-rtr-04",
        "role": "router",
        "loopback_ip": "10.0.0.4/32",
        "mgmt_ip": "172.20.36.14/24",
        "ospf_router_id": "10.0.0.4",
        "clab_container": "clab-frr-infrahub-demo-frr-rtr-04",
        "description": "Edge router — side host-right",
    },
    {
        "hostname": "host-left",
        "role": "host",
        "mgmt_ip": "172.20.36.21/24",
        "clab_container": "clab-frr-infrahub-demo-host-left",
        "description": "Linux host (192.168.10.10/24)",
    },
    {
        "hostname": "host-right",
        "role": "host",
        "mgmt_ip": "172.20.36.22/24",
        "clab_container": "clab-frr-infrahub-demo-host-right",
        "description": "Linux host (192.168.40.10/24)",
    },
]

INTERFACES = [
    # ── frr-rtr-01 ────────────────────────────────────────────────────────────
    {
        "device": "frr-rtr-01",
        "name": "lo",
        "description": "Loopback",
        "ip_address": "10.0.0.1/32",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
    },
    {
        "device": "frr-rtr-01",
        "name": "eth1",
        "description": "Link to frr-rtr-02 (10.0.12.0/30)",
        "ip_address": "10.0.12.1/30",
        "peer_ip": "10.0.12.2",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
        "ospf_network_type": "point-to-point",
        "bfd_enabled": True,
        "bfd_detect_multiplier": 3,
        "bfd_min_rx": 300,
        "bfd_min_tx": 300,
    },
    {
        "device": "frr-rtr-01",
        "name": "eth2",
        "description": "LAN host-left (192.168.10.0/24)",
        "ip_address": "192.168.10.1/24",
        "ospf_enabled": True,
        "ospf_passive": True,
        "ospf_area": "0",
    },
    # ── frr-rtr-02 ────────────────────────────────────────────────────────────
    {
        "device": "frr-rtr-02",
        "name": "lo",
        "description": "Loopback",
        "ip_address": "10.0.0.2/32",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
    },
    {
        "device": "frr-rtr-02",
        "name": "eth1",
        "description": "Link to frr-rtr-01 (10.0.12.0/30)",
        "ip_address": "10.0.12.2/30",
        "peer_ip": "10.0.12.1",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
        "ospf_network_type": "point-to-point",
        "bfd_enabled": True,
        "bfd_detect_multiplier": 3,
        "bfd_min_rx": 300,
        "bfd_min_tx": 300,
    },
    {
        "device": "frr-rtr-02",
        "name": "eth2",
        "description": "Link to frr-rtr-03 (10.0.23.0/30)",
        "ip_address": "10.0.23.1/30",
        "peer_ip": "10.0.23.2",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
        "ospf_network_type": "point-to-point",
        "bfd_enabled": True,
        "bfd_detect_multiplier": 3,
        "bfd_min_rx": 300,
        "bfd_min_tx": 300,
    },
    # ── frr-rtr-03 ────────────────────────────────────────────────────────────
    {
        "device": "frr-rtr-03",
        "name": "lo",
        "description": "Loopback",
        "ip_address": "10.0.0.3/32",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
    },
    {
        "device": "frr-rtr-03",
        "name": "eth1",
        "description": "Link to frr-rtr-02 (10.0.23.0/30)",
        "ip_address": "10.0.23.2/30",
        "peer_ip": "10.0.23.1",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
        "ospf_network_type": "point-to-point",
        "bfd_enabled": True,
        "bfd_detect_multiplier": 3,
        "bfd_min_rx": 300,
        "bfd_min_tx": 300,
    },
    {
        "device": "frr-rtr-03",
        "name": "eth2",
        "description": "Link to frr-rtr-04 (10.0.34.0/30)",
        "ip_address": "10.0.34.1/30",
        "peer_ip": "10.0.34.2",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
        "ospf_network_type": "point-to-point",
        "bfd_enabled": True,
        "bfd_detect_multiplier": 3,
        "bfd_min_rx": 300,
        "bfd_min_tx": 300,
    },
    # ── frr-rtr-04 ────────────────────────────────────────────────────────────
    {
        "device": "frr-rtr-04",
        "name": "lo",
        "description": "Loopback",
        "ip_address": "10.0.0.4/32",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
    },
    {
        "device": "frr-rtr-04",
        "name": "eth1",
        "description": "Link to frr-rtr-03 (10.0.34.0/30)",
        "ip_address": "10.0.34.2/30",
        "peer_ip": "10.0.34.1",
        "ospf_enabled": True,
        "ospf_passive": False,
        "ospf_area": "0",
        "ospf_network_type": "point-to-point",
        "bfd_enabled": True,
        "bfd_detect_multiplier": 3,
        "bfd_min_rx": 300,
        "bfd_min_tx": 300,
    },
    {
        "device": "frr-rtr-04",
        "name": "eth2",
        "description": "LAN host-right (192.168.40.0/24)",
        "ip_address": "192.168.40.1/24",
        "ospf_enabled": True,
        "ospf_passive": True,
        "ospf_area": "0",
    },
]


# ─── Helpers ───────────────────────────────────────────────────────────────────

def wait_for_infrahub(address: str, retries: int = 30, interval: int = 5) -> None:
    """Wait for Infrahub to be ready to receive requests."""
    import httpx
    url = f"{address}/api/schema/summary"
    log.info("Attente d'Infrahub sur %s ...", url)
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code < 500:
                log.info("Infrahub is ready (attempt %d/%d)", attempt, retries)
                return
        except Exception:
            pass
        log.info("  ... tentative %d/%d — nouvel essai dans %ds", attempt, retries, interval)
        time.sleep(interval)
    raise RuntimeError(f"Infrahub not available after {retries} attempts on {address}")


def schema_is_loaded(client: InfrahubClientSync) -> bool:
    """Return True when both Netalps schema kinds are available."""
    try:
        client.schema.get(kind=SCHEMA_KIND_DEVICE, branch="main")
        client.schema.get(kind=SCHEMA_KIND_INTERFACE, branch="main")
        return True
    except SchemaNotFoundError:
        return False


def load_schema(client: InfrahubClientSync, retries: int = 3, retry_delay: int = 10) -> None:
    """Load schema into Infrahub via SDK with retry and post-check."""
    if schema_is_loaded(client):
        log.info("Schema already present - skipping load.")
        return

    log.info("Loading schema: %s", SCHEMA_FILE)
    with SCHEMA_FILE.open("r", encoding="utf-8") as f:
        schema_payload = yaml.safe_load(f)

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            client.schema.load(schemas=[schema_payload], branch="main")

            # Give Infrahub a short window to index and expose the new schema kinds.
            for _ in range(24):
                if schema_is_loaded(client):
                    log.info("Schema loaded successfully.")
                    return
                time.sleep(5)

            raise RuntimeError("Schema load request sent but schema kinds are still missing.")
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                log.warning(
                    "Schema load attempt %d/%d failed: %s. Retrying in %ss...",
                    attempt,
                    retries,
                    exc,
                    retry_delay,
                )
                time.sleep(retry_delay)
            else:
                break

    log.error("Schema loading error: %s", last_exc)
    raise RuntimeError("Schema loading failed") from last_exc


def build_node_data(record: dict) -> dict:
    """Convertit un dictionnaire plat en format attendu par le SDK Infrahub."""
    data = {}
    for key, value in record.items():
        if value is None:
            continue
        # Boolean/Number/Text fields are wrapped in {"value": ...}
        data[key] = {"value": value}
    return data


def apply_record_to_node(node, record: dict, exclude_keys: set | None = None) -> bool:
    """Apply record values onto an existing node and return True if modified."""
    exclude_keys = exclude_keys or set()
    changed = False

    for key, value in record.items():
        if key in exclude_keys or value is None:
            continue

        try:
            attr = getattr(node, key)
        except AttributeError:
            # Ignore keys that are not part of the current schema.
            continue

        current = attr.value
        if str(current) != str(value):
            attr.value = value
            changed = True

    return changed


# ─── Chargement principal ──────────────────────────────────────────────────────

def load_devices(client: InfrahubClientSync) -> dict:
    """Create or update all devices and return a hostname -> node mapping."""
    device_map = {}
    for dev in DEVICES:
        hostname = dev["hostname"]
        # Check if the device already exists
        existing = client.get(
            kind="NetalpsNetworkDevice",
            raise_when_missing=False,
            hostname__value=hostname,
        )
        if existing:
            node = existing
            if apply_record_to_node(node, dev):
                node.update()
                log.info("  [UPD]  %s — updated", hostname)
            else:
                log.info("  [SKIP] %s — already up to date", hostname)
            device_map[hostname] = node
            continue

        data = build_node_data(dev)
        node = client.create(kind="NetalpsNetworkDevice", data=data)
        node.save()
        log.info("  [OK]   %s — created", hostname)
        device_map[hostname] = node

    return device_map


def load_interfaces(client: InfrahubClientSync, device_map: dict) -> None:
    """Create or update all interfaces and associate them with their device."""
    for iface in INTERFACES:
        device_name = iface["device"]
        iface_name  = iface["name"]

        # Check if the interface already exists
        existing = client.get(
            kind="NetalpsInterface",
            raise_when_missing=False,
            device__hostname__value=device_name,
            name__value=iface_name,
        )
        if existing:
            node = existing
            if apply_record_to_node(node, iface, exclude_keys={"device"}):
                node.update()
                log.info("  [UPD]  %s/%s — updated", device_name, iface_name)
            else:
                log.info("  [SKIP] %s/%s — already up to date", device_name, iface_name)
            continue

        # Prepare data without the "device" key (managed via relation)
        record = {k: v for k, v in iface.items() if k != "device"}
        data = build_node_data(record)

        # Associer au device
        device_node = device_map[device_name]
        data["device"] = device_node

        node = client.create(kind="NetalpsInterface", data=data)
        node.save()
        log.info("  [OK]   %s/%s — created (%s)", device_name, iface_name,
                 iface.get("ip_address", "no ip"))


# ─── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Load network data into Infrahub")
    parser.add_argument("--address", default=INFRAHUB_ADDRESS,
                        help="Infrahub URL (default: %(default)s)")
    parser.add_argument("--token", default=INFRAHUB_TOKEN,
                        help="Infrahub API token (default: %(default)s)")
    parser.add_argument("--load-schema", action="store_true",
                        help="Load the YAML schema before data")
    parser.add_argument("--wait", action="store_true",
                        help="Wait for Infrahub to be ready before continuing")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Client timeout in seconds (default: %(default)s)")
    parser.add_argument("--schema-retries", type=int, default=1,
                        help="Schema load retry count (default: %(default)s)")
    parser.add_argument("--schema-retry-delay", type=int, default=15,
                        help="Delay between schema load retries in seconds (default: %(default)s)")
    args = parser.parse_args()

    if args.wait:
        wait_for_infrahub(args.address)

    log.info("Connecting to Infrahub: %s", args.address)
    client = InfrahubClientSync(
        address=args.address,
        config={"api_token": args.token, "timeout": args.timeout},
    )

    if args.load_schema:
        load_schema(
            client,
            retries=args.schema_retries,
            retry_delay=args.schema_retry_delay,
        )
        log.info("Waiting 5 s after schema loading...")
        time.sleep(5)

    log.info("=== Chargement des devices ===")
    device_map = load_devices(client)

    log.info("=== Chargement des interfaces ===")
    load_interfaces(client, device_map)

    log.info("=== Loading complete — %d devices, %d interfaces ===",
             len(DEVICES), len(INTERFACES))


if __name__ == "__main__":
    main()

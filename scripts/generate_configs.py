#!/usr/bin/env python3
"""
generate_configs.py — Generate FRR configs from Infrahub (SSOT)
=======================================================================
Queries the Infrahub GraphQL API to retrieve network parameters
for each FRR router and generates the corresponding frr.conf files.

Generated files overwrite the static files in configs/.

Usage :
  cd ./netalps_infrahub
  python scripts/generate_configs.py

  # With explicit parameters:
  INFRAHUB_ADDRESS=http://localhost:8000 INFRAHUB_TOKEN=satoken \\
      python scripts/generate_configs.py [--dry-run] [--device frr-rtr-01]

Options :
  --dry-run         Display configs without writing files
  --device HOSTNAME Generate only the config for one router
  --output DIR      Output directory (default: configs/)

Prerequisites:
  - Infrahub started with data loaded (infrahub/load_data.py)
  - infrahub-sdk >= 1.16 (pip install infrahub-sdk)
"""

import os
import sys
import argparse
import logging
import textwrap
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

INFRAHUB_ADDRESS = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
INFRAHUB_TOKEN   = os.environ.get("INFRAHUB_TOKEN",   "satoken")

CONFIGS_DIR = Path(__file__).parent.parent / "configs"

# ─── GraphQL Query ─────────────────────────────────────────────────────────────

QUERY_DEVICES = """
query GetNetworkDevices {
  NetalpsNetworkDevice {
    edges {
      node {
        hostname       { value }
        role           { value }
        loopback_ip    { value }
        ospf_router_id { value }
        mgmt_ip        { value }
        clab_container { value }
        interfaces {
          edges {
            node {
              name              { value }
              description       { value }
              ip_address        { value }
              peer_ip           { value }
              ospf_enabled      { value }
              ospf_passive      { value }
              ospf_area         { value }
              ospf_network_type { value }
              bfd_enabled       { value }
              bfd_detect_multiplier { value }
              bfd_min_rx        { value }
              bfd_min_tx        { value }
            }
          }
        }
      }
    }
  }
}
"""

# ─── FRR config generation ─────────────────────────────────────────────────────

def _ospf_network_from_ip(ip_with_prefix: str) -> str:
    """Converts 10.0.12.1/30 → 10.0.12.0/30 (network address)."""
    import ipaddress
    try:
        net = ipaddress.ip_interface(ip_with_prefix).network
        return str(net)
    except ValueError:
        return ip_with_prefix


def generate_frr_conf(device: dict) -> str:
    """Generates the full content of a frr.conf from Infrahub data."""
    hostname        = device["hostname"]
    loopback_ip     = device.get("loopback_ip", "")
    ospf_router_id  = device.get("ospf_router_id") or (
        loopback_ip.split("/")[0] if loopback_ip else hostname
    )
    interfaces      = device.get("interfaces", [])

    lines = []
    lines += [
        "frr version 9.1",
        "frr defaults traditional",
        f"hostname {hostname}",
        "log syslog informational",
        "no ipv6 forwarding",
        "!",
        "! ── Generated via Infrahub SSOT ─ scripts/generate_configs.py ──",
        "!",
    ]

    # ── Interfaces ──────────────────────────────────────────────────────────
    # Loopback
    if loopback_ip:
        lines += [
            "interface lo",
            f" ip address {loopback_ip}",
            " ip ospf area 0",
            "!",
        ]

    non_lo_ifaces = [i for i in interfaces if i["name"] != "lo"]
    for iface in sorted(non_lo_ifaces, key=lambda x: x["name"]):
        lines.append(f"interface {iface['name']}")
        if iface.get("description"):
            lines.append(f" description {iface['description']}")
        if iface.get("ospf_enabled"):
            area = iface.get("ospf_area") or "0"
            lines.append(f" ip ospf area {area}")
            if iface.get("bfd_enabled"):
                lines.append(" ip ospf bfd")
            net_type = iface.get("ospf_network_type")
            if net_type:
                lines.append(f" ip ospf network {net_type}")
            if iface.get("ospf_passive"):
                lines.append(" ip ospf passive")
        lines.append("!")

    # ── Router OSPF ─────────────────────────────────────────────────────────
    lines += [
        "router ospf",
        f" ospf router-id {ospf_router_id}",
        " passive-interface default",
    ]

    # Disable passive on P2P interfaces
    for iface in non_lo_ifaces:
        if iface.get("ospf_enabled") and not iface.get("ospf_passive"):
            lines.append(f" no passive-interface {iface['name']}")

    # Advertised networks
    if loopback_ip:
        lines.append(f" network {loopback_ip} area 0")
    for iface in non_lo_ifaces:
        if iface.get("ospf_enabled") and iface.get("ip_address"):
            net = _ospf_network_from_ip(iface["ip_address"])
            area = iface.get("ospf_area") or "0"
            lines.append(f" network {net} area {area}")

    lines.append("!")

    # ── BFD ─────────────────────────────────────────────────────────────────
    bfd_ifaces = [i for i in non_lo_ifaces if i.get("bfd_enabled") and i.get("peer_ip")]
    if bfd_ifaces:
        lines.append("bfd")
        for iface in bfd_ifaces:
            peer_ip = iface['peer_ip'].split('/')[0]
            lines.append(f" peer {peer_ip} interface {iface['name']}")
            dm   = iface.get("bfd_detect_multiplier") or 3
            minr = iface.get("bfd_min_rx") or 300
            mint = iface.get("bfd_min_tx") or 300
            lines += [
                f"  detect-multiplier {dm}",
                f"  receive-interval {minr}",
                f"  transmit-interval {mint}",
                " !",
            ]
        lines.append("!")

    lines.append("end")
    return "\n".join(lines) + "\n"


# ─── Infrahub Query ────────────────────────────────────────────────────────────

def fetch_devices(address: str, token: str) -> list:
    """Interroger l'API GraphQL Infrahub et retourner la liste des devices."""
    headers = {
        "X-INFRAHUB-KEY": token,
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(
            f"{address}/graphql",
            json={"query": QUERY_DEVICES},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Erreur HTTP Infrahub : {exc}") from exc

    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(f"Erreur GraphQL : {payload['errors']}")

    edges = payload["data"]["NetalpsNetworkDevice"]["edges"]
    devices = []
    for edge in edges:
        n = edge["node"]
        dev = {
            "hostname":       n["hostname"]["value"],
            "role":           n["role"]["value"] if n.get("role") else "",
            "loopback_ip":    n["loopback_ip"]["value"] if n.get("loopback_ip") else "",
            "ospf_router_id": n["ospf_router_id"]["value"] if n.get("ospf_router_id") else "",
            "mgmt_ip":        n["mgmt_ip"]["value"] if n.get("mgmt_ip") else "",
            "clab_container": n["clab_container"]["value"] if n.get("clab_container") else "",
            "interfaces": [],
        }
        for ie in n["interfaces"]["edges"]:
            ni = ie["node"]
            dev["interfaces"].append({
                "name":              ni["name"]["value"],
                "description":       (ni["description"]["value"]
                                      if ni.get("description") else ""),
                "ip_address":        (ni["ip_address"]["value"]
                                      if ni.get("ip_address") else ""),
                "peer_ip":           (ni["peer_ip"]["value"]
                                      if ni.get("peer_ip") else ""),
                "ospf_enabled":      (ni["ospf_enabled"]["value"]
                                      if ni.get("ospf_enabled") is not None else False),
                "ospf_passive":      (ni["ospf_passive"]["value"]
                                      if ni.get("ospf_passive") is not None else False),
                "ospf_area":         (ni["ospf_area"]["value"]
                                      if ni.get("ospf_area") else "0"),
                "ospf_network_type": (ni["ospf_network_type"]["value"]
                                      if ni.get("ospf_network_type") else ""),
                "bfd_enabled":       (ni["bfd_enabled"]["value"]
                                      if ni.get("bfd_enabled") is not None else False),
                "bfd_detect_multiplier": (ni["bfd_detect_multiplier"]["value"]
                                          if ni.get("bfd_detect_multiplier") else 3),
                "bfd_min_rx":        (ni["bfd_min_rx"]["value"]
                                      if ni.get("bfd_min_rx") else 300),
                "bfd_min_tx":        (ni["bfd_min_tx"]["value"]
                                      if ni.get("bfd_min_tx") else 300),
            })
        devices.append(dev)

    return devices


# ─── Écriture des fichiers ─────────────────────────────────────────────────────

def write_config(device: dict, output_dir: Path, dry_run: bool) -> None:
    hostname = device["hostname"]
    role     = device.get("role", "")

    # Only generate frr.conf for routers
    if role != "router":
        log.info("  [SKIP] %s — role %r (not a router)", hostname, role)
        return

    conf = generate_frr_conf(device)
    dest = output_dir / hostname / "frr.conf"

    if dry_run:
        log.info("  [DRY-RUN] %s :\n%s", dest, textwrap.indent(conf, "    "))
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(conf)
    log.info("  [OK]   %s — %d lignes", dest, conf.count("\n"))


# ─── Entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate FRR configs from Infrahub SSOT"
    )
    parser.add_argument("--address", default=INFRAHUB_ADDRESS,
                        help="Infrahub URL (default: %(default)s)")
    parser.add_argument("--token", default=INFRAHUB_TOKEN,
                        help="Infrahub API token (default: %(default)s)")
    parser.add_argument("--output", default=str(CONFIGS_DIR),
                        help="Output directory (default: %(default)s)")
    parser.add_argument("--device", metavar="HOSTNAME",
                        help="Generate only this device")
    parser.add_argument("--dry-run", action="store_true",
                        help="Display without writing files")
    args = parser.parse_args()

    output_dir = Path(args.output)
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Connecting to Infrahub: %s", args.address)
    devices = fetch_devices(args.address, args.token)

    if args.device:
        devices = [d for d in devices if d["hostname"] == args.device]
        if not devices:
            log.error("Device %r introuvable dans Infrahub.", args.device)
            sys.exit(1)

    log.info("=== Generating FRR configs (%d device(s)) ===", len(devices))
    for device in devices:
        write_config(device, output_dir, dry_run=args.dry_run)

    log.info("=== Configs %s dans %s ===",
             "displayed (dry-run)" if args.dry_run else "written",
             args.output)


if __name__ == "__main__":
    main()

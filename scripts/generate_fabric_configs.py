#!/usr/bin/env python3
"""
generate_fabric_configs.py — Generate DC fabric FRR configs from Infrahub (SSOT)
================================================================================
Queries Infrahub for the leaf-spine fabric and writes
configs-fabric/<node>/frr.conf (eBGP unnumbered + EVPN-VXLAN).

Usage:
  INFRAHUB_ADDRESS=http://localhost:8000 INFRAHUB_TOKEN=satoken \\
      python scripts/generate_fabric_configs.py [--dry-run] [--device leaf-01]
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

CONFIGS_DIR = Path(__file__).parent.parent / "configs-fabric"


QUERY_FABRIC = """
query GetFabric {
  NetalpsFabricDevice {
    edges {
      node {
        hostname    { value }
        role        { value }
        asn         { value }
        loopback_ip { value }
        interfaces {
          edges {
            node {
              name { value }
            }
          }
        }
      }
    }
  }
  NetalpsFabricVrf {
    edges {
      node {
        name   { value }
        l3_vni { value }
      }
    }
  }
}
"""


def generate_frr_conf(device: dict, vrfs: list) -> str:
    """Generates the full content of a frr.conf from Infrahub data."""
    hostname    = device["hostname"]
    asn         = device["asn"]
    loopback_ip = device["loopback_ip"]
    router_id   = loopback_ip.split("/")[0]
    interfaces  = device["interfaces"]
    is_leaf     = device["role"] == "leaf"

    lines = [
        "frr version 9.1",
        "frr defaults datacenter",
        f"hostname {hostname}",
        "log syslog informational",
        "!",
        "! ── Generated via Infrahub SSOT ─ scripts/generate_fabric_configs.py ──",
        "!",
    ]

    if is_leaf:
        for vrf in vrfs:
            lines += [
                f"vrf {vrf['name']}",
                f" vni {vrf['l3_vni']}",
                "exit-vrf",
                "!",
            ]

    lines += [
        "interface lo",
        f" ip address {loopback_ip}",
        "!",
    ]
    for iface in interfaces:
        lines += [
            f"interface {iface}",
            " ipv6 nd ra-interval 3",
            " no ipv6 nd suppress-ra",
            "!",
        ]

    lines += [
        f"router bgp {asn}",
        f" bgp router-id {router_id}",
        " no bgp ebgp-requires-policy",
        " bgp bestpath as-path multipath-relax",
        " neighbor FABRIC peer-group",
        " neighbor FABRIC remote-as external",
    ]
    for iface in interfaces:
        lines.append(f" neighbor {iface} interface peer-group FABRIC")
    lines += [
        " !",
        " address-family ipv4 unicast",
        f"  network {loopback_ip}",
        " exit-address-family",
        " !",
        " address-family l2vpn evpn",
        "  neighbor FABRIC activate",
    ]
    if is_leaf:
        lines.append("  advertise-all-vni")
    lines += [
        " exit-address-family",
        "exit",
        "!",
    ]

    if is_leaf:
        for vrf in vrfs:
            lines += [
                f"router bgp {asn} vrf {vrf['name']}",
                f" bgp router-id {router_id}",
                " !",
                " address-family ipv4 unicast",
                "  redistribute connected",
                " exit-address-family",
                " !",
                " address-family l2vpn evpn",
                "  advertise ipv4 unicast",
                " exit-address-family",
                "exit",
                "!",
            ]

    lines.append("end")
    return "\n".join(lines) + "\n"


def fetch_fabric(address: str, token: str) -> tuple:
    """Query Infrahub and return (devices, vrfs)."""
    headers = {
        "X-INFRAHUB-KEY": token,
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(
            f"{address}/graphql",
            json={"query": QUERY_FABRIC},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Infrahub HTTP error: {exc}") from exc

    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(f"GraphQL error: {payload['errors']}")

    devices = []
    for edge in payload["data"]["NetalpsFabricDevice"]["edges"]:
        n = edge["node"]
        devices.append({
            "hostname":    n["hostname"]["value"],
            "role":        n["role"]["value"],
            "asn":         n["asn"]["value"],
            "loopback_ip": n["loopback_ip"]["value"],
            "interfaces":  sorted(ie["node"]["name"]["value"]
                                  for ie in n["interfaces"]["edges"]),
        })

    vrfs = []
    for edge in payload["data"]["NetalpsFabricVrf"]["edges"]:
        n = edge["node"]
        vrfs.append({
            "name":   n["name"]["value"],
            "l3_vni": n["l3_vni"]["value"],
        })

    return devices, vrfs


def write_config(device: dict, vrfs: list, output_dir: Path, dry_run: bool) -> None:
    conf = generate_frr_conf(device, vrfs)
    dest = output_dir / device["hostname"] / "frr.conf"

    if dry_run:
        log.info("  [DRY-RUN] %s :\n%s", dest, textwrap.indent(conf, "    "))
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(conf)
    log.info("  [OK]   %s — %d lines", dest, conf.count("\n"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate DC fabric FRR configs from Infrahub SSOT"
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

    log.info("Connecting to Infrahub: %s", args.address)
    devices, vrfs = fetch_fabric(args.address, args.token)

    if args.device:
        devices = [d for d in devices if d["hostname"] == args.device]
        if not devices:
            log.error("Device %r not found in Infrahub.", args.device)
            sys.exit(1)

    log.info("=== Generating fabric FRR configs (%d device(s)) ===", len(devices))
    for device in devices:
        write_config(device, vrfs, Path(args.output), dry_run=args.dry_run)


if __name__ == "__main__":
    main()

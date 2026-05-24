#!/usr/bin/env python3
"""
set_ospf_area.py - Read or update ospf_area for a router interface in Infrahub.

Examples:
  python scripts/set_ospf_area.py --device frr-rtr-03 --interface eth1
  python scripts/set_ospf_area.py --device frr-rtr-03 --interface eth1 --area 1
"""

import argparse
import os
import sys

from infrahub_sdk import InfrahubClientSync


def main() -> int:
    parser = argparse.ArgumentParser(description="Read or update ospf_area in Infrahub")
    parser.add_argument("--address", default=os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000"))
    parser.add_argument("--token", default=os.environ.get("INFRAHUB_TOKEN", "satoken"))
    parser.add_argument("--device", required=True, help="Device hostname (ex: frr-rtr-03)")
    parser.add_argument("--interface", required=True, help="Interface name (ex: eth1)")
    parser.add_argument("--area", help="New OSPF area value (ex: 0, 1, 0.0.0.1)")
    args = parser.parse_args()

    client = InfrahubClientSync(address=args.address, config={"api_token": args.token})
    node = client.get(
        kind="NetalpsInterface",
        raise_when_missing=False,
        device__hostname__value=args.device,
        name__value=args.interface,
    )

    if not node:
        print(f"Interface not found: {args.device}/{args.interface}", file=sys.stderr)
        return 1
    current = str(node.ospf_area.value or "")

    if args.area is None:
        print(current)
        return 0

    if current == args.area:
        print(f"{args.device}/{args.interface}: unchanged ({current})")
        return 0

    node.ospf_area.value = args.area
    node.update()
    print(f"{args.device}/{args.interface}: {current} -> {args.area}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

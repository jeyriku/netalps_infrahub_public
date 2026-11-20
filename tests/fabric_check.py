"""
fabric_check.py — DC fabric validation
======================================
Validates the dc-fabric lab (fabric.clab.yml) after deploy.

Usage :
  python tests/fabric_check.py
"""

import os
import sys
import json
import time
import subprocess
from pyats import aetest

INFRAHUB_ADDRESS = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
INFRAHUB_TOKEN   = os.environ.get("INFRAHUB_TOKEN",   "satoken")

LAB = "clab-dc-fabric"
SPINES = ["spine-01", "spine-02"]
LEAVES = ["leaf-01", "leaf-02", "leaf-03", "leaf-04"]
LEAF_LOOPBACKS = {
    "leaf-01": "10.1.1.1/32",
    "leaf-02": "10.1.1.2/32",
    "leaf-03": "10.1.1.3/32",
    "leaf-04": "10.1.1.4/32",
}
LEAF_VNIS = {
    "leaf-01": {"10010", "50001"},
    "leaf-02": {"10020", "50001"},
    "leaf-03": {"10010", "50001"},
    "leaf-04": {"10020", "50001"},
}
HOST_GATEWAYS = {
    "host-01": "192.168.110.1",
    "host-02": "192.168.120.1",
    "host-03": "192.168.110.1",
    "host-04": "192.168.120.1",
}


def docker_exec(node: str, cmd: list, check: bool = True) -> str:
    full_cmd = ["docker", "exec", f"{LAB}-{node}"] + cmd
    if check:
        return subprocess.check_output(full_cmd, stderr=subprocess.STDOUT).decode()
    r = subprocess.run(full_cmd, capture_output=True)
    return (r.stdout + r.stderr).decode()


def vtysh_json(node: str, command: str) -> dict:
    return json.loads(docker_exec(node, ["vtysh", "-c", f"{command} json"]))


def bgp_summary(node: str) -> dict:
    out = vtysh_json(node, "show bgp ipv4 unicast summary")
    return out.get("ipv4Unicast", out)


def established_peers(node: str) -> int:
    peers = bgp_summary(node).get("peers", {})
    return sum(1 for p in peers.values() if p.get("state") == "Established")


def wait_for_bgp(timeout: int = 90, interval: int = 5) -> bool:
    expected = {n: 4 for n in SPINES} | {n: 2 for n in LEAVES}
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if all(established_peers(n) >= c for n, c in expected.items()):
                return True
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            pass
        time.sleep(interval)
    return False


class CommonSetup(aetest.CommonSetup):

    @aetest.subsection
    def wait_bgp_convergence(self):
        if not wait_for_bgp():
            self.failed("eBGP sessions not all Established after 90 s")
        # Each host pings its anycast gateway so its leaf learns the host IP and
        # advertises an EVPN type-2 MAC/IP route. Without it, routed traffic is
        # ECMP'd over the /24 type-5 and can land on a leaf that can't resolve ARP.
        for host, gw in HOST_GATEWAYS.items():
            docker_exec(host, ["ping", "-c", "1", "-W", "1", gw], check=False)
        # Extra wait: EVPN routes and VXLAN FDB entries follow the sessions
        time.sleep(15)


class TestUnderlay(aetest.Testcase):

    @aetest.test
    def spine_sessions(self):
        for spine in SPINES:
            count = established_peers(spine)
            assert count == 4, f"{spine}: expected 4 Established peers, found {count}"

    @aetest.test
    def leaf_sessions(self):
        for leaf in LEAVES:
            count = established_peers(leaf)
            assert count == 2, f"{leaf}: expected 2 Established peers, found {count}"

    @aetest.test
    def leaf_loopbacks_ecmp(self):
        missing = []
        for leaf in LEAVES:
            for other, prefix in LEAF_LOOPBACKS.items():
                if other == leaf:
                    continue
                routes = vtysh_json(leaf, f"show ip route {prefix}").get(prefix, [])
                nexthops = [nh for r in routes for nh in r.get("nexthops", [])
                            if nh.get("active")]
                if len(nexthops) != 2:
                    missing.append(f"{leaf} → {prefix} ({len(nexthops)} nexthop(s))")
        assert not missing, f"Expected 2 ECMP nexthops via spines: {missing}"


class TestOverlay(aetest.Testcase):

    @aetest.test
    def leaf_vnis(self):
        for leaf, expected in LEAF_VNIS.items():
            vnis = set(vtysh_json(leaf, "show evpn vni").keys())
            assert expected <= vnis, f"{leaf}: expected VNIs {expected}, found {vnis}"


class TestConnectivity(aetest.Testcase):

    @aetest.test
    def l2_same_segment(self):
        """host-01 ↔ host-03 (VLAN 10) and host-02 ↔ host-04 (VLAN 20) over VXLAN."""
        for src, dst in (("host-01", "192.168.110.13"), ("host-02", "192.168.120.14")):
            out = docker_exec(src, ["ping", "-c", "3", "-W", "2", dst], check=False)
            assert " 0% " in out, f"Ping {src} → {dst} FAIL\n{out}"

    @aetest.test
    def l3_across_segments(self):
        """host-01 (VLAN 10) ↔ host-04 (VLAN 20) routed through the L3VNI."""
        for src, dst in (("host-01", "192.168.120.14"), ("host-04", "192.168.110.11")):
            out = docker_exec(src, ["ping", "-c", "3", "-W", "2", dst], check=False)
            assert " 0% " in out, f"Ping {src} → {dst} FAIL\n{out}"


class TestSSoTAudit(aetest.Testcase):

    @aetest.test
    def asn_matches_ssot(self):
        import httpx
        query = "query { NetalpsFabricDevice { edges { node { hostname { value } asn { value } } } } }"
        try:
            resp = httpx.post(
                f"{INFRAHUB_ADDRESS}/graphql",
                json={"query": query},
                headers={"X-INFRAHUB-KEY": INFRAHUB_TOKEN},
                timeout=15,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            self.skipped(f"Infrahub unreachable: {exc}")
            return
        edges = resp.json()["data"]["NetalpsFabricDevice"]["edges"]
        ssot = {e["node"]["hostname"]["value"]: e["node"]["asn"]["value"] for e in edges}

        mismatches = []
        for node in SPINES + LEAVES:
            deployed = bgp_summary(node).get("as")
            if deployed != ssot.get(node):
                mismatches.append(f"{node}: Infrahub={ssot.get(node)} deployed={deployed}")
        assert not mismatches, f"SSOT Audit: BGP ASN mismatch: {mismatches}"


if __name__ == "__main__":
    result = aetest.main()
    sys.exit(0 if result.value in ('passed', 'passx') else 1)

"""
post_check.py — Full Functional Validation
===========================================
Step 2 of the pipeline: full network validation AFTER deploy.
Blocks the merge if any single test fails.

Tests :
  1. OSPF neighbors — Full state on all 4 routers
  2. Nombre de voisins OSPF attendus (1 pour edge, 2 pour transit)
  3. Table de routage — routes OSPF loopbacks + LANs distants
  4. BFD peers — Up state on all active P2P links
  5. Ping end-to-end — host-left ↔ host-right (traverse 4 routeurs)
  6. Ping loopback-to-loopback — proves complete OSPF redistribution
  7. SSOT consistency — audit of deployed configs vs Infrahub

Usage :
  python tests/post_check.py --testbed tests/testbed.yml
  pyats run job tests/test_job.py --testbed-file tests/testbed.yml
"""

import os
import subprocess
import argparse
import time
import logging
from pyats import aetest
from pyats.topology import loader

log = logging.getLogger(__name__)

INFRAHUB_ADDRESS = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
INFRAHUB_TOKEN   = os.environ.get("INFRAHUB_TOKEN",   "satoken")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def docker_exec(container: str, cmd: list, check: bool = True) -> str:
    full_cmd = ["docker", "exec", container] + cmd
    if check:
        return subprocess.check_output(full_cmd, stderr=subprocess.STDOUT).decode()
    r = subprocess.run(full_cmd, capture_output=True)
    return (r.stdout + r.stderr).decode()


def wait_for_ospf_full(container: str, timeout: int = 60, interval: int = 5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out = docker_exec(container, ["vtysh", "-c", "show ip ospf neighbor"])
            if "Full" in out:
                return True
        except subprocess.CalledProcessError:
            pass
        time.sleep(interval)
    return False


def count_ospf_full(container: str) -> int:
    out = docker_exec(container, ["vtysh", "-c", "show ip ospf neighbor"])
    return sum(1 for line in out.splitlines() if "Full" in line)


# ─── Common Setup ─────────────────────────────────────────────────────────────

class CommonSetup(aetest.CommonSetup):

    @aetest.subsection
    def load_devices(self, testbed):
        self.parent.parameters.update(
            rtr01=testbed.devices["frr-rtr-01"],
            rtr02=testbed.devices["frr-rtr-02"],
            rtr03=testbed.devices["frr-rtr-03"],
            rtr04=testbed.devices["frr-rtr-04"],
            hleft=testbed.devices["host-left"],
            hright=testbed.devices["host-right"],
        )

    @aetest.subsection
    def wait_ospf_convergence(self, rtr01):
        """Attendre la convergence OSPF (max 60 s) avant de lancer les tests."""
        converged = wait_for_ospf_full(rtr01.custom["container"], timeout=60)
        if not converged:
            self.skipped(
                "OSPF not converged after 60 s — OSPF tests will fail",
                goto=["next_tc"],
            )
        # Extra wait: neighbors Full ≠ routes installed. SPF + RIB update
        # takes a few extra seconds. 15 s is conservative but reliable.
        time.sleep(15)


# ─── Test 1 : OSPF Neighbors Full ──────────────────────────────────────────────

class TestOSPF(aetest.Testcase):
    """Checks that all routers have their OSPF neighbors in Full state."""

    @aetest.test
    def rtr01_ospf_full(self, rtr01):
        out = docker_exec(rtr01.custom["container"],
                          ["vtysh", "-c", "show ip ospf neighbor"])
        assert "Full" in out, (
            f"{rtr01.alias} : aucun voisin OSPF Full\n\n{out}"
        )

    @aetest.test
    def rtr02_ospf_full(self, rtr02):
        out = docker_exec(rtr02.custom["container"],
                          ["vtysh", "-c", "show ip ospf neighbor"])
        assert "Full" in out, (
            f"{rtr02.alias} : aucun voisin OSPF Full\n\n{out}"
        )

    @aetest.test
    def rtr03_ospf_full(self, rtr03):
        out = docker_exec(rtr03.custom["container"],
                          ["vtysh", "-c", "show ip ospf neighbor"])
        assert "Full" in out, (
            f"{rtr03.alias} : aucun voisin OSPF Full\n\n{out}"
        )

    @aetest.test
    def rtr04_ospf_full(self, rtr04):
        out = docker_exec(rtr04.custom["container"],
                          ["vtysh", "-c", "show ip ospf neighbor"])
        assert "Full" in out, (
            f"{rtr04.alias} : aucun voisin OSPF Full\n\n{out}"
        )

    @aetest.test
    def rtr01_ospf_neighbor_count(self, rtr01):
        """rtr-01 est un routeur edge — 1 seul voisin OSPF attendu (rtr-02)."""
        count = count_ospf_full(rtr01.custom["container"])
        assert count >= 1, (
            f"{rtr01.alias} : expected ≥1 Full neighbor, found {count}"
        )

    @aetest.test
    def rtr02_ospf_neighbor_count(self, rtr02):
        """rtr-02 est un routeur transit — 2 voisins OSPF attendus (rtr-01, rtr-03)."""
        count = count_ospf_full(rtr02.custom["container"])
        assert count >= 2, (
            f"{rtr02.alias} : expected ≥2 Full neighbors (transit), found {count}"
        )

    @aetest.test
    def rtr03_ospf_neighbor_count(self, rtr03):
        """rtr-03 est un routeur transit — 2 voisins OSPF attendus (rtr-02, rtr-04)."""
        count = count_ospf_full(rtr03.custom["container"])
        assert count >= 2, (
            f"{rtr03.alias} : expected ≥2 Full neighbors (transit), found {count}"
        )

    @aetest.test
    def rtr04_ospf_neighbor_count(self, rtr04):
        """rtr-04 est un routeur edge — 1 seul voisin OSPF attendu (rtr-03)."""
        count = count_ospf_full(rtr04.custom["container"])
        assert count >= 1, (
            f"{rtr04.alias} : expected ≥1 Full neighbor, found {count}"
        )


# ─── Test 2 : Table de routage OSPF ───────────────────────────────────────────

class TestRouting(aetest.Testcase):
    """Checks for the presence of OSPF routes (remote loopbacks + LANs)."""

    @aetest.test
    def rtr01_learns_rtr04_lan(self, rtr01):
        """rtr-01 doit avoir la route OSPF vers le LAN de rtr-04 (192.168.40.0/24)."""
        out = docker_exec(rtr01.custom["container"],
                          ["vtysh", "-c", "show ip route 192.168.40.0/24"])
        assert "ospf" in out.lower(), (
            f"{rtr01.alias} : route OSPF 192.168.40.0/24 absente\n{out}"
        )

    @aetest.test
    def rtr04_learns_rtr01_lan(self, rtr04):
        """rtr-04 doit avoir la route OSPF vers le LAN de rtr-01 (192.168.10.0/24)."""
        out = docker_exec(rtr04.custom["container"],
                          ["vtysh", "-c", "show ip route 192.168.10.0/24"])
        assert "ospf" in out.lower(), (
            f"{rtr04.alias} : route OSPF 192.168.10.0/24 absente\n{out}"
        )

    @aetest.test
    def rtr01_learns_all_loopbacks(self, rtr01):
        """rtr-01 must know the loopbacks of rtr-02, rtr-03, and rtr-04."""
        for lo in ("10.0.0.2", "10.0.0.3", "10.0.0.4"):
            out = docker_exec(rtr01.custom["container"],
                              ["vtysh", "-c", f"show ip route {lo}/32"])
            assert "ospf" in out.lower(), (
                f"{rtr01.alias} : loopback OSPF {lo}/32 absente\n{out}"
            )

    @aetest.test
    def rtr04_learns_all_loopbacks(self, rtr04):
        """rtr-04 must know the loopbacks of rtr-01, rtr-02, and rtr-03."""
        for lo in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
            out = docker_exec(rtr04.custom["container"],
                              ["vtysh", "-c", f"show ip route {lo}/32"])
            assert "ospf" in out.lower(), (
                f"{rtr04.alias} : loopback OSPF {lo}/32 absente\n{out}"
            )

    @aetest.test
    def rtr02_has_full_routing_table(self, rtr02):
        """rtr-02 (transit) doit apprendre les 2 LANs et les 3 autres loopbacks."""
        missing = []
        for prefix in ("192.168.10.0/24", "192.168.40.0/24",
                        "10.0.0.1/32", "10.0.0.3/32", "10.0.0.4/32"):
            out = docker_exec(rtr02.custom["container"],
                              ["vtysh", "-c", f"show ip route {prefix}"])
            if "ospf" not in out.lower():
                missing.append(prefix)
        assert not missing, (
            f"{rtr02.alias} : routes OSPF manquantes : {missing}"
        )


# ─── Test 3 : BFD ─────────────────────────────────────────────────────────────

class TestBFD(aetest.Testcase):
    """Checks that BFD sessions are in Up state on all P2P links."""

    @aetest.test
    def rtr01_bfd_up(self, rtr01):
        out = docker_exec(rtr01.custom["container"],
                          ["vtysh", "-c", "show bfd peers"])
        assert "up" in out.lower(), (
            f"{rtr01.alias} : aucune session BFD Up\n{out}"
        )

    @aetest.test
    def rtr02_bfd_up(self, rtr02):
        out = docker_exec(rtr02.custom["container"],
                          ["vtysh", "-c", "show bfd peers"])
        assert "up" in out.lower(), (
            f"{rtr02.alias} : aucune session BFD Up\n{out}"
        )
        # rtr-02 a 2 voisins BFD (rtr-01 et rtr-03)
        up_count = sum(1 for line in out.splitlines()
                       if "status" in line.lower() and "up" in line.lower())
        assert up_count >= 2, (
            f"{rtr02.alias} : expected ≥2 BFD Up sessions, found {up_count}\n{out}"
        )

    @aetest.test
    def rtr03_bfd_up(self, rtr03):
        out = docker_exec(rtr03.custom["container"],
                          ["vtysh", "-c", "show bfd peers"])
        assert "up" in out.lower(), (
            f"{rtr03.alias} : aucune session BFD Up\n{out}"
        )

    @aetest.test
    def rtr04_bfd_up(self, rtr04):
        out = docker_exec(rtr04.custom["container"],
                          ["vtysh", "-c", "show bfd peers"])
        assert "up" in out.lower(), (
            f"{rtr04.alias} : aucune session BFD Up\n{out}"
        )


# ─── Test 4 : Ping End-to-End ─────────────────────────────────────────────────

class TestConnectivity(aetest.Testcase):
    """Verification of E2E connectivity traversing the 4 routers."""

    @aetest.test
    def host_left_to_host_right(self, hleft, hright):
        """host-left (192.168.10.10) pinge host-right (192.168.40.10)."""
        target = hright.custom["ip"]
        out = docker_exec(hleft.custom["container"],
                          ["ping", "-c", "3", "-W", "2", target], check=False)
        assert " 0% " in out, (
            f"Ping {hleft.alias} → {hright.alias} ({target}) FAIL\n{out}"
        )

    @aetest.test
    def host_right_to_host_left(self, hleft, hright):
        """host-right (192.168.40.10) pinge host-left (192.168.10.10)."""
        target = hleft.custom["ip"]
        out = docker_exec(hright.custom["container"],
                          ["ping", "-c", "3", "-W", "2", target], check=False)
        assert " 0% " in out, (
            f"Ping {hright.alias} → {hleft.alias} ({target}) FAIL\n{out}"
        )

    @aetest.test
    def rtr01_to_rtr04_loopback(self, rtr01, rtr04):
        """Loopback-to-loopback via OSPF — proves full convergence."""
        target = rtr04.custom["loopback"]
        out = docker_exec(rtr01.custom["container"],
                          ["ping", "-c", "3", "-W", "2", target])
        assert " 0% " in out, (
            f"Ping loopback {rtr01.alias}→{rtr04.alias} ({target}) FAIL\n{out}"
        )

    @aetest.test
    def rtr04_to_rtr01_loopback(self, rtr01, rtr04):
        target = rtr01.custom["loopback"]
        out = docker_exec(rtr04.custom["container"],
                          ["ping", "-c", "3", "-W", "2", target])
        assert " 0% " in out, (
            f"Ping loopback {rtr04.alias}→{rtr01.alias} ({target}) FAIL\n{out}"
        )

    @aetest.test
    def rtr02_to_rtr03_loopback(self, rtr02, rtr03):
        """Transit-to-transit — validates chain symmetry."""
        target = rtr03.custom["loopback"]
        out = docker_exec(rtr02.custom["container"],
                          ["ping", "-c", "3", "-W", "2", target])
        assert " 0% " in out, (
            f"Ping loopback {rtr02.alias}→{rtr03.alias} ({target}) FAIL\n{out}"
        )


# ─── Test 5 : Audit SSOT Infrahub ─────────────────────────────────────────────

class TestSSoTAudit(aetest.Testcase):
    """
    Checks consistency between deployed config and the Infrahub SSOT.
    Compares interface IPs at the kernel level vs Infrahub data.
    """

    @aetest.test
    def rtr01_ip_matches_ssot(self, rtr01):
        """The eth1 IP of rtr-01 matches what Infrahub declares."""
        import httpx
        query = """
        query {
          NetalpsInterface(
            filters: { device__hostname__value: "frr-rtr-01", name__value: "eth1" }
          ) {
            edges { node { ip_address { value } } }
          }
        }
        """
        try:
            resp = httpx.post(
                f"{INFRAHUB_ADDRESS}/graphql",
                json={"query": query},
                headers={"X-INFRAHUB-KEY": INFRAHUB_TOKEN},
                timeout=10,
            )
            data = resp.json()
            edges = data["data"]["NetalpsInterface"]["edges"]
            ssot_ip = edges[0]["node"]["ip_address"]["value"] if edges else None
        except Exception as exc:
            self.skipped(f"Infrahub non accessible pour audit : {exc}")
            return

        if not ssot_ip:
            self.skipped("eth1 IP of frr-rtr-01 not defined in Infrahub")
            return

        deployed_ip = ssot_ip.split("/")[0]
        out = docker_exec(rtr01.custom["container"], ["ip", "addr", "show", "eth1"])
        assert deployed_ip in out, (
            f"SSOT Audit: Infrahub declares {ssot_ip} on {rtr01.alias}/eth1 "
            f"but that is not what is deployed!\n{out}"
        )


# ─── Common Cleanup ────────────────────────────────────────────────────────────

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect(self):
        pass


# ─── Entrypoint standalone ────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("--testbed", required=True)
    args = parser.parse_args()
    testbed = loader.load(args.testbed)
    result = aetest.main(testbed=testbed)
    sys.exit(0 if result.value in ('passed', 'passx') else 1)

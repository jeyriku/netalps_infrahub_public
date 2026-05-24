"""
pre_check.py — Infrastructure Sanity Check
===========================================
Step 1 of the pipeline: checks that the infrastructure is ready BEFORE
functional validation. Runs immediately after `clab deploy`.

Tests :
  1. All containers are Running (4 routers + 2 hosts)
  2. FRR daemons (zebra, ospfd, bfdd) respond via vtysh
  3. Interfaces eth1/eth2 UP avec les IPs attendues
  4. Infrahub API accessible (SSOT disponible)

Usage :
  python tests/pre_check.py --testbed tests/testbed.yml
  pyats run job tests/test_job.py --testbed-file tests/testbed.yml
"""

import os
import subprocess
import argparse
import logging
from pyats import aetest
from pyats.topology import loader

log = logging.getLogger(__name__)

INFRAHUB_ADDRESS = os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000")
INFRAHUB_TOKEN   = os.environ.get("INFRAHUB_TOKEN",   "satoken")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def docker_exec(container: str, cmd: list) -> str:
    full_cmd = ["docker", "exec", container] + cmd
    return subprocess.check_output(full_cmd, stderr=subprocess.STDOUT).decode()


def container_running(container: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


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


# ─── Test 1 : Containers Running ──────────────────────────────────────────────

class TestContainers(aetest.Testcase):
    """Checks that the 6 Containerlab containers are in Running state."""

    @aetest.test
    def rtr01_running(self, rtr01):
        c = rtr01.custom["container"]
        assert container_running(c), f"Container {c!r} n'est pas Running"

    @aetest.test
    def rtr02_running(self, rtr02):
        c = rtr02.custom["container"]
        assert container_running(c), f"Container {c!r} n'est pas Running"

    @aetest.test
    def rtr03_running(self, rtr03):
        c = rtr03.custom["container"]
        assert container_running(c), f"Container {c!r} n'est pas Running"

    @aetest.test
    def rtr04_running(self, rtr04):
        c = rtr04.custom["container"]
        assert container_running(c), f"Container {c!r} n'est pas Running"

    @aetest.test
    def host_left_running(self, hleft):
        c = hleft.custom["container"]
        assert container_running(c), f"Container {c!r} n'est pas Running"

    @aetest.test
    def host_right_running(self, hright):
        c = hright.custom["container"]
        assert container_running(c), f"Container {c!r} n'est pas Running"


# ─── Test 2 : FRR daemons ─────────────────────────────────────────────────────

class TestFRRDaemons(aetest.Testcase):
    """Checks that vtysh responds and that critical daemons are active."""

    @aetest.test
    def vtysh_rtr01(self, rtr01):
        out = docker_exec(rtr01.custom["container"], ["vtysh", "-c", "show version"])
        assert "FRRouting" in out, f"vtysh KO sur {rtr01.custom['container']}\n{out}"

    @aetest.test
    def vtysh_rtr02(self, rtr02):
        out = docker_exec(rtr02.custom["container"], ["vtysh", "-c", "show version"])
        assert "FRRouting" in out, f"vtysh KO sur {rtr02.custom['container']}\n{out}"

    @aetest.test
    def vtysh_rtr03(self, rtr03):
        out = docker_exec(rtr03.custom["container"], ["vtysh", "-c", "show version"])
        assert "FRRouting" in out, f"vtysh KO sur {rtr03.custom['container']}\n{out}"

    @aetest.test
    def vtysh_rtr04(self, rtr04):
        out = docker_exec(rtr04.custom["container"], ["vtysh", "-c", "show version"])
        assert "FRRouting" in out, f"vtysh KO sur {rtr04.custom['container']}\n{out}"

    @aetest.test
    def ospfd_running_rtr01(self, rtr01):
        out = docker_exec(rtr01.custom["container"],
                          ["vtysh", "-c", "show ip ospf"])
        assert "OSPF" in out or "routing" in out.lower(), (
            f"ospfd not responding on {rtr01.alias}\n{out}"
        )

    @aetest.test
    def bfdd_running_rtr01(self, rtr01):
        out = docker_exec(rtr01.custom["container"],
                          ["vtysh", "-c", "show bfd peers"])
        # bfdd may respond with an empty list at first — just check
        # que la commande ne retourne pas d'erreur
        assert "%" not in out[:5], (
            f"bfdd not responding on {rtr01.alias}\n{out}"
        )


# ─── Test 3 : IPs des interfaces ──────────────────────────────────────────────

class TestInterfaces(aetest.Testcase):
    """Checks that the eth1/eth2 interfaces have the correct IPs."""

    @aetest.test
    def rtr01_eth1_ip(self, rtr01):
        expected = rtr01.custom["wan_eth1_ip"]
        out = docker_exec(rtr01.custom["container"], ["ip", "addr", "show", "eth1"])
        assert expected in out, (
            f"{rtr01.alias} eth1 : IP {expected} absente\n{out}"
        )

    @aetest.test
    def rtr02_eth1_ip(self, rtr02):
        expected = rtr02.custom["wan_eth1_ip"]
        out = docker_exec(rtr02.custom["container"], ["ip", "addr", "show", "eth1"])
        assert expected in out, (
            f"{rtr02.alias} eth1 : IP {expected} absente\n{out}"
        )

    @aetest.test
    def rtr02_eth2_ip(self, rtr02):
        expected = rtr02.custom["wan_eth2_ip"]
        out = docker_exec(rtr02.custom["container"], ["ip", "addr", "show", "eth2"])
        assert expected in out, (
            f"{rtr02.alias} eth2 : IP {expected} absente\n{out}"
        )

    @aetest.test
    def rtr03_eth1_ip(self, rtr03):
        expected = rtr03.custom["wan_eth1_ip"]
        out = docker_exec(rtr03.custom["container"], ["ip", "addr", "show", "eth1"])
        assert expected in out, (
            f"{rtr03.alias} eth1 : IP {expected} absente\n{out}"
        )

    @aetest.test
    def rtr03_eth2_ip(self, rtr03):
        expected = rtr03.custom["wan_eth2_ip"]
        out = docker_exec(rtr03.custom["container"], ["ip", "addr", "show", "eth2"])
        assert expected in out, (
            f"{rtr03.alias} eth2 : IP {expected} absente\n{out}"
        )

    @aetest.test
    def rtr04_eth1_ip(self, rtr04):
        expected = rtr04.custom["wan_eth1_ip"]
        out = docker_exec(rtr04.custom["container"], ["ip", "addr", "show", "eth1"])
        assert expected in out, (
            f"{rtr04.alias} eth1 : IP {expected} absente\n{out}"
        )


# ─── Test 4 : Infrahub SSOT accessible ────────────────────────────────────────

class TestInfrahub(aetest.Testcase):
    """Checks that Infrahub is accessible (SSOT available for audit)."""

    @aetest.test
    def infrahub_api_reachable(self):
        import urllib.request
        url = f"{INFRAHUB_ADDRESS}/api/schema/summary"
        try:
            req = urllib.request.Request(
                url,
                headers={"X-INFRAHUB-KEY": INFRAHUB_TOKEN},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
        except Exception as exc:
            self.failed(
                f"Infrahub non accessible sur {url} : {exc}\n"
                "Check: cd infrahub && docker compose ps"
            )
        assert status < 500, (
            f"Infrahub retourne HTTP {status} — stack en erreur ?"
        )

    @aetest.test
    def infrahub_has_devices(self):
        """Verify that Infrahub contains the 4 routers (consistent SSOT)."""
        import httpx
        resp = httpx.post(
            f"{INFRAHUB_ADDRESS}/graphql",
            json={"query": "query { NetalpsNetworkDevice { edges { node { hostname { value } } } } }"},
            headers={"X-INFRAHUB-KEY": INFRAHUB_TOKEN},
            timeout=15,
        )
        if resp.status_code >= 400:
            self.failed(f"GraphQL Infrahub KO : HTTP {resp.status_code}")
        data = resp.json()
        if "errors" in data:
            self.failed(f"Erreur GraphQL : {data['errors']}")
        edges = data["data"]["NetalpsNetworkDevice"]["edges"]
        routers = [e["node"]["hostname"]["value"] for e in edges
                   if "rtr" in e["node"]["hostname"]["value"]]
        assert len(routers) >= 4, (
            f"Infrahub contient {len(routers)} routeur(s), attendu ≥4.\n"
            f"Routers found: {routers}\n"
            "Run: python infrahub/load_data.py"
        )

        @aetest.test
        def infrahub_has_ospf_data(self):
                """Verify OSPF attributes exist in SSOT for all router interfaces."""
                import httpx

                query = """
                query {
                    NetalpsInterface(
                        filters: { device__role__value: "router", ospf_enabled__value: true }
                    ) {
                        edges {
                            node {
                                name { value }
                                ospf_area { value }
                                device { node { hostname { value } } }
                            }
                        }
                    }
                }
                """

                resp = httpx.post(
                        f"{INFRAHUB_ADDRESS}/graphql",
                        json={"query": query},
                        headers={"X-INFRAHUB-KEY": INFRAHUB_TOKEN},
                        timeout=15,
                )
                if resp.status_code >= 400:
                        self.failed(f"GraphQL Infrahub KO : HTTP {resp.status_code}")

                payload = resp.json()
                if "errors" in payload:
                        self.failed(f"Erreur GraphQL : {payload['errors']}")

                edges = payload["data"]["NetalpsInterface"]["edges"]
                # Expected count with current topology: 4 loopbacks + 6 P2P + 2 LAN = 12
                assert len(edges) >= 12, (
                        f"Donnees OSPF insuffisantes dans Infrahub: {len(edges)} interface(s) trouvee(s), "
                        "12 attendues minimum. Relance: python infrahub/load_data.py"
                )

                missing = []
                for edge in edges:
                        node = edge["node"]
                        host = node["device"]["node"]["hostname"]["value"]
                        iface = node["name"]["value"]
                        area = node["ospf_area"]["value"] if node.get("ospf_area") else ""
                        if str(area).strip() == "":
                                missing.append(f"{host}/{iface}")

                assert not missing, (
                        "Attribut ospf_area manquant pour: "
                        + ", ".join(missing)
                        + ". Relance: python infrahub/load_data.py"
                )


# ─── Common Cleanup ────────────────────────────────────────────────────────────

class CommonCleanup(aetest.CommonCleanup):

    @aetest.subsection
    def disconnect(self):
        pass


# ─── Entrypoint standalone ────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--testbed", required=True)
    args = parser.parse_args()
    testbed = loader.load(args.testbed)
    aetest.main(testbed=testbed)

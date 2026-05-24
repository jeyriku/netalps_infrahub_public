# NetAlps Infrahub Demo — Network CI/CD with a Single Source of Truth

> 🌐 **Language / Langue :** [English](README.md) · [Français](README.fr.md)

> **A hands-on lab for Network Engineers learning NetDevOps.**  
> Build a fully automated network: define data once in Infrahub, generate configs, deploy virtual routers, validate with pyATS, and prove that SSOT drift breaks things.

---

## Table of Contents

1. [What You Will Learn](#1-what-you-will-learn)
2. [Core Concepts](#2-core-concepts)
3. [Network Topology](#3-network-topology)
4. [SSOT Data Architecture](#4-ssot-data-architecture)
5. [CI/CD Pipeline Architecture](#5-cicd-pipeline-architecture)
6. [Prerequisites](#6-prerequisites)
7. [Step-by-Step Guide](#7-step-by-step-guide)
8. [Understanding the Tests](#8-understanding-the-tests)
9. [The SSOT Failure Demo](#9-the-ssot-failure-demo)
10. [Understanding the CI/CD Pipeline](#10-understanding-the-cicd-pipeline)
11. [Project File Reference](#11-project-file-reference)
12. [Infrahub Web Interface](#12-infrahub-web-interface)
13. [Troubleshooting](#13-troubleshooting)
14. [Going Further](#14-going-further)

---

## 1. What You Will Learn

This project is a complete, end-to-end demonstration of **Network as Code** and **CI/CD for network infrastructure**. By working through it, you will understand:

| Skill | What the project demonstrates |
|---|---|
| **SSOT design** | How to model a network in Infrahub (schema + data), so that all config derives from one truth |
| **Config generation** | How to query a GraphQL API and render device configurations programmatically |
| **Virtual lab creation** | How Containerlab starts a realistic 4-router FRR topology with a single command |
| **Network state validation** | How pyATS tests check OSPF adjacencies, routing tables, BFD, and end-to-end ping |
| **SSOT consistency audit** | How to compare what is *deployed* to what is *expected* in the SSOT — and fail the pipeline if they diverge |
| **Failure injection** | How mutating the SSOT (changing one value) automatically propagates to the router and breaks the network — proving that the SSOT is the real source of configuration |
| **CI/CD for networking** | How a GitLab pipeline chains all of the above: Infrahub start → data load → config gen → deploy → test → cleanup |

### How this builds on `netalps_demo`

`netalps_demo` introduced Containerlab + FRR + pyATS with 2 routers and static configs.  
This project goes further on three axes:

| Axis | `netalps_demo` | This project |
|---|---|---|
| Scale | 2 routers | 4 routers in a chain |
| Configuration | Static files | Generated from Infrahub SSOT |
| Validation | OSPF + ping | OSPF + routing table + BFD + ping + **SSOT audit** |

---

## 2. Core Concepts

### 2.1 Single Source of Truth (SSOT)

In traditional networking, the same information is duplicated in many places: the device config, the IPAM spreadsheet, the documentation wiki, the monitoring system. When one of those drifts from the others, incidents happen.

A **Single Source of Truth** is a system where network parameters (IP addresses, OSPF areas, BFD timers, device roles…) are stored **once**, and everything else is **derived** from that single record:

```
SSOT (Infrahub)
    │
    ├──► generate_configs.py  →  frr.conf  →  pushed to router
    ├──► post_check.py         →  audit: does router match SSOT?
    └──► documentation, IPAM, monitoring… (future integrations)
```

> **Key insight:** If the router config does not match the SSOT, the pipeline fails. This makes config drift visible and blocking.

### 2.2 Infrahub

[Infrahub](https://github.com/opsmill/infrahub) is an open-source **network source of truth** built by OpsMill. It is:

- **Schema-driven** — you define your own data model (what a "router" or "interface" is), and Infrahub enforces it
- **GraphQL-native** — all data is queried and mutated via a GraphQL API
- **Git-versioned** — Infrahub stores all data changes with full history (branches, diffs)
- **Designed for networks** — with built-in types for IP addresses, prefixes, ASNs, etc.

In this project, Infrahub stores the entire network data model: devices, interfaces, IP addresses, OSPF parameters, and BFD timers. Everything the FRR routers need is in Infrahub.

### 2.3 Containerlab

[Containerlab](https://containerlab.dev/) launches network topologies using Docker containers. A single YAML file describes the topology, and `containerlab deploy` starts all nodes, wires the virtual links, and assigns management IPs — in seconds.

Benefits for a learning environment:
- No physical hardware required
- Reproducible: every deploy is identical
- Destroyed cleanly with `containerlab destroy --cleanup`
- Supports FRR, Nokia SR Linux, Arista cEOS, Cisco XRd, and many others

### 2.4 FRR (Free Range Routing)

[FRR](https://frrouting.org/) is a Linux routing software suite that implements OSPF, BGP, ISIS, BFD, and more. It runs inside Docker containers and is configured via a `frr.conf` file that is **generated from Infrahub** in this project.

### 2.5 pyATS

[pyATS](https://developer.cisco.com/pyats/) (Python Automated Testing System) is Cisco's network test framework. It provides:
- A **testbed** model to describe your devices (used here via `docker exec`)
- **aetest** — a structured test framework with setup/teardown, test sections, and pass/fail tracking
- Clean test reports and exit codes suitable for CI/CD

In this project, pyATS tests validate the network state after every deployment.

### 2.6 OSPF and BFD (Quick Reminder)

**OSPF** (Open Shortest Path First) is a link-state routing protocol. Routers exchange Link State Advertisements (LSAs) to build a complete map of the network, then compute the shortest path tree. Key states: `Init → ExStart → Exchange → Loading → Full`. Only **Full** means the adjacency is fully established and routes are exchanged.

**BFD** (Bidirectional Forwarding Detection) is a fast hello protocol that detects link failures in milliseconds (much faster than OSPF dead timers). It runs between pairs of routers on each P2P link.

---

## 3. Network Topology

### Physical Diagram

```
  host-left                                                         host-right
192.168.10.10/24                                                 192.168.40.10/24
     eth1                                                              eth1
      │                                                                 │
  eth2│ (LAN)                                                   (LAN) eth2│
┌──────────┐                    ┌──────────┐    ┌──────────┐                    ┌──────────┐
│frr-rtr-01│eth1──10.0.12.0/30──│frr-rtr-02│    │frr-rtr-03│──10.0.34.0/30──eth1│frr-rtr-04│
│ 10.0.0.1 │                    │ 10.0.0.2 │    │ 10.0.0.3 │                    │ 10.0.0.4 │
└──────────┘                    └──────────┘    └──────────┘                    └──────────┘
                                      eth2──10.0.23.0/30──eth1
```

End-to-end traffic from `host-left` to `host-right` traverses all 4 routers.

### Device Table

| Device | Loopback | LAN (eth2) | Role | OSPF neighbors |
|---|---|---|---|---|
| frr-rtr-01 | 10.0.0.1/32 | 192.168.10.0/24 | Edge (left) | rtr-02 |
| frr-rtr-02 | 10.0.0.2/32 | — | Transit | rtr-01, rtr-03 |
| frr-rtr-03 | 10.0.0.3/32 | — | Transit | rtr-02, rtr-04 |
| frr-rtr-04 | 10.0.0.4/32 | 192.168.40.0/24 | Edge (right) | rtr-03 |
| host-left  | — | 192.168.10.10/24 | Test host | — |
| host-right | — | 192.168.40.10/24 | Test host | — |

### Why This Topology?

A 4-router chain is the simplest topology that has both **edge** routers (one neighbor) and **transit** routers (two neighbors). This makes it possible to test:
- Route propagation across multiple hops
- The distinction between passive and active OSPF interfaces
- BFD on multiple independent P2P links
- Failure impact when a transit router is misconfigured (area mismatch on rtr-03 breaks both halves)

### Protocols

- **OSPF Area 0** on all P2P links and loopbacks
- **BFD** on all P2P links (fast failure detection, sub-second timers)
- **Passive OSPF** on LAN interfaces (advertised but no neighbor formation with hosts)

---

## 4. SSOT Data Architecture

### Schema

Infrahub uses a **custom schema** (`infrahub/schema/network.yml`) that defines two node types in the `Netalps` namespace:

#### `NetalpsNetworkDevice`

Represents a router or host. Key attributes:

| Attribute | Type | Description |
|---|---|---|
| `hostname` | Text | Unique device identifier |
| `role` | Dropdown | `router` or `host` |
| `loopback_ip` | IPHost | Loopback address (e.g. `10.0.0.1/32`) |
| `ospf_router_id` | Text | OSPF Router-ID |
| `mgmt_ip` | IPHost | Containerlab management IP |
| `clab_container` | Text | Docker container name for `docker exec` |

#### `NetalpsInterface`

Represents a physical or logical interface, linked to a device. Key attributes:

| Attribute | Type | Description |
|---|---|---|
| `name` | Text | Interface name (e.g. `eth1`) |
| `ip_address` | IPHost | Interface IP |
| `peer_ip` | IPHost | Peer IP (for BFD config) |
| `ospf_enabled` | Boolean | Whether OSPF is active on this interface |
| `ospf_passive` | Boolean | Passive mode (advertise but no hellos) |
| `ospf_area` | Text | OSPF area (e.g. `0`) |
| `ospf_network_type` | Text | `point-to-point` for P2P links |
| `bfd_enabled` | Boolean | Whether BFD is enabled |
| `bfd_detect_multiplier` | Integer | BFD detection multiplier |
| `bfd_min_rx` / `bfd_min_tx` | Integer | BFD timers in milliseconds |

### Data Flow: From SSOT to Running Config

```
┌─────────────────────────────────────────────────────────────────┐
│                    Infrahub (SSOT)                              │
│  Schema: NetalpsNetworkDevice + NetalpsInterface                │
│  API: http://localhost:8000  (GraphQL)                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
           ┌─────────────────┼──────────────────────┐
           │                 │                       │
    load_data.py     generate_configs.py        post_check.py
    (PUSH data)      (PULL → render frr.conf)   (PULL → audit)
           │                 │                       │
    Runs once          Runs every CI job        Runs every CI job
    (idempotent)             │                       │
                       configs/                 Compare running
                       frr-rtr-0X/             config vs SSOT
                       frr.conf
                             │
                       containerlab deploy
                             │
                     4 FRR containers
                     (frr.conf bind-mounted)
```

### GraphQL Query Example

`generate_configs.py` queries Infrahub with a single GraphQL request to fetch all devices and their interfaces in one shot:

```graphql
query GetNetworkDevices {
  NetalpsNetworkDevice {
    edges {
      node {
        hostname       { value }
        ospf_router_id { value }
        loopback_ip    { value }
        interfaces {
          edges {
            node {
              name              { value }
              ip_address        { value }
              ospf_enabled      { value }
              ospf_area         { value }
              bfd_enabled       { value }
              bfd_min_tx        { value }
              bfd_min_rx        { value }
            }
          }
        }
      }
    }
  }
}
```

The response is then used to render a `frr.conf` per device. No Jinja2 templates — the config is built in pure Python, which makes the logic easy to inspect and extend.

---

## 5. CI/CD Pipeline Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   infrahub   │───►│  configure   │───►│    deploy    │───►│  pre_check   │
│              │    │              │    │              │    │              │
│infrahub_start│    │generate_cfg  │    │deploy_lab    │    │pre_check.py  │
│load_schema   │    │              │    │              │    │              │
│load_data     │    │              │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────┬───────┘
                                                                    │
                    ┌──────────────────────────────────────────────►│
                    │                                               │
             ┌──────┴──────┐    ┌───────────────────────────────────┘
             │   cleanup   │◄───│           post_check              │
             │             │    │                                   │
             │cleanup_lab  │    │  post_check.py                    │
             │(always runs)│    │  (OSPF + routes + BFD + ping +   │
             └─────────────┘    │   SSOT audit)                     │
                                └──────────────────────────────────┘
```

The `cleanup` stage runs **always** (even on failure) to destroy the lab and stop Infrahub, ensuring the runner is never left in a dirty state.

### When Does the Pipeline Trigger?

Defined in `.gitlab-ci.yml` workflow rules:
- On **merge request** events
- On push to **`main`**
- On push to branches matching **`feature/*`** or **`infrahub/*`**

---

## 6. Prerequisites

### Knowledge

This project is suitable if you are familiar with:
- Basic Linux command line (shell, Docker, environment variables)
- IP networking fundamentals (routing, subnets)
- OSPF basics (what an adjacency is, what a routing table contains)
- Python basics (to read and modify the test scripts)

No prior pyATS, Infrahub, or Containerlab experience required — the project is self-explanatory.

### Tools

| Tool | Version | Install |
|---|---|---|
| Docker | ≥ 24 | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Containerlab | ≥ 0.55 | [containerlab.dev/install](https://containerlab.dev/install/) |
| Python | ≥ 3.10 | system or pyenv |

### Python Dependencies

Install in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pyats infrahub-sdk httpx pyyaml
```

### Docker Images

```bash
docker pull frrouting/frr:latest       # FRR router
docker pull nicolaka/netshoot:latest   # Test hosts
```

---

## 7. Step-by-Step Guide

### Step 0 — Start Infrahub (the SSOT)

Infrahub runs as a Docker Compose stack (Neo4j + RabbitMQ + Redis + the Infrahub server itself).

```bash
# Copy the example env file (adjust passwords if needed for production)
cp infrahub/.env.example infrahub/.env

cd infrahub
docker compose up -d
```

Then wait for it to be fully ready (~2 minutes on first start):

```bash
bash scripts/wait_for_infrahub.sh http://localhost:8000
```

> **Why wait?** Infrahub depends on Neo4j and RabbitMQ being ready before it accepts API calls. The wait script polls `/api/health` until it gets a `200 OK`.

### Step 1 — Load the Schema (define your data model)

Before pushing data, Infrahub needs to know what types of objects exist. The schema file defines the `NetalpsNetworkDevice` and `NetalpsInterface` node types.

```bash
source .venv/bin/activate

INFRAHUB_ADDRESS=http://localhost:8000 \
INFRAHUB_API_TOKEN=satoken \
    infrahubctl schema load infrahub/schema/network.yml --branch main
```

> **Why a custom schema?** Infrahub is generic — it does not know what a "router" is until you tell it. By defining the schema, you make the data model explicit: every field has a type, a validation rule, and a human-readable label. You can then extend it (add BGP ASN, vendor, serial number…) without changing the pipeline scripts.

You can verify the schema was loaded in the web UI at `http://localhost:8000` under **Schema**.

### Step 2 — Load Network Data (populate the SSOT)

```bash
INFRAHUB_ADDRESS=http://localhost:8000 \
INFRAHUB_TOKEN=satoken \
    python infrahub/load_data.py
```

This script creates all 4 routers, 2 hosts, and all their interfaces with:
- IP addresses
- OSPF settings (area, passive mode, network type)
- BFD timers

The script is **idempotent** — running it a second time updates existing objects rather than creating duplicates.

> **Why load data programmatically?** In a real environment, this data would come from an existing IPAM or CMDB via an import script. Here it is hardcoded for clarity, but the pattern is the same: data flows **into** the SSOT from an authoritative source, not the other way around.

### Step 3 — Generate FRR Configs from Infrahub (SSOT → Device Config)

```bash
INFRAHUB_ADDRESS=http://localhost:8000 \
INFRAHUB_TOKEN=satoken \
    python scripts/generate_configs.py
```

This queries the Infrahub GraphQL API and writes a `frr.conf` for each of the 4 routers into `configs/frr-rtr-0X/`. 

To preview without writing files:

```bash
python scripts/generate_configs.py --dry-run
```

To regenerate only one router:

```bash
python scripts/generate_configs.py --device frr-rtr-03
```

> **Why generate configs?** The alternative is to manually maintain 4 separate `frr.conf` files and keep them in sync with each other and with the documentation. Config generation removes human error: if the OSPF area in Infrahub is `0`, the generated config will have `ip ospf area 0`. There is no way for the config to say area `1` while the SSOT says `0` — unless someone manually edits the file (which the pipeline would catch).

After generation, you can inspect what changed:

```bash
git diff configs/
```

### Step 4 — Deploy the Lab

```bash
containerlab deploy -t topology.clab.yml
```

Containerlab reads `topology.clab.yml`, creates Docker containers for each node, creates virtual links between them, and assigns management IPs. The `frr.conf` files from `configs/` are bind-mounted into each FRR container at startup.

> **Why Containerlab?** You get a realistic multi-router topology without physical hardware. Each FRR container runs a real routing stack — OSPF adjacencies, SPF computation, and BFD sessions are the same as on a physical router.

### Step 5 — Wait for OSPF Convergence

OSPF convergence takes a few seconds after the containers start. pyATS handles this wait automatically (see [Understanding the Tests](#8-understanding-the-tests)), but if you are running manually, allow ~30 seconds before inspecting the routing table.

### Step 6 — Run pyATS Tests

```bash
# Sanity check (containers up, daemons running, Infrahub reachable)
python tests/pre_check.py --testbed tests/testbed.yml

# Full validation (OSPF + routing + BFD + ping + SSOT audit)
python tests/post_check.py --testbed tests/testbed.yml
```

Or run both as a single pyATS job:

```bash
pyats run job tests/test_job.py --testbed-file tests/testbed.yml
```

### Step 7 — Cleanup

```bash
containerlab destroy -t topology.clab.yml --cleanup
cd infrahub && docker compose down -v
```

The `--cleanup` flag removes the `clab-frr-infrahub-demo/` directory created by Containerlab.  
The `-v` flag removes Docker volumes (Neo4j data) so the next run starts fresh.

---

## 8. Understanding the Tests

### `pre_check.py` — Sanity

Runs **before** any network validation. It checks:

| Test | What it verifies | Why it matters |
|---|---|---|
| Containers running | All 6 containers are `Up` in `docker ps` | Fail fast if the lab did not start properly |
| FRR daemons | `ospfd` and `bfdd` processes are alive inside each router | A container can be running without its routing daemons |
| Infrahub reachable | HTTP `GET /api/health` returns 200 | Needed by `post_check.py` for the SSOT audit |

### `post_check.py` — Full Functional Validation

Runs **after** deployment. It has 7 test cases:

#### TestOSPF — OSPF Neighbors

```
frr-rtr-01: vtysh -c "show ip ospf neighbor"  →  must contain "Full"
```

Checks that **every router** has at least one OSPF neighbor in `Full` state.  
Also validates the **neighbor count**: edge routers must have 1, transit routers must have 2.

> If rtr-03 has an OSPF area mismatch (area 1 instead of 0), its neighbors with rtr-02 and rtr-04 will be stuck in `ExStart/Exchange` and never reach `Full`. This test catches that.

#### TestRouting — Routing Table

```
frr-rtr-01: vtysh -c "show ip route 192.168.40.0/24"  →  must contain "ospf"
```

Checks that edge routers have OSPF routes to:
- The remote LAN (e.g. rtr-01 learns `192.168.40.0/24`)
- All remote loopbacks (e.g. rtr-01 learns `10.0.0.2/32`, `10.0.0.3/32`, `10.0.0.4/32`)

> This test verifies route propagation across all 4 routers. A failure here indicates either an OSPF adjacency issue or a missing `network` statement in the OSPF config.

#### TestBFD — BFD Peers

```
frr-rtr-01: vtysh -c "show bfd peers"  →  must contain "Status: Up"
```

Checks that all BFD peers are in `Up` state on every router. BFD requires both sides to be configured with matching timers.

#### TestConnectivity — End-to-End Ping

```
docker exec clab-...-host-left ping -c 3 -W 2 192.168.40.10
docker exec clab-...-host-right ping -c 3 -W 2 192.168.10.10
```

Ping from `host-left` to `host-right` and vice versa. This traverses all 4 routers and confirms the complete data plane is working.

Also tests loopback-to-loopback pings between all router pairs, which validates that loopback routes are correctly advertised and installed.

#### TestSSoT — SSOT Consistency Audit

This is the most distinctive test in this project.

```python
# Query Infrahub: what OSPF area should each interface have?
# Query FRR: what OSPF area does the router actually have?
# Compare: if they differ → FAIL
```

`post_check.py` queries the Infrahub GraphQL API to get the **expected** OSPF area per interface, then runs `vtysh -c "show ip ospf interface"` on each container to get the **actual** OSPF area. If they differ, the test fails with a clear message:

```
FAILED: frr-rtr-03/eth1 — SSOT says area=0, router has area=1
```

> **This is the key test.** It makes the pipeline fail whenever the running network diverges from the SSOT — whether from a manual change, a config generation bug, or a failed deployment.

### CommonSetup — OSPF Convergence Wait

Before running any test, `post_check.py` waits for OSPF to converge:

```python
def wait_ospf_convergence(self, rtr01):
    converged = wait_for_ospf_full(rtr01.custom["container"], timeout=60)
    if not converged:
        self.skipped("OSPF not converged after 60 s", goto=["next_tc"])
    time.sleep(15)  # Extra wait: neighbors Full ≠ routes installed yet
```

There are two phases to OSPF convergence:
1. **Neighbor Full state** — adjacency established, LSA exchange complete
2. **RIB installation** — SPF computed, routes installed in the kernel

The 15-second extra sleep is necessary because `Full` in the neighbor table appears ~2–5 seconds before the routes are in the kernel routing table. Removing it causes intermittent `TestRouting` failures.

---

## 9. The SSOT Failure Demo

### What It Demonstrates

The failure demo answers the question: **"What happens if the SSOT has wrong data?"**

It shows the complete lifecycle:

```
[Correct SSOT] → generate → deploy → test PASS
      ↓
[Mutate SSOT: area 0 → area 1 on rtr-03/eth1]
      ↓
[Regenerate config] → reload router → OSPF breaks
      ↓
[post_check FAILS: neighbor count, routing, ping, SSoT audit]
      ↓
[Restore SSOT: area 1 → area 0]
      ↓
[Regenerate config] → reload router → OSPF recovers
      ↓
[post_check PASSES]
```

### Running the Demo

```bash
source .venv/bin/activate
INFRAHUB_TOKEN=satoken bash scripts/failure_demo.sh
```

### Step-by-Step Walkthrough

The demo runs **8 stages**, each logged with a clear header:

| Stage | Action | Expected |
|---|---|---|
| 1/8 | Verify Infrahub availability | Infrahub responds on port 8000 |
| 2/8 | Load SSOT data + generate configs | `configs/frr-rtr-0X/frr.conf` written from Infrahub |
| 3/8 | Deploy lab + run baseline pre/post checks | **PASS** — network is correct |
| 4/8 | Read current OSPF area from Infrahub | Saves `original_area=0` for rollback |
| 5/8 | **Inject failure**: set `frr-rtr-03/eth1 ospf_area → 1` in Infrahub | SSOT now says area 1 |
| 5/8 | Regenerate frr-rtr-03 config + reload (`vtysh -b`) | Router now in area 1 |
| 6/8 | Run post_check | **FAIL** — OSPF adjacency lost, routing broken, SSOT audit mismatch |
| 7/8 | **Restore**: set `frr-rtr-03/eth1 ospf_area → 0` in Infrahub | SSOT back to area 0 |
| 7/8 | Regenerate config + reload | Router back to area 0 |
| 8/8 | Run post_check | **PASS** — full recovery |

### Why Area Mismatch Breaks OSPF

OSPF routers only form adjacencies with neighbors in the **same area**. If `rtr-03/eth1` is in area 1 but `rtr-02/eth2` is in area 0, their Hello packets will be rejected:

```
rtr-02 (area 0) ←── eth2──eth1 ──→ rtr-03 (area 1)
                         ✗ REJECTED: area mismatch
```

The consequence:
- rtr-02 loses its neighbor with rtr-03 → no routes beyond rtr-02
- rtr-04 loses its only neighbor → completely isolated
- Ping from host-left to host-right fails (no route)

### Trap: The SSOT Is Not the Only Layer

The demo shows that even with the SSOT restored, the router must also be reloaded. The failure demo does this:

```bash
# 1. Update SSOT
python scripts/set_ospf_area.py --device frr-rtr-03 --interface eth1 --area 0

# 2. Regenerate frr.conf from SSOT
python scripts/generate_configs.py

# 3. Remove stale OSPF config from running config (critical!)
docker exec clab-...-frr-rtr-03 vtysh \
    -c "configure terminal" \
    -c "interface eth1" \
    -c "no ip ospf area" \
    -c "end"

# 4. Reload from file (applies the regenerated frr.conf)
docker exec clab-...-frr-rtr-03 vtysh -b
```

Step 3 (`no ip ospf area`) is necessary because `vtysh -b` merges the file config with the running config — it does not replace it. Without explicitly removing the old area first, the stale `ip ospf area 1` would remain.

---

## 10. Understanding the CI/CD Pipeline

### Stage Breakdown

#### Stage `infrahub` — Start the SSOT

Three parallel-ish jobs:

| Job | Does |
|---|---|
| `infrahub_start` | `docker compose up -d` + health wait |
| `load_schema` | `infrahubctl schema load` (needs `infrahub_start`) |
| `load_data` | `python infrahub/load_data.py` (needs `load_schema`) |

These three jobs have `needs:` dependencies to ensure strict ordering.

#### Stage `configure` — Generate Device Configs

| Job | Does |
|---|---|
| `generate_configs` | Queries Infrahub GraphQL → writes `configs/frr-rtr-0X/frr.conf` |

After this job, a `git diff configs/` shows exactly what changed vs the committed configs.

> In a GitLab **merge request** workflow, you can configure this job to post the diff as a comment on the MR, giving reviewers visibility into exactly which config lines changed before merging.

#### Stage `deploy`

| Job | Does |
|---|---|
| `deploy_lab` | `containerlab deploy -t topology.clab.yml --reconfigure` |

`--reconfigure` forces a full recreate even if the topology is already running (idempotent).

#### Stage `pre_check`

| Job | Does |
|---|---|
| `pre_check` | Runs `tests/pre_check.py` — containers up, daemons alive, Infrahub reachable |

This is a fast sanity gate. If pre_check fails, there is no point running the 60-second OSPF convergence wait in post_check.

#### Stage `post_check`

| Job | Does |
|---|---|
| `post_check` | Runs `tests/post_check.py` — OSPF, routing, BFD, ping, SSOT audit |

This is the **quality gate**. If any test fails, the pipeline is marked failed and the merge is blocked (if you configure branch protection rules in GitLab).

#### Stage `cleanup`

| Job | Does |
|---|---|
| `cleanup_lab` | `containerlab destroy --cleanup` + `docker compose down -v` |

Uses `when: always` so it runs even if pre_check or post_check failed, preventing resource leaks on the CI runner.

### CI Variables

Defined in **GitLab → Settings → CI/CD → Variables** (or in the pipeline for demos):

| Variable | Default | Description |
|---|---|---|
| `INFRAHUB_TOKEN` | `satoken` | Infrahub API token |
| `INFRAHUB_ADDRESS` | `http://localhost:8000` | Infrahub URL (if not localhost) |

> In production, replace `satoken` with a secrets-manager-backed token and mark the variable as **masked** in GitLab.

### Runner Requirements

The pipeline requires a **shell executor** runner (not Docker-in-Docker) with:
- Docker CLI access (to run `docker exec` against the Containerlab containers)
- Containerlab installed
- The Python venv at `.venv/bin/activate`
- Tag: `frr-infrahub`

---

## 11. Project File Reference

```
netalps_infrahub_public/
│
├── topology.clab.yml              # Containerlab topology — 4 FRR routers + 2 hosts
│                                  # Defines nodes, links, image, bind mounts
│
├── .gitlab-ci.yml                 # Full 6-stage CI/CD pipeline
│
├── infrahub/
│   ├── .env.example               # Environment variables template (copy to .env)
│   ├── docker-compose.yml         # Infrahub stack: Neo4j + RabbitMQ + Redis + Infrahub
│   ├── schema/
│   │   └── network.yml            # Custom schema: NetalpsNetworkDevice + NetalpsInterface
│   └── load_data.py               # SSOT bootstrap: pushes all devices + interfaces into Infrahub
│
├── configs/                       # FRR configs (generated — do not edit manually)
│   └── frr-rtr-0X/
│       ├── daemons                # Enables ospfd, bfdd
│       ├── frr.conf               # Main routing config (OSPF, BFD, interfaces)
│       └── vtysh.conf             # vtysh hostname
│
├── scripts/
│   ├── generate_configs.py        # Queries Infrahub GraphQL → renders frr.conf per router
│   ├── set_ospf_area.py           # Read or write ospf_area in Infrahub (used by failure_demo)
│   ├── failure_demo.sh            # End-to-end SSOT failure/recovery scenario (8 steps)
│   └── wait_for_infrahub.sh       # Polls /api/health until Infrahub is ready
│
└── tests/
    ├── testbed.yml                # pyATS testbed: 6 devices with docker exec connection
    ├── pre_check.py               # Stage 1: containers, daemons, Infrahub reachability
    ├── post_check.py              # Stage 2: OSPF, routing, BFD, ping, SSOT audit
    └── test_job.py                # pyATS job runner (chains pre + post check)
```

---

## 12. Infrahub Web Interface

Access the Infrahub UI at **`http://localhost:8000`**

| Field | Value |
|---|---|
| Login | `admin` |
| Password | `infrahub` |
| API Token | `satoken` |

### What to Explore

- **Objects → NetalpsNetworkDevice** — see the 4 routers and 2 hosts
- **Objects → NetalpsInterface** — see all interfaces with their OSPF/BFD attributes
- **Schema** — see the data model with field types and constraints
- **GraphQL Explorer** (`/graphql`) — run the query from `generate_configs.py` directly in the browser

### Manually Changing a Value

Try changing `ospf_area` on `frr-rtr-03/eth1` from `0` to `1` via the UI, then run:

```bash
python scripts/generate_configs.py --device frr-rtr-03
git diff configs/frr-rtr-03/frr.conf
```

You will see exactly one line changed in the generated config — confirming that the SSOT is the true source and the config file is just a derived artifact.

---

## 13. Troubleshooting

### Infrahub does not start

```bash
cd infrahub && docker compose logs --tail=50
```

Common causes:
- Neo4j taking too long on first start → wait longer, re-run `wait_for_infrahub.sh`
- Port 8000 already in use → change `INFRAHUB_PORT` in `.env`

### `infrahubctl schema load` fails with `SchemaNotFound`

Infrahub is not fully ready yet. Re-run `wait_for_infrahub.sh` and retry.

### FRR containers start but OSPF does not converge

```bash
# Check FRR daemon logs
docker exec clab-frr-infrahub-demo-frr-rtr-01 vtysh -c "show ip ospf neighbor"

# Check if ospfd is running
docker exec clab-frr-infrahub-demo-frr-rtr-01 ps aux | grep ospf

# Check the loaded frr.conf
docker exec clab-frr-infrahub-demo-frr-rtr-01 vtysh -c "show running-config"
```

Common cause: config was not regenerated after a schema/data change. Run `generate_configs.py` again, then `containerlab deploy --reconfigure`.

### `post_check.py` fails on TestRouting but OSPF neighbors are Full

This is a timing issue. OSPF neighbors reach `Full` state 2–5 seconds before the kernel routing table is updated. The `time.sleep(15)` in `CommonSetup.wait_ospf_convergence` handles this in the test — but if you are running manually and do not wait, you may see it.

Solution: wait ~20 seconds after `Full` appears before running the test.

### SSOT audit fails after manual config edit

If you manually edit a `frr.conf` in `configs/` and redeploy, the SSOT audit will fail because the SSOT still says the old value. Always regenerate configs from Infrahub — never edit `frr.conf` directly.

---

## 14. Going Further

This project is a starting point. Here are directions for extending it:

### Add a BGP Peering

Add a `bgp_asn` attribute to `NetalpsNetworkDevice` in the schema, populate it in `load_data.py`, and extend `generate_configs.py` to render `router bgp <asn>` blocks. Then add a `TestBGP` test case in `post_check.py`.

### Multi-Area OSPF

Add an `ospf_area` attribute at the device level (for area border routers), extend the schema, and modify `generate_configs.py` to generate the correct ABR config. The SSOT audit in `post_check.py` would then validate multi-area deployments.

### Infrahub Transforms

Instead of the custom Python `generate_configs.py`, use [Infrahub Transforms](https://docs.infrahub.app/guides/transform/) — a built-in Infrahub feature that renders Jinja2 templates server-side from GraphQL queries. This makes config generation accessible via the API without any client-side script.

### GitLab MR Config Diff

Extend `generate_configs.py` to output a structured diff, and add a `.gitlab-ci.yml` job that posts it as a merge request comment using the GitLab API. Reviewers will see exactly which config lines the MR changes.

### Extend to More Vendors

Replace or add Nokia SR Linux nodes (supported by Containerlab out of the box). Add a `vendor` dropdown to `NetalpsNetworkDevice` and make `generate_configs.py` dispatch to vendor-specific renderers.

---

## License

MIT — free to use, modify, and share.

## Related Projects

- [netalps_demo](https://github.com/jeyriku/netalps_demo_public) — the simpler 2-router version that this project extends
- [Infrahub](https://github.com/opsmill/infrahub) — the open-source SSOT used here
- [Containerlab](https://github.com/srl-labs/containerlab) — the virtual lab engine
- [pyATS](https://developer.cisco.com/pyats/) — Cisco's network test framework

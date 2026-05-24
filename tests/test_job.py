"""
test_job.py — PyATS Job File
=============================
Orchestrates the two testscripts in sequence:
  1. pre_check  — sanity infrastructure + Infrahub SSOT accessible
  2. post_check — OSPF/routing/BFD/ping E2E + audit SSOT

Usage:
  pyats run job tests/test_job.py --testbed-file tests/testbed.yml
"""

import os
from pyats.easypy import run

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def main(runtime):
    # ── 1. Pre-check : infrastructure + SSOT ──────────────────────────────────
    run(
        testscript=os.path.join(TESTS_DIR, "pre_check.py"),
        runtime=runtime,
        taskid="pre_check",
        testbed=runtime.testbed,
    )

    # ── 2. Post-check : OSPF + routing + BFD + E2E + audit Infrahub ──────────
    run(
        testscript=os.path.join(TESTS_DIR, "post_check.py"),
        runtime=runtime,
        taskid="post_check",
        testbed=runtime.testbed,
    )

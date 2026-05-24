#!/usr/bin/env bash
# failure_demo.sh - SSOT-driven failure scenario using Infrahub OSPF data.

set -euo pipefail

DEMO_DIR="${DEMO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
TOPO="${TOPO:-$DEMO_DIR/topology.clab.yml}"
TESTBED="${TESTBED:-$DEMO_DIR/tests/testbed.yml}"
INFRAHUB_ADDRESS="${INFRAHUB_ADDRESS:-http://localhost:8000}"
INFRAHUB_TOKEN="${INFRAHUB_TOKEN:-satoken}"
PYTHON_BIN="${PYTHON_BIN:-python}"

TARGET_DEVICE="${TARGET_DEVICE:-frr-rtr-03}"
TARGET_INTERFACE="${TARGET_INTERFACE:-eth1}"
BROKEN_AREA="${BROKEN_AREA:-1}"
TARGET_CONTAINER="clab-frr-infrahub-demo-${TARGET_DEVICE}"

ORIGINAL_AREA=""
AREA_MUTATED=0
RESTORED=0
CLEANED=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
step() { echo -e "\n${CYAN}== $* ==${NC}"; }
ok() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }

restore_ssot_if_needed() {
  if [[ "$AREA_MUTATED" -eq 1 && "$RESTORED" -eq 0 && -n "$ORIGINAL_AREA" ]]; then
    warn "Restoring Infrahub OSPF area (${TARGET_DEVICE}/${TARGET_INTERFACE} -> ${ORIGINAL_AREA})"
    INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
      "$PYTHON_BIN" "$DEMO_DIR/scripts/set_ospf_area.py" \
      --device "$TARGET_DEVICE" --interface "$TARGET_INTERFACE" --area "$ORIGINAL_AREA" || true

    INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
      "$PYTHON_BIN" "$DEMO_DIR/scripts/generate_configs.py" || true

    docker exec "$TARGET_CONTAINER" vtysh \
      -c "configure terminal" -c "interface $TARGET_INTERFACE" \
      -c "no ip ospf area" -c "end" >/dev/null 2>&1 || true
    docker exec "$TARGET_CONTAINER" vtysh -b >/dev/null 2>&1 || true
  fi
}

cleanup_lab_if_needed() {
  if [[ "$CLEANED" -eq 0 ]]; then
    containerlab destroy -t "$TOPO" --cleanup >/dev/null 2>&1 || true
    CLEANED=1
  fi
}

on_exit() {
  restore_ssot_if_needed
  cleanup_lab_if_needed
}
trap on_exit EXIT INT TERM

step "1/8 - Verify Infrahub availability"
bash "$DEMO_DIR/scripts/wait_for_infrahub.sh" "$INFRAHUB_ADDRESS" 20 5
ok "Infrahub reachable"

step "2/8 - Ensure SSOT data is loaded and configs are generated"
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/infrahub/load_data.py" --load-schema --timeout 3600 --schema-retries 1
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/scripts/generate_configs.py"
ok "SSOT data and configs ready"

step "3/8 - Deploy lab and run baseline checks"
containerlab deploy -t "$TOPO" --reconfigure
sleep 30
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/tests/pre_check.py" --testbed "$TESTBED"
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/tests/post_check.py" --testbed "$TESTBED"
ok "Baseline checks passed"

step "4/8 - Backup current OSPF area from Infrahub"
ORIGINAL_AREA="$(INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/scripts/set_ospf_area.py" \
  --device "$TARGET_DEVICE" --interface "$TARGET_INTERFACE")"
if [[ -z "$ORIGINAL_AREA" ]]; then
  fail "Could not read original ospf_area for ${TARGET_DEVICE}/${TARGET_INTERFACE}"
  exit 1
fi
ok "Original ospf_area=${ORIGINAL_AREA}"

step "5/8 - Inject failure through Infrahub (ospf_area=${BROKEN_AREA})"
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/scripts/set_ospf_area.py" \
  --device "$TARGET_DEVICE" --interface "$TARGET_INTERFACE" --area "$BROKEN_AREA"
AREA_MUTATED=1
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/scripts/generate_configs.py"
docker exec "$TARGET_CONTAINER" vtysh \
  -c "configure terminal" -c "interface $TARGET_INTERFACE" \
  -c "no ip ospf area" -c "end" 2>/dev/null || true
docker exec "$TARGET_CONTAINER" vtysh -b || true
sleep 15
ok "Failure injected via SSOT"

step "6/8 - Validate expected failure"
set +e
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/tests/post_check.py" --testbed "$TESTBED"
EXIT_CODE=$?
set -e

if [[ "$EXIT_CODE" -eq 0 ]]; then
  fail "post_check passed unexpectedly while failure was injected"
  exit 1
fi
ok "post_check failed as expected (exit=${EXIT_CODE})"

step "7/8 - Restore SSOT OSPF data and revalidate"
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/scripts/set_ospf_area.py" \
  --device "$TARGET_DEVICE" --interface "$TARGET_INTERFACE" --area "$ORIGINAL_AREA"
RESTORED=1
AREA_MUTATED=0
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/scripts/generate_configs.py"
docker exec "$TARGET_CONTAINER" vtysh \
  -c "configure terminal" -c "interface $TARGET_INTERFACE" \
  -c "no ip ospf area" -c "end" 2>/dev/null || true
docker exec "$TARGET_CONTAINER" vtysh -b || true
sleep 20
INFRAHUB_ADDRESS="$INFRAHUB_ADDRESS" INFRAHUB_TOKEN="$INFRAHUB_TOKEN" \
  "$PYTHON_BIN" "$DEMO_DIR/tests/post_check.py" --testbed "$TESTBED"
ok "Recovery validated"

step "8/8 - Cleanup"
cleanup_lab_if_needed
ok "Failure demo completed successfully"

trap - EXIT INT TERM

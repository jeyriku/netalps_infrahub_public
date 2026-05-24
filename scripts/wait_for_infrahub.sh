#!/usr/bin/env bash
# wait_for_infrahub.sh — Wait for Infrahub to be operational
#
# Usage :
#   bash scripts/wait_for_infrahub.sh [URL] [MAX_RETRIES] [INTERVAL_SEC]
#
# Exemples :
#   bash scripts/wait_for_infrahub.sh
#   bash scripts/wait_for_infrahub.sh http://localhost:8000 40 10

set -euo pipefail

INFRAHUB_URL="${1:-${INFRAHUB_ADDRESS:-http://localhost:8000}}"
MAX_RETRIES="${2:-40}"
INTERVAL="${3:-10}"
HEALTH_ENDPOINT="${INFRAHUB_URL}/api/schema/summary"

echo "=== Attente d'Infrahub sur ${HEALTH_ENDPOINT} ==="

for i in $(seq 1 "${MAX_RETRIES}"); do
    STATUS=$(curl -4 -sf -o /dev/null -w "%{http_code}" "${HEALTH_ENDPOINT}" 2>/dev/null || echo "000")
    if [[ "${STATUS}" =~ ^[23] ]]; then
        echo "=== Infrahub ready (attempt ${i}/${MAX_RETRIES}, HTTP ${STATUS}) ==="
        exit 0
    fi
    echo "  ... tentative ${i}/${MAX_RETRIES} — HTTP ${STATUS} — nouvel essai dans ${INTERVAL}s"
    sleep "${INTERVAL}"
done

echo "=== ERROR: Infrahub not available after ${MAX_RETRIES} attempts ==="
exit 1

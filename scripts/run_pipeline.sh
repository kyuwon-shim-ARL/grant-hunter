#!/bin/bash
# Grant Hunter pipeline runner – suitable for cron
# Cron example (daily 06:00):
#   0 6 * * * /home/kyuwon/projects/grant_hunter/scripts/run_pipeline.sh

set -euo pipefail

PROJECT_DIR="/home/kyuwon/projects/grant_hunter"
LOG_DIR="${PROJECT_DIR}/logs"
DATE=$(date +%Y%m%d)

mkdir -p "${LOG_DIR}"

cd "${PROJECT_DIR}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting grant_hunter pipeline" \
  | tee -a "${LOG_DIR}/pipeline_${DATE}.log"

/home/kyuwon/.venv/bin/python -m grant_hunter.pipeline 2>&1 | tee -a "${LOG_DIR}/pipeline_${DATE}.log"

EXIT_CODE=${PIPESTATUS[0]}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pipeline finished with exit code ${EXIT_CODE}" \
  | tee -a "${LOG_DIR}/pipeline_${DATE}.log"

exit ${EXIT_CODE}

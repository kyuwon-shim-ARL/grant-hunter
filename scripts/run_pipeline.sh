#!/bin/bash
# Grant Hunter pipeline runner – suitable for cron
# Cron example (daily 06:00):
#   0 6 * * * /home/kyuwon/projects/grant_hunter/scripts/run_pipeline.sh

set -euo pipefail

export PATH="$HOME/bin:$PATH"

PROJECT_DIR="/home/kyuwon/projects/grant_hunter"
LOG_DIR="${HOME}/.grant-hunter/logs"
DATE=$(date +%Y%m%d)

mkdir -p "${LOG_DIR}"

cd "${PROJECT_DIR}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting grant_hunter pipeline" \
  | tee -a "${LOG_DIR}/pipeline_${DATE}.log"

/home/kyuwon/.venv/bin/python -m grant_hunter.pipeline 2>&1 | tee -a "${LOG_DIR}/pipeline_${DATE}.log"

EXIT_CODE=${PIPESTATUS[0]}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pipeline finished with exit code ${EXIT_CODE}" \
  | tee -a "${LOG_DIR}/pipeline_${DATE}.log"

if [ ${EXIT_CODE} -ne 0 ]; then
  send-email "kyuwon.shim@ip-korea.org" \
    "[Grant Hunter] Pipeline FAILED (exit code ${EXIT_CODE})" \
    "Pipeline failed at $(date -u +%Y-%m-%dT%H:%M:%SZ). Check log: ${LOG_DIR}/pipeline_${DATE}.log" \
    2>/dev/null || true
fi

exit ${EXIT_CODE}

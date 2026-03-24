#!/bin/bash
# Grant Hunter pipeline runner – suitable for cron
# Cron example (daily 06:00):
#   0 6 * * * /home/kyuwon/projects/grant_hunter/scripts/run_pipeline.sh

set -euo pipefail

export PATH="$HOME/bin:$PATH"

PROJECT_DIR="/home/kyuwon/projects/grant_hunter"
LOG_DIR="${PROJECT_DIR}/data/logs"
DATE=$(date +%Y%m%d)

mkdir -p "${LOG_DIR}"

cd "${PROJECT_DIR}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting grant_hunter pipeline" \
  >> "${LOG_DIR}/pipeline_${DATE}.log"

/home/kyuwon/.venv/bin/python -m grant_hunter.pipeline >> "${LOG_DIR}/pipeline_${DATE}.log" 2>&1

EXIT_CODE=${PIPESTATUS[0]}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pipeline finished with exit code ${EXIT_CODE}" \
  >> "${LOG_DIR}/pipeline_${DATE}.log"

# Update latest report/dashboard symlinks
REPORTS_DIR="${PROJECT_DIR}/data/reports"
LINKS_DIR="${PROJECT_DIR}/reports"
LATEST_REPORT=$(ls -t "${REPORTS_DIR}"/report_*.html 2>/dev/null | head -1)
LATEST_DASHBOARD=$(ls -t "${REPORTS_DIR}"/dashboard_*.html 2>/dev/null | head -1)
if [ -n "${LATEST_REPORT}" ]; then
  ln -sf "${LATEST_REPORT}" "${LINKS_DIR}/latest_report.html"
fi
if [ -n "${LATEST_DASHBOARD}" ]; then
  ln -sf "${LATEST_DASHBOARD}" "${LINKS_DIR}/latest_dashboard.html"
fi

if [ ${EXIT_CODE} -ne 0 ]; then
  send-email "kyuwon.shim@ip-korea.org" \
    "[Grant Hunter] Pipeline FAILED (exit code ${EXIT_CODE})" \
    "Pipeline failed at $(date -u +%Y-%m-%dT%H:%M:%SZ). Check log: ${LOG_DIR}/pipeline_${DATE}.log" \
    2>/dev/null || true
fi

exit ${EXIT_CODE}

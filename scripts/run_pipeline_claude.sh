#!/bin/bash
# Grant Hunter pipeline runner — Claude Code edition
# Uses `claude -p` with MCP tools instead of direct Python pipeline.
# Claude acts as the LLM reranker (no Anthropic API key needed).
#
# Cron example (daily 06:00):
#   0 6 * * * /home/kyuwon/projects/grant_hunter/scripts/run_pipeline_claude.sh
#
# Fallback: if claude CLI is unavailable, runs the classic Python pipeline.

set -euo pipefail

export PATH="$HOME/.local/bin:$HOME/bin:$PATH"

PROJECT_DIR="/home/kyuwon/projects/grant_hunter"
LOG_DIR="${PROJECT_DIR}/data/logs"
DATE=$(date +%Y%m%d)
REPORTS_DIR="${PROJECT_DIR}/data/reports"
LINKS_DIR="${PROJECT_DIR}/reports"

mkdir -p "${LOG_DIR}" "${LINKS_DIR}"
cd "${PROJECT_DIR}"

LOG_FILE="${LOG_DIR}/pipeline_${DATE}.log"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $1" >> "${LOG_FILE}"
}

log "Starting grant_hunter pipeline (claude -p mode)"

# ── MCP config for grant-hunter server ──────────────────────────────
MCP_CONFIG='{"mcpServers":{"grant-hunter":{"command":"uv","args":["--directory","/home/kyuwon/projects/grant_hunter","run","grant-hunter-serve"]}}}'

# ── Prompt: Claude runs the full pipeline via MCP tools ─────────────
PROMPT=$(cat <<'PROMPT_EOF'
You are running the daily grant_hunter pipeline. Execute these steps in order:

1. Call grant_collect tool (do NOT pass sources — omit it to collect from all sources, test: false, profile: "default") to start collection.
2. Poll grant_collect_status with the returned job_id every 10 seconds until status is "complete".
3. Call grant_collect_result with the job_id to get results.
4. Review the collected grants. For each grant in the results, evaluate its relevance to AMR (antimicrobial resistance) + AI (artificial intelligence, machine learning, deep learning, computational biology). Mentally score each 0-2:
   - 0: Not relevant to AMR+AI
   - 1: Tangentially related
   - 2: Directly relevant to AMR+AI research
5. Call grant_report (format: "dashboard") to generate the dashboard report.
6. Call grant_report (format: "html") to generate the HTML report.
7. Output a brief summary: total collected, how many scored 2 (highly relevant), how many scored 1, report paths.

Be concise. Only output the final summary (step 7). Do not explain your process.
PROMPT_EOF
)

# ── Run Claude or fall back to Python pipeline ──────────────────────
if command -v claude &>/dev/null; then
  log "Using claude -p with MCP tools"
  claude -p "${PROMPT}" \
    --model haiku \
    --mcp-config "${MCP_CONFIG}" \
    --allowedTools "mcp__grant-hunter__grant_collect,mcp__grant-hunter__grant_collect_status,mcp__grant-hunter__grant_collect_result,mcp__grant-hunter__grant_report,mcp__grant-hunter__grant_search,mcp__grant-hunter__grant_deadlines,Bash" \
    --max-budget-usd 0.50 \
    --no-session-persistence \
    >> "${LOG_FILE}" 2>&1
  EXIT_CODE=$?
else
  log "claude CLI not found — falling back to Python pipeline"
  /home/kyuwon/.venv/bin/python -m grant_hunter.pipeline >> "${LOG_FILE}" 2>&1
  EXIT_CODE=$?
fi

log "Pipeline finished with exit code ${EXIT_CODE}"

# ── Update latest report/dashboard symlinks ─────────────────────────
LATEST_REPORT=$(ls -t "${REPORTS_DIR}"/report_*.html 2>/dev/null | head -1)
LATEST_DASHBOARD=$(ls -t "${REPORTS_DIR}"/dashboard_*.html 2>/dev/null | head -1)
if [ -n "${LATEST_REPORT}" ]; then
  ln -sf "${LATEST_REPORT}" "${LINKS_DIR}/latest_report.html"
fi
if [ -n "${LATEST_DASHBOARD}" ]; then
  ln -sf "${LATEST_DASHBOARD}" "${LINKS_DIR}/latest_dashboard.html"
fi

# ── Failure notification ────────────────────────────────────────────
if [ ${EXIT_CODE} -ne 0 ]; then
  send-email "kyuwon.shim@ip-korea.org" \
    "[Grant Hunter] Pipeline FAILED (exit code ${EXIT_CODE})" \
    "Pipeline failed at $(date -u +%Y-%m-%dT%H:%M:%SZ). Check log: ${LOG_FILE}" \
    2>/dev/null || true
fi

exit ${EXIT_CODE}

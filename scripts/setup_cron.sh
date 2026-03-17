#!/usr/bin/env bash
# setup_cron.sh - Register weekly_reminder.py as a Monday 9:00 AM KST cron job.
#
# Usage:
#   ./setup_cron.sh <recipient_email>
#   ./setup_cron.sh --remove   # remove the cron entry

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEEKLY_REMINDER="${SCRIPT_DIR}/weekly_reminder.py"
PYTHON_BIN="/home/kyuwon/.venv/bin/python"
LOG_FILE="${SCRIPT_DIR}/../outputs/cron_weekly_reminder.log"
CRON_MARKER="grant_hunter_weekly_reminder"

# ---- helpers ----------------------------------------------------------------

usage() {
    echo "Usage: $0 <recipient_email>"
    echo "       $0 --remove"
    exit 1
}

ensure_log_dir() {
    mkdir -p "$(dirname "${LOG_FILE}")"
}

# ---- main -------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
    usage
fi

if [[ "$1" == "--remove" ]]; then
    echo "Removing grant_hunter weekly reminder from crontab..."
    crontab -l 2>/dev/null | grep -v "${CRON_MARKER}" | crontab -
    echo "Done. Removed cron entry (if it existed)."
    exit 0
fi

RECIPIENT="$1"

# Validate email format (basic)
if [[ ! "$RECIPIENT" =~ ^[^@]+@[^@]+\.[^@]+$ ]]; then
    echo "ERROR: Invalid email address: ${RECIPIENT}" >&2
    exit 1
fi

if [[ ! -f "${WEEKLY_REMINDER}" ]]; then
    echo "ERROR: weekly_reminder.py not found at ${WEEKLY_REMINDER}" >&2
    exit 1
fi

ensure_log_dir

# Build cron line: every Monday at 09:00 KST
# KST = UTC+9, so cron (UTC) runs at 00:00 Monday UTC = 09:00 Monday KST
# If cron is already in KST (system clock is KST), use: 0 9 * * 1
# Detect system timezone
SYS_TZ="$(timedatectl show --property=Timezone --value 2>/dev/null || echo "Unknown")"

if [[ "${SYS_TZ}" == "Asia/Seoul" ]]; then
    CRON_HOUR=9
    TZ_NOTE="(system is KST, cron at 09:00 local)"
else
    CRON_HOUR=0
    TZ_NOTE="(system is ${SYS_TZ}, cron at 00:00 UTC = 09:00 KST)"
fi

CRON_CMD="${PYTHON_BIN} ${WEEKLY_REMINDER} ${RECIPIENT} >> ${LOG_FILE} 2>&1"
CRON_LINE="0 ${CRON_HOUR} * * 1 ${CRON_CMD} # ${CRON_MARKER}"

# Check for duplicate
EXISTING_CRONTAB="$(crontab -l 2>/dev/null || echo "")"

if echo "${EXISTING_CRONTAB}" | grep -q "${CRON_MARKER}"; then
    echo "Cron entry already exists. Updating it..."
    NEW_CRONTAB="$(echo "${EXISTING_CRONTAB}" | grep -v "${CRON_MARKER}")"
else
    echo "Adding new cron entry..."
    NEW_CRONTAB="${EXISTING_CRONTAB}"
fi

# Append and install
printf "%s\n%s\n" "${NEW_CRONTAB}" "${CRON_LINE}" | grep -v '^$' | crontab -

echo ""
echo "Cron entry registered successfully."
echo "  Schedule : Every Monday ${TZ_NOTE}"
echo "  Recipient: ${RECIPIENT}"
echo "  Script   : ${WEEKLY_REMINDER}"
echo "  Log      : ${LOG_FILE}"
echo ""
echo "Current crontab (grant_hunter entries):"
crontab -l | grep "${CRON_MARKER}" || echo "  (none found - something went wrong)"

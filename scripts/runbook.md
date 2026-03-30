# Grant Hunter Operations Runbook

## 1. Alert Conditions & Response

### ZERO_COLLECT
**Meaning:** A source returned 0 grants but reported `success=True`. The collector completed without error but fetched nothing — typically a sign of an upstream API change, empty query results, or a silent scraping failure.

**Immediate actions:**
1. Check the pipeline log for that source: `grep "ZERO_COLLECT\|collected 0" /home/kyuwon/projects/grant_hunter/data/logs/pipeline_$(date +%Y%m%d).log`
2. Manually test the source collector in isolation (see Dry-Run section).
3. Verify the upstream API/portal is reachable and returning data.

---

### VOLUME_DROP
**Meaning:** Total grants collected this run dropped below 50% of the 7-run average. Possible causes: partial API outage, changed pagination, keyword/filter config drift, or a source going dark.

**Immediate actions:**
1. Check per-source counts in the log: `grep "collected=" /home/kyuwon/projects/grant_hunter/data/logs/pipeline_$(date +%Y%m%d).log`
2. Identify which source(s) dropped. Compare with previous snapshot files in `data/snapshots/`.
3. If one source accounts for the drop, treat it as SOURCE_FAIL for that source.
4. If all sources dropped uniformly, check network connectivity and API keys.

---

### SOURCE_FAIL
**Meaning:** A collector raised an exception or returned an error after all retries. The `success` flag is `False` and an error message is recorded.

**Immediate actions:**
1. Read the error: `grep "SOURCE_FAIL\|ERROR\|failed after" /home/kyuwon/projects/grant_hunter/data/logs/pipeline_$(date +%Y%m%d).log`
2. Check if the error is transient (timeout, HTTP 5xx) or permanent (auth failure, API removed).
3. For transient errors: rerun the pipeline (see Recovery Procedures).
4. For auth/config errors: check environment variables and API keys before rerunning.

---

## 2. Recovery Procedures

### Step 1 — Check logs
```bash
# Most recent log
ls -lt /home/kyuwon/projects/grant_hunter/data/logs/ | head -5

# Tail the latest log for errors
tail -100 /home/kyuwon/projects/grant_hunter/data/logs/pipeline_$(date +%Y%m%d).log | grep -E "ERROR|WARNING|FAIL|ANOMALY"
```

### Step 2 — Verify upstream connectivity
```bash
# Check Grants.gov API
curl -s -o /dev/null -w "%{http_code}" "https://api.grants.gov/v1/api/search2" -X POST -H "Content-Type: application/json" -d '{"rows":1}'

# Check EU Portal (basic reachability)
curl -s -o /dev/null -w "%{http_code}" "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/horizon-results-platform"
```

### Step 3 — Manual rerun
```bash
cd /home/kyuwon/projects/grant_hunter && uv run python -m grant_hunter.pipeline
```

To run with a specific profile:
```bash
cd /home/kyuwon/projects/grant_hunter && uv run python -m grant_hunter.pipeline --profile wetlab_amr
```

### Step 4 — Verify the fix
After the rerun completes, check:
```bash
# Confirm no anomaly alerts in new log
grep "ANOMALY\|anomaly_alerts" /home/kyuwon/projects/grant_hunter/data/logs/pipeline_$(date +%Y%m%d).log

# Check uptime report
cd /home/kyuwon/projects/grant_hunter && uv run python scripts/check_uptime.py

# Inspect latest run_history entry
python3 -c "
import json
from pathlib import Path
h = json.loads(Path('data/run_history.json').read_text())
print(json.dumps(h[-1], indent=2))
"
```

---

## 3. Escalation

**Trigger:** 2 or more consecutive pipeline runs with failures (SOURCE_FAIL or ZERO_COLLECT on the same source, or repeated VOLUME_DROP).

**Detection:**
```bash
cd /home/kyuwon/projects/grant_hunter && python3 -c "
import json
from pathlib import Path
h = json.loads(Path('data/run_history.json').read_text())
# Show last 5 runs: success status per source
for entry in h[-5:]:
    ts = entry.get('run_at','?')
    src_status = {s: info.get('success') for s, info in entry.get('sources',{}).items()}
    print(ts, src_status)
"
```

**Actions on escalation:**
1. Do NOT rely on automatic retry — investigate manually.
2. Check if the upstream API has changed its schema, authentication, or rate limits.
3. Inspect the collector source code for the affected source:
   - NIH: `src/grant_hunter/collectors/nih.py`
   - EU Portal: `src/grant_hunter/collectors/eu_portal.py`
   - Grants.gov: `src/grant_hunter/collectors/grants_gov.py`
4. If a collector needs patching, fix and run the test suite before redeploying:
   ```bash
   cd /home/kyuwon/projects/grant_hunter && uv run pytest tests/ -v
   ```
5. Contact the data owner (kyuwon.shim@ip-korea.org) if the issue persists beyond one business day.

---

## 4. Dry-Run Verification

Use these commands to test each recovery procedure safely, without overwriting production snapshots or sending real emails.

### Test a single collector in isolation
```bash
cd /home/kyuwon/projects/grant_hunter && uv run python3 -c "
from grant_hunter.collectors.grants_gov import GrantsGovCollector
c = GrantsGovCollector()
grants = c.collect()
print(f'Collected {len(grants)} grants from grants_gov')
"
# Replace GrantsGovCollector with NIHCollector or EUPortalCollector as needed
```

### Test anomaly detection with a fake summary
```bash
cd /home/kyuwon/projects/grant_hunter && uv run python3 -c "
from pathlib import Path
from grant_hunter.monitoring import check_volume_anomaly
summary = {
    'run_at': '2026-01-01T00:00:00',
    'total_collected': 5,
    'filtered': 5,
    'eligible': 1,
    'sources': {'grants_gov': {'collected': 0, 'success': True}},
}
alerts = check_volume_anomaly(summary, Path('data/run_history.json'))
print('Alerts:', alerts)
"
```

### Test send_anomaly_alert (dry run — no real email)
```bash
cd /home/kyuwon/projects/grant_hunter && uv run python3 -c "
from unittest.mock import patch, MagicMock
from grant_hunter.monitoring import send_anomaly_alert
alerts = ['ZERO_COLLECT: grants_gov collected 0 grants']
with patch('subprocess.run') as mock:
    mock.return_value = MagicMock(returncode=0)
    result = send_anomaly_alert(alerts, 'test@example.com')
    print('Alert sent (mocked):', result)
    print('Called with:', mock.call_args[0][0])
"
```

### Test the uptime report
```bash
cd /home/kyuwon/projects/grant_hunter && uv run python scripts/check_uptime.py --days 30
# Or with a custom history file for testing:
# uv run python scripts/check_uptime.py --file /tmp/test_history.json
```

### Run the full test suite
```bash
cd /home/kyuwon/projects/grant_hunter && uv run pytest tests/ -v
```

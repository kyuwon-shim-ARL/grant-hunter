---
name: dashboard
description: Generate interactive HTML dashboard with grant overview, calendar, and sortable table
---

# Grant Dashboard

Generate an interactive HTML dashboard.

## Execution

1. Call `grant_report` MCP tool with format="dashboard"

2. Show the user:
   - Dashboard path
   - Summary stats (total grants, eligible count, avg score)
   - How to open: "Open in browser: file://<path>"

3. If user wants the basic report instead, call with format="html"

## Output
The dashboard includes:
- KPI summary cards
- Deadline calendar (90-day view)
- Sortable grant table with eligibility color-coding
- Client-side filters by source and eligibility

---
name: collect
description: Run AMR+AI grant collection from 3 sources (NIH, EU Portal, Grants.gov)
---

# Grant Collection

Run the full grant collection pipeline.

## Execution

1. Start collection: Call `grant_collect` MCP tool
   - If user specified a source (e.g., "/grant-hunter:collect nih"), pass sources=["nih"]
   - Otherwise, collect from all sources

2. Poll progress: Call `grant_collect_status` every few seconds
   - Show user which sources have completed as they finish

3. Get results: Call `grant_collect_result` when done

4. Present summary to user:
   ```
   Collection complete!
   - Total collected: X grants from Y sources
   - After keyword filter: Z grants (AMR+AI relevant)
   - Eligible for IPK: A | Uncertain: B | Ineligible: C
   - Report: <path>
   ```

5. If user has Google Workspace MCP available, offer to send email report

## Error Handling
- If a source fails, show which sources succeeded and which failed
- Partial results are still valuable - don't treat partial failure as total failure

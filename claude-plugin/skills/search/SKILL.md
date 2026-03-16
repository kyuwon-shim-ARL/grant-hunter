---
name: search
description: Search collected grants by keyword, source, or criteria
---

# Grant Search

Search through collected grants.

## Execution

1. Parse the user's query from the arguments
   - Examples: "NIH R01 AMR", "eligible grants over $1M", "EU Horizon"

2. Call `grant_search` MCP tool with:
   - query: the search terms
   - eligible_only: true if user says "eligible" or "IPK에서 낼 수 있는"
   - min_score: extract if user mentions score threshold
   - source: extract if user mentions a specific source

3. Format results as a table:
   | Title | Source | Deadline | Score | Eligibility | Amount |
   |-------|--------|----------|-------|-------------|--------|

4. For each result, the URL is available if user wants details

## Tips
- If no results, suggest broadening the search
- If too many results, suggest adding eligibility or score filters
- Show top 10 by default, offer to show more

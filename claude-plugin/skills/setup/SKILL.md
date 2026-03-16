---
name: setup
description: Initialize Grant Hunter configuration (email, data directory, test connection)
---

# Grant Hunter Setup

Guide the user through initial setup of Grant Hunter.

## Steps

1. **Check Python MCP server**: Verify `grant-hunter-mcp` is installed
   - If not: tell user to run `uvx install grant-hunter-mcp` or `pip install grant-hunter-mcp`

2. **Configure email**: Ask the user for their notification email
   - Call MCP tool `grant_config_set` with key="email", value=<user's email>

3. **Test connection**: Run a quick test collection
   - Call MCP tool `grant_collect` with sources=["nih"], test=true
   - Poll `grant_collect_status` until done
   - Show results: "Connected successfully! Found X grants from NIH."

4. **Show next steps**:
   - `/grant-hunter:collect` to run full collection
   - `/grant-hunter:deadlines` to see upcoming deadlines
   - `/grant-hunter:search <query>` to search grants

## Error Handling
- If MCP server not available: Guide pip/uvx installation
- If test collection fails: Check network, suggest retry

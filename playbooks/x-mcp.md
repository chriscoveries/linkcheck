# x-mcp

Drive the account's X MCP server (`namespace: x`) the same way every time: plan → call → save → ingest. Read-only tools only.

Prefer this over `check-own-posts` / `monitor` when the bot already has X MCP tools. Keep `monitor` only as a bearer-token fallback.

## Loop

```bash
linkcheck x-plan <playbook> [args] --json   # note call_count; respect limits
# For each calls[i]: CallDynamicTool {namespace, toolName: tool, arguments}
# If arguments contain {"$from":"stepN..."}, run: linkcheck x-plan --resolve plan.json --outputs prior.json --json
# Save every raw tool result (fences/footers OK) into one file
linkcheck x-ingest --file raw.json --json   # compact; add --verbose for full detail
```

Exit codes: `0` clear, `1` ask, `2` stop.

## Playbooks

| Id | Command |
| --- | --- |
| `own-posts` | `linkcheck x-plan own-posts --username <name> --json` |
| `own-posts` | `linkcheck x-plan own-posts --user-id <id> --json` |
| `shared-code` | `linkcheck x-plan shared-code --file <draft> --json` |
| `shared-script` | `linkcheck x-plan shared-script --file <draft> --json` |
| `cluster` | `linkcheck x-plan cluster --query <q> --start-time <iso> --json` |

Each call is exactly `{namespace, tool, arguments}` with array fields (e.g. `"post.fields":["id","text","entities","created_at","author_id"]`). `max_results` ≤ 25. Plans cap at 30 calls; rate limits are 30/min and 1000/day UTC (`limits` on the plan).

`$from` example: `"id": {"$from": "step1.data.id"}`. Never guess — resolve with `--resolve` / `--outputs`.

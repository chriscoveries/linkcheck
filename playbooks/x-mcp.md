# x-mcp

Drive the account's X MCP server (`namespace: x`): plan → call → save to a file → ingest. Read-only. Prefer this over bearer `monitor`.

## Loop

```bash
linkcheck x-plan <playbook> [args] --json
# CallDynamicTool each {namespace, tool, arguments}; save raw output to a file (do not read inline)
linkcheck x-plan --resolve plan.json --outputs step1.txt --json   # if {$from} present
linkcheck x-ingest --file raw.json --json
```

## Link reads (own-posts / all-posts)

Query defaults to `from:<username> has:links -is:retweet` (never pages link-less posts).

- `--include-reposts` drops `-is:retweet`
- `--exclude-replies` adds `-is:reply`
- `post.fields` = `["id","created_at","entities"]` only (add `--with-text` for script checks)
- No expansions, no user.fields; `max_results` always 25
- Read math: `ceil(posts_with_links / 25) = reads`
- `--preflight` adds `get_posts_counts_recent` to estimate pages

### all-posts (full history)

```bash
linkcheck x-plan all-posts --username <name> --state state.json --json
# run the single call; save output
linkcheck x-ingest --file page.json --append state.json --json
# repeat until done:true (follow next_token only)
# later: --incremental to fetch only new link posts via since_id
```

Respect `wait_until` when rate-capped (30/min, 1000/day UTC).

## Other playbooks

| Id | Command |
| --- | --- |
| `own-posts` | `linkcheck x-plan own-posts --username <name> --json` |
| `shared-code` | `linkcheck x-plan shared-code --file <draft> --json` |
| `shared-script` | `linkcheck x-plan shared-script --file <draft> --json` |
| `cluster` | `linkcheck x-plan cluster --query <q> --start-time <iso> --json` |
| `all-posts` | `linkcheck x-plan all-posts --username <name> --state state.json --json` |

Exit: `0` clear, `1` ask, `2` stop.

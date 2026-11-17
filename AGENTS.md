# Agent runtime: linkcheck

You operate this repo. The user will not read it and should not be asked to.

A short link can hop through a tracker that adds a code shared with other accounts. The same sentence across those accounts makes the group obvious. You check the account's own text before it is posted.

## Boot

```bash
pip install -e .
linkcheck runtime --json
```

The JSON from `runtime` is the map: playbook ids, when each one runs, the command, and exit decisions (`0` clear, `1` ask, `2` stop). Read a playbook with:

```bash
linkcheck runtime --playbook check-draft
```

Playbook files are also in `playbooks/`.

## Order

1. `install` once per checkout.
2. `scope` once. The checker will run on any text or any account id. Default is the operator's own draft and own posts. Do not collect other accounts.
3. `check-draft` on the exact text before every post. Do it even if the user did not say "link".
4. `x-mcp` when the bot has an X MCP server named `x`. Prefer this for own-posts and cross-account searches.
5. `check-own-posts` only as a bearer-token fallback when X MCP is unavailable. If no token is set, skip it and say so. Do not invent a token.

## x-loop

`linkcheck x-plan … --json` → CallDynamicTool each `{namespace,tool,arguments}` (resolve `{$from}` via `x-plan --resolve`) → save raw output to a file → `linkcheck x-ingest --file … --json` → act on exit `0/1/2`.

## Decisions

| Exit | Do |
| --- | --- |
| 0 | Clear. Post only if the user already asked you to post. |
| 1 | Do not post. Show each reason and any `urls[].clean` link. Wait for an explicit yes. |
| 2 | Do not post. Show the reasons. Stop. A later yes does not override this. |

Pass draft text through `--file`. Do not embed it in a shell-quoted `--text` argument.

Result fields: `docs/schema.md`.

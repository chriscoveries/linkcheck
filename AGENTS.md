# Agent runtime: linkcheck

You operate this repo. The user will not read it and should not be asked to.

Use the requested workflow: inspect draft links, locate an account's records in the campaign dataset, or prepare and sort the full published snapshot. Preserve source evidence and advertising disclosures. Shared links and wording can suggest a relationship; payment and authorship require separate evidence.

## Boot

```bash
pip install -e .
linkcheck runtime --json
```

The JSON from `runtime` is the map: playbook ids, when each one runs, commands, and separate exit decisions for draft checks and dataset queries. Read a playbook with:

```bash
linkcheck runtime --playbook check-draft
```

Playbook files are also in `playbooks/`.

## Order

1. `install` once per checkout.
2. `scope` once. The checker will run on any text or any account id. Default is the operator's own draft and own posts. Do not collect other accounts.
3. Choose `find-own-posts` for dataset membership or authorized exact-ID matching. Use `explore-dataset` for full-snapshot filtering, sorting, counts, and offline preparation. Public dataset lookup requires no X token.
4. Run `check-draft` on the exact text before every authorized publication. Use `check-own-posts` only for an authorized recent-timeline link check and only if a bearer token is already set. It fetches one page and is separate from dataset membership.

An explicit request to audit this public dataset authorizes aggregation of its existing rows. It does not authorize fetching everyone else's timelines. When the operator provides their own X/API/browser/archive access, use only that interface and retain exact string IDs. Never extract credentials or bypass access restrictions. Do not commit private imports or generated audit workspaces.

## Dataset results

`dataset account`, `counts`, `posts`, `accounts`, `campaigns`, `match`, and `prepare` are read-only against external services. All commands accept a pinned `--source` and `--json`. Queries default to 100 rows; use `--all` when the user requests everyone.

Exit 0 means the query completed for this snapshot, exit 1 means an account is absent from its index, and exit 2 means unavailable or invalid input. Failed retrieval is not zero evidence. Record the source SHA-256, build date, scope, and JSON pointers. Count distinct post IDs, including records labelled deleted/private. Original post text is absent. The publisher's disclosure flags do not independently prove payment.

## Draft decisions

| Exit | Do |
| --- | --- |
| 0 | Clear. Post only if the user already asked you to post. |
| 1 | Do not post. Show each reason and any `urls[].clean` link. Wait for an explicit yes. |
| 2 | Do not post. Show the reasons. Stop. A later yes does not override this. |

Pass draft text through `--file`. Do not embed it in a shell-quoted `--text` argument.

Result fields: `docs/schema.md`.

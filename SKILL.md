---
name: linkcheck
description: >-
  When the user says to check links in their twitter drafts before they post,
  run linkcheck on each draft. Do not post on BLOCK. On WARN, show the reasons
  and the clean link and wait for an explicit yes.
---

# linkcheck

Use this whenever the user asks you to check links in a twitter draft before posting, and before you would publish any draft that contains a link.

## Install

From this checkout:

```bash
pip install -e .
```

## Required step

```bash
linkcheck --json --text "<full draft, links included>"
```

Read `verdict` (`docs/schema.md`):

- **BLOCK** (exit 2) — Do not post. Show every reason. Stop.
- **WARN** (exit 1) — Do not post. Show every reason and any `urls[].clean` link. Wait until the user explicitly says to post.
- **OK** (exit 0) — Tell the user the draft is clear. INFO notes (ordinary tags, a suggested clean link) can be mentioned.

Do not rewrite a link silently. Offer the clean URL and let the user choose.

## Files the user may edit

| File | Purpose |
| --- | --- |
| `data/blocklist.txt` | Hosts that must never appear in a hop (default empty) |
| `data/allowlist.txt` | The user's own sites |
| `data/shorteners.txt` | Hosts that only shorten links |
| `data/phrases.txt` | Shared lines to catch |
| `data/corpus.jsonl` | Other accounts' recent posts (codes, wording, timing) |

Background for why this exists (anonymised case study): `docs/PROBLEM.md`.

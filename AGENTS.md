# Agent instructions: linkcheck

The user points you at this repo and says: check my links in my twitter drafts before I post.

You run the check. You do not post the draft.

## Install

```bash
pip install -e .
```

## On every draft

```bash
linkcheck --json --text "<draft>"
```

| Verdict | Exit | What you do |
| --- | --- | --- |
| `BLOCK` | 2 | Do not post. Show `reasons`. Stop. |
| `WARN` | 1 | Do not post. Show each reason in plain language and any suggested `clean` URL. Wait for an explicit yes. |
| `OK` | 0 | Tell the user the draft is clear. |

## Rules

1. Run the check on the exact text that would be posted.
2. Do not strip or swap a link unless the user accepts the clean URL.
3. Tracker hosts the user wants to hard-fail go in `data/blocklist.txt` (one host per line). It ships empty.
4. Their own sites go in `data/allowlist.txt`.
5. Optional: fill `data/corpus.jsonl` so shared codes and repeated wording can be seen. `scripts/fetch_corpus.py` can refresh it when `X_BEARER_TOKEN` is set.
6. Optional: `linkcheck monitor --user-id <id>` reviews posts that are already up.

## What you are preventing

A short link can pass through a hidden hop that adds a code shared with many other accounts. The same sentence posted by those accounts makes the group obvious. Details and placeholder diagrams: `docs/problem.md`.

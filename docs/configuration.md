# Configuration files

Overview also in [guide.md](guide.md#files). This page is the format reference
with copy-paste examples.

Defaults resolve from repo `data/` when present, else the packaged
`linkcheck/data/` bundle. Override with `--blocklist`, `--allowlist`,
`--shorteners`, `--phrases`, `--corpus`.

## Domain lists

Shared rules for `blocklist.txt`, `allowlist.txt`, `shorteners.txt`:

- One hostname per line; `#` comments; blank lines ignored
- `www.` stripped; listed parents match subdomains

### Blocklist → BLOCK

```text
# data/blocklist.txt (ships empty)
track.example
newtrack.example
```

### Allowlist

Skips intermediate-hop and age warnings for your sites. Does **not** clear
`cid` / opaque codes on those hosts.

```text
# data/allowlist.txt
myblog.example
```

### Shorteners

Intermediate hops on these are expected. Packaged list includes `t.co`,
`bit.ly`, and other public shorteners.

## Phrases → `script_phrase`

```text
# data/phrases.txt
the same sentence is posted by each account in this example
```

Matching: case-insensitive substring after URLs, `@handles`, and `#tags` are
removed.

## Corpus JSONL

14-day lookback. Required: account + text.

```json
{"account": "account_a", "text": "The same sentence is posted by each account in this example.", "created_at": "2026-11-17T12:00:00Z", "urls": ["https://news.example/story?utm_campaign=a1b2c3d4"]}
{"account": "account_b", "text": "The same sentence is posted by each account in this example.", "created_at": "2026-11-17T12:00:00Z", "urls": ["https://news.example/story?utm_campaign=a1b2c3d4"]}
{"account": "account_c", "text": "The same sentence is posted by each account in this example.", "created_at": "2026-11-17T12:00:00Z", "urls": ["https://news.example/story?utm_campaign=a1b2c3d4"]}
```

| Field | Required | Role |
| --- | --- | --- |
| `account` / `username` / `author` | yes | Distinct poster |
| `text` / `full_text` | yes | Body |
| `created_at` / `date` | no | Lookback + `posting_time_cluster` |
| `urls` | no | Shared-code detection |
| `id` | no | Ignored for verdict |

Thresholds: similarity ≥ 0.85, ≥ 3 accounts; timing window 168 hours. Deep dive:
[how-it-works.md](how-it-works.md).

Refresh (needs token):

```bash
python scripts/fetch_corpus.py --user-id 111 --user-id 222 --out data/corpus.jsonl
```

Never commit bearer tokens. Prefer placeholder account labels in fixtures.

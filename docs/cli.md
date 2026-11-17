# CLI reference

Narrative usage and “how to read a report” live in [guide.md](guide.md). This
page is the compact flag / exit / env sheet.

```bash
linkcheck --version
# linkcheck 0.1.0
```

## Synopsis

```text
linkcheck [global options] [urls ...]
linkcheck [global options] monitor --user-id ID [--max-results N]
```

Global options must appear **before** `monitor` (for example
`linkcheck --json monitor --user-id 123`).

## Inputs

| Flag | Description |
| --- | --- |
| `--text`, `-t` | Draft text |
| `--file`, `-f` | Draft file (UTF-8) |
| `--stdin` | Read stdin (also implied when piped with no other text) |
| `urls` | Positional URLs; also extracted from text |

At least one input is required.

## Output and data paths

| Flag | Description |
| --- | --- |
| `--json` | JSON only — [schema.md](schema.md) |
| `--blocklist PATH` | Override blocklist |
| `--allowlist PATH` | Override allowlist |
| `--shorteners PATH` | Override shorteners (default: packaged / repo list) |
| `--phrases PATH` | Phrase list |
| `--corpus PATH` | JSONL corpus |
| `--no-age` | Skip RDAP/WHOIS |
| `--version` | Print version |
| `-h`, `--help` | Help |

## `monitor`

| Flag | Required | Default |
| --- | --- | --- |
| `--user-id` | yes | — |
| `--max-results` | no | 10 (API helper clamps 5–100) |

```bash
linkcheck --json monitor --user-id 123
```

Details: [monitor.md](monitor.md).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | OK (INFO-only counts as OK) |
| 1 | WARN, or monitor config/API error |
| 2 | BLOCK |

```bash
linkcheck --no-age --text "https://news.example/story?utm_campaign=a1b2c3d4"; echo $?
# 1
linkcheck --no-age --text "https://news.example/story"; echo $?
# 0
```

## Environment

| Variable | Used by |
| --- | --- |
| `X_BEARER_TOKEN` | `monitor`, `scripts/fetch_corpus.py` |
| `TWITTER_BEARER_TOKEN` | Accepted alias |

Privacy of network calls: [limitations-and-privacy.md](limitations-and-privacy.md).

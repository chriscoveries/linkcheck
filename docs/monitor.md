# Monitor (already-posted check)

Guide summary: [guide.md](guide.md#posts-that-are-already-up). This page is the
dedicated reference.

`linkcheck monitor` re-checks **your own** recent posts via X API v2. It does
not post, delete, or edit.

## Requirements

- `X_BEARER_TOKEN` or `TWITTER_BEARER_TOKEN`
- Numeric `--user-id` you are allowed to read

## Usage

Put global flags **before** the subcommand:

```bash
export X_BEARER_TOKEN=...
linkcheck --json monitor --user-id 1234567890 --max-results 10
```

Without a token:

```bash
linkcheck --json monitor --user-id 123
```

```json
{
  "exit_code": 1,
  "message": "Set X_BEARER_TOKEN (or TWITTER_BEARER_TOKEN) to use monitor.",
  "posts": []
}
```

## Behaviour

1. Fetch recent tweets for the user
2. Run the draft checker on each (`check_age=False`)
3. Return only WARN/BLOCK posts
4. `exit_code` is the worst post exit code (or 1 on config/API errors)

Corpus refresh is separate: `scripts/fetch_corpus.py` — see
[configuration.md](configuration.md).

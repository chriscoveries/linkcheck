# `linkcheck --json` output schema

Stable contract for agents and scripts. `schema_version` is `"1.0"`.
(`json-schema.md` redirects here.)

```bash
linkcheck --no-age --json --text "A note https://news.example/story?utm_campaign=a1b2c3d4&utm_medium=cpc"
```

## Top-level object

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | `"1.0"` |
| `verdict` | string | `OK` \| `WARN` \| `BLOCK` |
| `exit_code` | int | `0` / `1` / `2` |
| `reasons` | Finding[] | All findings |
| `urls` | UrlReport[] | Per-URL hops + findings |
| `script_match` | object \| null | Wording / shared-code / timing |
| `text_excerpt` | string | Truncated draft |

## Finding

```json
{
  "severity": "WARN",
  "code": "campaign_code",
  "message": "'utm_campaign' carries an opaque code (a1b2c3d4) that can group this post with others using the same value",
  "detail": {
    "key": "utm_campaign",
    "values": ["a1b2c3d4"],
    "url": "https://news.example/story?utm_campaign=a1b2c3d4&utm_medium=cpc"
  }
}
```

### Codes

| Code | Severity | Meaning |
| --- | --- | --- |
| `blocklisted_hop` | BLOCK | Hop host on blocklist |
| `intermediate_hop` | WARN | Unexpected middle hop |
| `young_domain` | WARN | Host younger than ~90 days |
| `domain_age_unknown` | INFO | Age lookup failed soft |
| `utm_params` | INFO | Word-like UTM keys |
| `campaign_code` | WARN | Opaque token in `utm_*` |
| `tracking_param` | WARN | Identifying key (`cid`, …) |
| `tracking_token` | WARN | Opaque token on other keys |
| `clean_url_suggestion` | INFO | Tracking-stripped URL |
| `script_near_duplicate` | WARN | Near-dupe vs ≥3 accounts |
| `script_phrase` | WARN | Phrase list hit |
| `shared_tracking_code` | WARN | Same code on ≥3 accounts |
| `posting_time_cluster` | WARN | Near-dupes bunched in time |

## UrlReport

```json
{
  "input": "https://news.example/story?utm_campaign=a1b2c3d4",
  "hops": [
    {
      "index": 0,
      "url": "https://news.example/story?utm_campaign=a1b2c3d4",
      "status": null,
      "via": "error",
      "error": "…NameResolutionError…"
    }
  ],
  "final": "https://news.example/story?utm_campaign=a1b2c3d4",
  "clean": "https://news.example/story",
  "findings": []
}
```

`via`: `location` | `meta-refresh` | `js` | `final` | `error`.

## ScriptMatchReport

```json
{
  "checked": true,
  "near_duplicate": false,
  "match_count_accounts": 0,
  "max_similarity": 0.0,
  "matched_accounts": [],
  "phrase_hits": [],
  "shared_tracking_codes": [],
  "findings": []
}
```

## Monitor JSON

`linkcheck --json monitor --user-id …` returns a different object:

```json
{
  "exit_code": 1,
  "message": "Set X_BEARER_TOKEN (or TWITTER_BEARER_TOKEN) to use monitor.",
  "posts": []
}
```

## Exit codes

| Code | Verdict |
| --- | --- |
| 0 | OK (including INFO-only) |
| 1 | WARN |
| 2 | BLOCK |

# `linkcheck --json` output schema

Stable contract for agents and scripts. `schema_version` is currently `"1.0"`.

## Top-level object

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Schema revision (`"1.0"`) |
| `verdict` | string | `OK` \| `WARN` \| `BLOCK` |
| `exit_code` | int | `0` OK, `1` WARN, `2` BLOCK |
| `reasons` | array of Finding | All findings across URLs + wording checks |
| `urls` | array of UrlReport | Per-URL hop chains and findings |
| `script_match` | object \| null | Near-duplicate / shared-code report |
| `text_excerpt` | string | Truncated draft text |

## Finding

```json
{
  "severity": "INFO|WARN|BLOCK",
  "code": "blocklisted_hop",
  "message": "Human-readable explanation",
  "detail": {}
}
```

Common `code` values: `blocklisted_hop`, `intermediate_hop`, `young_domain`, `domain_age_unknown`, `utm_params`, `campaign_code`, `tracking_param`, `tracking_token`, `clean_url_suggestion`, `dead_link`, `script_near_duplicate`, `script_phrase`, `shared_tracking_code`, `posting_time_cluster`.

`linkcheck x-ingest --json` defaults to compact `{verdict, exit_code, reasons, clean_urls}`; `--verbose` returns this full schema plus `posts`.

`utm_params` is INFO when the values are ordinary words. `campaign_code` is WARN when a `utm_*` value is an opaque token (for example 8 hex characters), because that token is enough to cluster posts even when the surrounding UTM names look routine.

## UrlReport

```json
{
  "input": "https://example.com/a",
  "hops": [
    {"index": 0, "url": "https://example.com/a", "status": 302, "via": "location", "error": null},
    {"index": 1, "url": "https://example.com/b", "status": 200, "via": "final", "error": null}
  ],
  "final": "https://example.com/b",
  "clean": "https://example.com/b",
  "findings": []
}
```

`via` is one of: `location`, `meta-refresh`, `js`, `final`, `error`.

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

## Exit codes

| Code | Verdict |
| --- | --- |
| 0 | OK (including INFO-only) |
| 1 | WARN |
| 2 | BLOCK |

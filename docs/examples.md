# Examples

Placeholder hosts only. `news.example` and `track.example` do not resolve, so the hop line ends in a connection error. The verdict does not depend on that. Codes and blocklist hits are read from the URL itself.

`--no-age` is used so the examples do not wait on a registration lookup.

## OK: ordinary tags

```bash
linkcheck --no-age --text "A short note https://news.example/story?utm_medium=social&utm_campaign=spring"
```

Exit code 0. Word-like `utm_*` values are INFO. The clean link drops them.

```text
Verdict: OK
Reasons:
  [INFO] utm_params: Plain UTM parameters present (often benign): utm_campaign, utm_medium
  [INFO] clean_url_suggestion: Suggested clean link (tracking stripped): https://news.example/story
```

## WARN: an opaque code

```bash
linkcheck --no-age --text "A short note https://news.example/story?utm_campaign=a1b2c3d4&utm_medium=social"
```

Exit code 1. `a1b2c3d4` is an opaque campaign code. `utm_medium=social` stays INFO.

```text
Verdict: WARN
What would let someone group this draft with others:
  - 'utm_campaign' carries an opaque code (a1b2c3d4) that can group this post with others using the same value
Reasons:
  [WARN] campaign_code: 'utm_campaign' carries an opaque code (a1b2c3d4) that can group this post with others using the same value
  [INFO] utm_params: Plain UTM parameters present (often benign): utm_medium
  [INFO] clean_url_suggestion: Suggested clean link (tracking stripped): https://news.example/story
```

Post `https://news.example/story` instead, then run the check again.

## BLOCK: a host you forbade

`my-blocklist.txt`:

```text
track.example
```

```bash
linkcheck --no-age --blocklist my-blocklist.txt \
  --text "See https://track.example/c/?cid=poster1&utm_campaign=a1b2c3d4"
```

Exit code 2. The block wins even though the host never answered.

```text
Verdict: BLOCK
What would let someone group this draft with others:
  - Hop domain 'track.example' is on the blocklist (track.example)
  - 'utm_campaign' carries an opaque code (a1b2c3d4) that can group this post with others using the same value
  - Identifying tracking parameter 'cid' on URL
Reasons:
  [BLOCK] blocklisted_hop: Hop domain 'track.example' is on the blocklist (track.example)
  [WARN] campaign_code: 'utm_campaign' carries an opaque code (a1b2c3d4) that can group this post with others using the same value
  [WARN] tracking_param: Identifying tracking parameter 'cid' on URL
  [INFO] clean_url_suggestion: Suggested clean link (tracking stripped): https://track.example/c/
```

Do not post this draft. Remove the link.

## Same sentence across accounts

`data/phrases.txt`:

```text
the same sentence is posted by each account in this example
```

`data/corpus.jsonl` (three accounts, one code):

```json
{"account": "account_a", "text": "The same sentence is posted by each account in this example.", "created_at": "2026-11-17T12:00:00Z", "urls": ["https://news.example/story?utm_campaign=a1b2c3d4"]}
{"account": "account_b", "text": "The same sentence is posted by each account in this example.", "created_at": "2026-11-17T12:00:00Z", "urls": ["https://news.example/story?utm_campaign=a1b2c3d4"]}
{"account": "account_c", "text": "The same sentence is posted by each account in this example.", "created_at": "2026-11-17T12:00:00Z", "urls": ["https://news.example/story?utm_campaign=a1b2c3d4"]}
```

```bash
linkcheck --no-age \
  --text "The same sentence is posted by each account in this example. https://news.example/story?utm_campaign=a1b2c3d4"
```

Expect WARN for the phrase, for the near-duplicate wording, and for the shared code `utm_campaign=a1b2c3d4`. Details of those codes are in [guide.md](guide.md).

## JSON for a bot

```bash
linkcheck --json --no-age --text "A short note https://news.example/story?utm_campaign=spring"
```

Read `verdict` and `exit_code`. The field list is [schema.md](schema.md).

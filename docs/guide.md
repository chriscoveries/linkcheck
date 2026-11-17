# Using linkcheck

linkcheck reads a draft before it is posted. It pulls every link out of the text, follows each redirect hop, and looks for anything an outsider could use to group this draft with other accounts: a hidden hop host, a shared code in the URL, or a sentence that already appears across other accounts. It then suggests the same destination with those tracking keys removed.

It does not decide whether a post is an advertisement. A clear verdict means "this draft is not carrying that kind of join key." It does not mean the page at the end of the link is trustworthy.

The pictures and the story of how the leak works are in [problem.md](problem.md). The JSON a bot should parse is in [schema.md](schema.md). Worked command output is in [examples.md](examples.md).

## Install

The repo is private. Install it from a checkout you can already read:

```bash
pip install -e ".[dev]"
```

Or, with credentials that can read the repo:

```bash
pip install "git+https://github.com/chriscoveries/linkcheck.git"
```

Python 3.10 or newer. The only required library is `requests`. Domain age can fall back to a WHOIS lookup if `python-whois` is installed (`pip install -e ".[whois]"`). If that package is missing, a failed age lookup is reported and the rest of the check still runs.

Check that the command is on your path:

```bash
linkcheck --version
```

## Check one draft

Pass the exact text that would be posted.

```bash
linkcheck --text "A note https://news.example/story"
```

Other ways to feed it:

```bash
linkcheck --file draft.txt
printf '%s' "draft text" | linkcheck --stdin
linkcheck https://news.example/story
linkcheck --json --text "draft text https://news.example/story"
```

`--json` prints the machine-readable report and no other prose. Without it, you get a short human report. The process exit code matches the verdict either way.

| Exit | Verdict | Meaning |
| --- | --- | --- |
| 0 | OK | Nothing linkable was found. INFO notes may still be present. |
| 1 | WARN | Something could group this draft with others. Read it before posting. |
| 2 | BLOCK | A hop host is on your blocklist. Do not post this draft as-is. |

INFO never raises the verdict by itself. One WARN anywhere makes the whole draft WARN. One BLOCK makes it BLOCK, even if other findings are only warnings.

## How to read the human report

The report has three parts.

1. **Verdict.** The single word to act on: OK, WARN, or BLOCK.
2. **What would let someone group this draft with others.** Present only when there is a real join key. Each bullet is one reason, in plain language.
3. **Reasons.** Every finding, including INFO, as `[SEVERITY] code: message`.
4. **One block per URL.** The hop chain in order, then a clean link with tracking keys removed.

A hop line looks like:

```text
0. [302] https://short.example/ab12 location
1. [200] https://news.example/story final
```

`302` plus `location` means an HTTP redirect. `200` plus `final` means the chain stopped. `meta-refresh` and `js` mean the next URL was found in the page itself (a refresh tag, or a simple `location` assignment). `-` plus `error` means that hop could not be fetched. The URL is still recorded, so a blocklist hit or a code in that URL still counts.

The chain stops after 10 hops, on a loop, or when a hop returns a page with no further redirect.

## What each code means

| Code | Severity | What it is telling you |
| --- | --- | --- |
| `blocklisted_hop` | BLOCK | This host is in your blocklist. You already decided it should never appear in a chain. |
| `intermediate_hop` | WARN | A hop in the middle is neither a known short-link host nor the final page. That is the shape of a hidden tracker hop. |
| `campaign_code` | WARN | A `utm_*` value is an opaque token (8 hex characters, or a long random token), not an ordinary word. The same token on other posts is enough to cluster them. |
| `tracking_param` | WARN | A query key such as `cid`, `creator`, `campaign`, `aff`, `subid`, or `clickid`. |
| `tracking_token` | WARN | Some other query value looks like an opaque token. |
| `young_domain` | WARN | The host was registered less than about 90 days ago. A replacement tracker host often looks like this. |
| `domain_age_unknown` | INFO | The age lookup failed or returned nothing. The check did not guess. |
| `utm_params` | INFO | Ordinary word-like `utm_*` values, such as `utm_medium=social`. Common, and not by themselves a shared code. |
| `clean_url_suggestion` | INFO | The same destination with tracking keys stripped. This is a suggestion, not a rewrite. |
| `script_phrase` | WARN | The draft contains a line from `data/phrases.txt`. |
| `script_near_duplicate` | WARN | The wording is very close (similarity at least 0.85) to posts by 3 or more other accounts in the lookback window. |
| `shared_tracking_code` | WARN | A code in this draft also appears on posts by 3 or more other accounts in the corpus. |

Allowlisted hosts skip the intermediate-hop and age warnings. A blocklist hit still wins: if you put a host on both lists, treat the blocklist as the one that matters and do not list it in both.

## What to do with the verdict

**OK.** The draft does not carry a join key the tool knows about. You can post it. If a clean link was suggested, you may still prefer it.

**WARN.** Do not post yet. Read the grouping bullets. The usual fix is to replace the link with the clean URL and, if a phrase or near-duplicate fired, rewrite the sentence in your own words. Run the check again on the revised draft. Post only when you have read the reasons and still want this text.

**BLOCK.** Do not post. A host you listed as forbidden is in the chain. Remove that link. Adding a disclosure tag does not clear a block.

The tool never edits the draft for you.

## Flags

| Flag | Effect |
| --- | --- |
| `--text`, `-t` | Draft text on the command line. |
| `--file`, `-f` | Read the draft from a file. |
| `--stdin` | Read the draft from stdin. Also the default when stdin is a pipe and you passed no text. |
| URL arguments | Extra URLs to check. If you pass only URLs, they are the draft. |
| `--json` | JSON only. See [schema.md](schema.md). |
| `--blocklist PATH` | Use this blocklist instead of `data/blocklist.txt`. |
| `--allowlist PATH` | Use this allowlist instead of `data/allowlist.txt`. |
| `--shorteners PATH` | Hosts that only shorten links. |
| `--phrases PATH` | Shared lines, one per line. |
| `--corpus PATH` | JSONL of other accounts' recent posts. |
| `--no-age` | Skip the registration-age lookup. Useful offline. |
| `--version` | Print the version and exit. |

`linkcheck monitor` is separate. See below.

## Files

All of these live in `data/` when you run from a checkout. Lines starting with `#` are comments. Blank lines are ignored. Hostnames are matched without a leading `www.`, and a listed host also matches its subdomains.

### `blocklist.txt`

Hosts that must not appear on any hop. The file ships empty. One host per line:

```text
track.example
go.track.example
```

A hit is BLOCK, including when the fetch itself fails. You do not need the host to be up.

### `allowlist.txt`

Your own sites and other hosts you have decided are not a hidden hop. A match skips intermediate-hop and age warnings for that host. It does not strip codes from the URL. A `cid` on an allowlisted host is still WARN.

### `shorteners.txt`

Hosts whose only job is to shorten a link. An intermediate hop on one of these is expected and is not WARN. The final page is never treated as a shortener. The file ships with a list of public short-link hosts so an ordinary short link is not flagged just for existing.

### `phrases.txt`

One shared sentence per line. Matching is case-insensitive, after links, @-mentions, and #tags are removed and whitespace is collapsed. A hit is WARN (`script_phrase`). Put a line here when you already know that exact wording is being reused.

### `corpus.jsonl`

One JSON object per line. Posts older than 14 days are ignored. Each row needs an account and text:

```json
{"account": "account_a", "text": "The same sentence is posted by each account in this example.", "created_at": "2026-11-17T12:00:00Z", "urls": ["https://news.example/story?utm_campaign=a1b2c3d4"]}
```

| Field | Required | Role |
| --- | --- | --- |
| `account` (or `username` or `author`) | yes | Who posted it. A leading `@` is stripped. |
| `text` (or `full_text`) | yes | The post body. |
| `created_at` (or `date`) | no | ISO-8601 or `YYYY-MM-DD`. Missing dates are kept. |
| `urls` | no | Links already expanded, used for shared-code checks. |
| `id` | no | Your own identifier. Not used in the verdict. |

Near-duplicate wording compares the draft to each row with shingles and with TF-IDF cosine, and keeps the higher score. Scores are grouped by account, so five posts from one account count as one account. WARN needs a score of at least 0.85 against at least 3 different accounts.

Shared codes use the same rule: the same key and value on at least 3 other accounts.

`scripts/fetch_corpus.py` can refill this file from recent posts when `X_BEARER_TOKEN` is set:

```bash
python scripts/fetch_corpus.py --user-id 123 --user-id 456 --out data/corpus.jsonl
```

The account field written by that script is the numeric user id you passed, not a display name.

## The clean link

Tracking keys removed from the suggestion are:

`cid`, `creator`, `campaign`, `aff`, `affiliate`, `subid`, `sub_id`, `clickid`, `click_id`, `cb`, `ref_id`, `partner_id`, `publisher_id`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content`, `utm_id`.

Anything else in the query string is kept. The fragment is dropped. The suggestion is the final URL when the chain completed, otherwise the input URL. Post the clean link only after you have looked at it. Stripping keys does not prove the path is the article you meant to share.

## Domain age

For each hop host that is not on the allowlist and not a known shortener, linkcheck asks the public registration-data service at `https://rdap.org/domain/<host>`. A registration date younger than 90 days is WARN. No date, an HTTP error, or a network error becomes INFO (`domain_age_unknown`) and does not fail the run. If `python-whois` is installed, it is tried after RDAP fails.

`--no-age` skips this. Use it when you are offline or when you only care about codes and the blocklist.

## Posts that are already up

```bash
export X_BEARER_TOKEN=...
linkcheck monitor --user-id 123456789 --json
```

`X_BEARER_TOKEN` or `TWITTER_BEARER_TOKEN` must be set. `--user-id` is the numeric account id. The command fetches recent posts and runs the same checks with age lookups turned off. The JSON lists only posts that are WARN or BLOCK. Exit code 0 means none of them failed. Exit code 1 means a warning, a missing token, or an API error. Exit code 2 means at least one post was BLOCK.

This reviews the past. It is not a substitute for checking the draft first.

## Point a bot at this repo

A bot that can read this repo and run a shell command should follow [AGENTS.md](../AGENTS.md). A bot that loads a skill file should follow [SKILL.md](../SKILL.md).

The instruction to give it:

> This repo is linkcheck. Install it with `pip install -e .` from the checkout. When I say "check my links in my twitter drafts before I post", run `linkcheck --json --text "<draft>"` on each draft and do not post it yourself. If the verdict is BLOCK, show me the reasons and stop. If WARN, show me the reasons and the suggested clean link, and wait until I explicitly say to post. If OK, tell me it is clear. Follow AGENTS.md and SKILL.md.

The bot should pass the draft as data, not assemble a shell command by pasting untrusted text into a double-quoted string. From a program, call `linkcheck.cli.main(["--json", "--text", draft])` or write the draft to a file and use `--file`.

## Limits

- Redirects that only happen inside a browser after scripts run will be missed, except for a simple `location` assignment or a meta refresh in the first chunk of HTML.
- Some hosts refuse the request. The hop is still listed, with the error. Codes and blocklist hits on that URL still count. Later hops that were never reached do not.
- Age data is only as good as the public registration record.
- Shared wording and shared codes are only as good as `data/corpus.jsonl`. An empty corpus does not mean the sentence is unique.
- The default blocklist is empty. Until you add hosts, a tracker hop is WARN (`intermediate_hop`), not BLOCK.
- The clean link is a string transform. It does not fetch the page again to confirm it.

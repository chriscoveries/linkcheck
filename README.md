# linkcheck

This repo is for an agent. A person is not expected to read it or run it.

The agent starts with `AGENTS.md`, then `linkcheck runtime --json`, then the playbook for the job. It can audit the published influencer campaign dataset, match an operator's post IDs, or inspect draft links before an authorized publication.

A short link can pass through a hidden hop that adds a code shared with other accounts. linkcheck follows the hops and reports OK, WARN, or BLOCK.

Shortened links can carry shared tracking codes through redirect hops. Those associations support further investigation. Establishing who paid for a post, who authored it, or whether accounts coordinated requires additional evidence. The dataset tools retain the original records and disclosure flags so those questions can be checked.

The pictures in [docs/problem.md](docs/problem.md) use only placeholder hosts (`short.example`, `track.example`, `news.example`) and unnamed accounts. They are not copies of anyone's posts.

## Point this repo at your bot

Copy-paste this to your bot:

> Use https://github.com/chriscoveries/linkcheck to audit my account's inclusion in the influencer campaign dataset. Read AGENTS.md, install the tool, run `linkcheck runtime --json`, and follow `find-own-posts`. Ask for my handle if you need it. Show the exact source rows and post URLs. You may use my already-authorized X connector, browser, or archive to verify the returned posts; preserve disclosures and report access gaps. Keep private imports local. Do not edit or publish posts.

For a broader audit, ask the agent to follow `explore-dataset`. It can prepare the entire snapshot and sort it by account, topic, date, disclosure flag, publisher, or destination group.

## Dataset audit

```bash
linkcheck dataset account --handle JackPosobiec --json
linkcheck dataset prepare --output ./audit-snapshot --json
linkcheck dataset counts --source ./audit-snapshot/raw/all.json --json
linkcheck dataset accounts --source ./audit-snapshot/raw/all.json --sort posts --desc --all --json
linkcheck dataset accounts --source ./audit-snapshot/raw/all.json --min-posts 1 --max-posts 1 --all --format csv
linkcheck dataset posts --source ./audit-snapshot/raw/all.json --category ai --sort date --desc --all --json
linkcheck dataset match --source ./audit-snapshot/raw/all.json --posts-file ./my-posts.json --json
```

Preparation creates exact source JSON, an indexed SQLite database, four CSV tables, a zero/one-post inventory, and a manifest with file hashes. It refuses an existing output directory. Keep generated data outside version control. Matching reads exact IDs from X API responses, archive `tweets.js`, JSON, or JSONL; it reads no credentials and does not fetch a timeline itself.

Every query identifies the source SHA-256 and the zero-based source rows. Filters have an explicit scope and report pagination. Default query limit is 100; `--all` returns every result. The source contains X post IDs and metadata, with no original post text. Errors cannot produce a successful zero-post count. See [dataset schema and examples](docs/dataset.md).

## How the leak happens

1. A draft contains only a short link.
2. That short link does not open the article. It 302s through a hidden hop on some other host.
3. The hop URL carries ID codes (creator, campaign, click, or an opaque token such as eight hex characters). The same code is reused across many accounts.
4. The reader lands on the article. The hop and the codes are already in the chain, so anyone who traces redirects can group the posts. Near-identical wording makes the group obvious.
5. When one tracker host is noticed, a new host can be registered and pointed at the same way, with the same code shape. A very new intermediate domain is a signal by itself.

```
short link  →  hidden hop ?utm_campaign=<shared code>  →  article
```

![Hop chain](docs/figures/01-hop-chain.svg)

![Shared wording](docs/figures/02-shared-wording.svg)

## What linkcheck checks

![What the tool reports](docs/figures/03-what-linkcheck-sees.svg)

| Check | Result |
| --- | --- |
| A hop host is on your blocklist | **BLOCK** |
| An intermediate hop is neither a known shortener nor the destination | **WARN** |
| Identifying query params (`cid`, `creator`, `campaign`, `aff`, `subid`, `clickid`, …) or opaque tokens | **WARN** |
| An opaque code hiding in `utm_*` (for example 8 hex characters) | **WARN** |
| Ordinary word-like `utm_*` values | **INFO** |
| A hop domain younger than about 90 days (lookup fails soft) | **WARN** |
| Near-duplicate wording, a known shared phrase, or the same code on 3+ other accounts in 14 days | **WARN** |
| A clean link with those tracking keys removed | **INFO** (suggestion) |

## Documentation

| Doc | What it is |
| --- | --- |
| [docs/guide.md](docs/guide.md) | Install, every flag, how to read a report, config files, corpus, clean links, already-posted checks |
| [docs/examples.md](docs/examples.md) | OK, WARN, and BLOCK runs with the output |
| [docs/problem.md](docs/problem.md) | Why a short link can group accounts, with placeholder figures |
| [docs/schema.md](docs/schema.md) | `--json` fields for a bot |
| [docs/dataset.md](docs/dataset.md) | Source joins, filters, exact-ID matching, SQLite, and evidence limits |
| [AGENTS.md](AGENTS.md) | Instructions for any bot that can run a shell command |
| [SKILL.md](SKILL.md) | Legacy draft-check skill; dataset audits start with `AGENTS.md` and runtime |

## Install

From a checkout of this repo:

```bash
pip install -e ".[dev]"
```

From the public repo:

```bash
pip install "git+https://github.com/chriscoveries/linkcheck.git"
```

## Usage

```bash
linkcheck --text "A note https://news.example/story?utm_campaign=a1b2c3d4"
linkcheck --json --text "Draft with https://short.example/ab12"
printf '%s' "draft text" | linkcheck --stdin
```

Draft exit codes: `0` clear, `1` warn, `2` block. Dataset commands: `0` complete for this snapshot, `1` account not listed, `2` invalid or unavailable. JSON shapes: [draft checks](docs/schema.md), [dataset audit](docs/dataset.md).

### Files you edit

- `data/blocklist.txt` — hosts that must never appear in a hop (ships empty)
- `data/allowlist.txt` — your own sites
- `data/shorteners.txt` — hosts that only shorten links
- `data/phrases.txt` — shared lines you already know
- `data/corpus.jsonl` — recent posts by other accounts, so shared codes and wording can be seen

### Already-posted check

This checks links in one page of recent posts. To find posts in the published campaign dataset, use `dataset account` or `dataset match`.

```bash
export X_BEARER_TOKEN=...
linkcheck monitor --user-id <id> --json
```

## Tests

```bash
pytest -q
```

After editing canonical `playbooks/`, run `python scripts/sync_playbooks.py` before building. Tests require packaged playbooks to match so `runtime` works from an installed wheel outside a checkout.

## Limitations

- Tracing needs the network. Some hops only run in a browser.
- Age lookups sometimes have no public answer. That is reported, not treated as a failure.
- Shared-wording checks only see the corpus you give them.
- The clean link drops known tracking keys. It does not prove the page is the one you meant.
- The blocklist starts empty. Add tracker hosts you want to hard-fail.

## License

MIT

# Purpose

`linkcheck` inspects draft links and audits records in the public influencer campaign dataset. A draft check follows redirects and reports tracking fields. Dataset queries decode indexed source rows, preserve their provenance, and help an operator locate their own posts using authorized access.

The draft checker reports link signals. Dataset disclosure flags retain the publisher's labels. Verifying sponsorship, payment, original wording, or authorship requires evidence beyond either output. Link cleanup must preserve disclosures.

## Finding the evidence in the dataset

The explorer publishes `https://influencer-campaign-explorer.com/data/all.json`. A post is a compact array joined to account and destination-group arrays by zero-based indices:

```json
["1595055431763779584", 112, 1120, "2022-11-22", 8, null]
```

In the snapshot built `2026-11-15 18:55 UTC`, this is `/posts/979`. `/accounts/112` identifies `JackPosobiec`; `/campaigns/1120` supplies the linked page. The raw byte SHA-256 is `dc992ff337646c0e36409559935e7c28fbadf4d27ac2ad6e1e4eed8116f1ea3c`. That account has 15 distinct post rows across nine destination groups in this snapshot. A text search for the handle inside `posts` misses the numeric join.

Use `linkcheck dataset account --handle JackPosobiec --json` to decode those joins and `dataset counts` for the complete zero/one-post inventory. Pin `--source` when reproducing a result. `dataset prepare` creates SQLite and CSV tables for the rest of the data. [Full schema and workflow](dataset.md).

Counts distinguish an absent handle, a listed account with zero rows, an unavailable source, and a filtered query with no matches. Original post text and redirect chains are absent from this JSON. The publisher's snapshot also has no guarantee of exhaustive collection.

# The problem, in general terms

Shortened links can pass through redirect hops that attach tracking codes. Shared hosts, codes, or wording can identify clusters worth investigating. A copied link, syndication, or an ordinary analytics campaign can create similar patterns, so a cluster by itself leaves coordination and payment unresolved.

The figures below are placeholders. They are not copies of anyone's posts, and they do not name accounts, outlets, or tracker hosts.

## How the leak happens

![Short link, hidden hop, destination](figures/01-hop-chain.svg)

1. The draft contains only a short link, such as `short.example/ab12`.
2. A public shortener lookup shows an intermediate host, `track.example`, with query tags. An opaque code such as `utm_campaign=a1b2c3d4` can be compared across links. Its meaning needs documentation or independent evidence.
3. `track.example` answers with a 302. The browser lands on `news.example/story`, now decorated with further tags (`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`). The reader sees the article. The hop and the code are already in the chain.
4. After a tracker host becomes known, a replacement host can be registered and pointed the same way, with the same code shape, on a very short timeline. A young intermediate domain is itself a signal.
5. Some links carry an opaque code directly on the destination URL. That field can group records for inspection while leaving the relationship between accounts unresolved.

## Comparing wording

![Three accounts, one sentence](figures/02-shared-wording.svg)

A shared sentence can supply another comparison when original post text is available. The explorer JSON omits that text, so wording claims need a separately retrieved and attributed source.

## What linkcheck checks

![Checks mapped onto the chain](figures/03-what-linkcheck-sees.svg)

| What it sees | Verdict |
| --- | --- |
| A hop whose host is on your blocklist | BLOCK |
| An intermediate host that is neither a known shortener nor the destination | WARN |
| An opaque code in the query string, including an 8-hex value hiding in `utm_campaign` | WARN |
| Ordinary word-like `utm_*` values (`utm_medium=cpc`) | INFO |
| A hop domain younger than about 90 days | WARN |
| The same code, or near-identical wording, on posts by three or more other accounts in the last 14 days | WARN |
| A clean URL with those tracking keys removed | INFO (suggestion) |

The default blocklist ships empty. Add hosts you never want in a hop chain, one per line, in `data/blocklist.txt`.

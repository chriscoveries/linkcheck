# Dataset audit and offline workspace

`linkcheck dataset` reads the complete supplied explorer JSON, validates its internal joins, and returns reproducible results. The default source is `https://influencer-campaign-explorer.com/data/all.json`. Add `--source <file-or-public-url>` to pin another snapshot. Only HTTP(S) public hosts and local files are accepted; source retrieval sends no account credentials.

## Source schema

| Record | Meaning |
| --- | --- |
| `accounts[i]` | Account metadata; `h` is the X handle |
| `campaigns[j]` | A destination group, with `id`, `cat`, `title`, `pub`, `url`, counts and dates |
| `cats[k]` | Topic ID and label |
| `posts[n]` | `[post_id, account_index, campaign_index, date, flags, views, optional_archive_url]` |

IDs remain strings. A post's `source_pointer`, `account_pointer`, and `campaign_pointer` refer to the zero-based arrays in the unmodified source. Each result includes its SHA-256, byte count, source label, retrieval time, and publisher build timestamp. Optional metadata and the raw row remain available for inspection.

Flags preserve the site's meanings: bit 8 is a recorded advertising disclosure; bit 2 marks a post the site labels deleted/unretrievable; bit 4 marks private. Other bits are exposed as `uninterpreted_flags`. These are historical publisher labels. Lack of an ad label leaves payment unresolved. Current availability requires a new check.

The loader rejects malformed/truncated JSON, duplicate IDs, broken references, unsafe numeric IDs, invalid dates, and disagreement with declared destination-group counts or date ranges. Successful validation checks internal consistency, not the publisher's collection completeness or the truth of its attribution.

## Commands and scope

| Command | Output |
| --- | --- |
| `dataset account --handle <handle>` | Every row joined to that indexed account, without query pagination |
| `dataset counts` | All listed accounts with zero or exactly one distinct ID; sole-post evidence for each one-post account |
| `dataset posts` | Filtered post records |
| `dataset accounts` | Recomputed account aggregates |
| `dataset campaigns` | Recomputed destination-group aggregates |
| `dataset match --posts-file <file>` | Exact-ID membership and supplied-author/date comparisons |
| `dataset prepare --output <new-directory>` | Complete local snapshot, SQLite, CSVs, count report and hash manifest |

Use `--json` for agent results. Query commands default to 100 rows, with `--all`, `--limit` and `--offset` controlling pagination. Output states `total_matched` and `returned_count`; JSON always identifies filters and sort order. `--format csv` emits selected rows to stdout and a metadata summary to stderr. Retain that summary for provenance. CSV formula-like cells and long numeric IDs receive a leading apostrophe; JSON/SQLite retain exact values.

`posts`, `accounts` and `campaigns` accept `--handle`, `--category`, `--campaign`, `--search`, `--since`, `--until`, `--ad any|labelled|unlabelled`, and `--availability all|available|deleted|private|unavailable`. Dates are inclusive. Handle, topic and group selectors are exact and case-insensitive; unknown selectors raise an error. Search is literal and case-insensitive across published metadata, including titles and destinations. Original post wording is absent.

Aggregate `post_count` values use the selected rows. `total_post_count` retains each group's unfiltered count. Unfiltered queries include indexed zero-post accounts. Filters remove groups with no selected rows; use `counts` for the global zero/one inventory. `--min-posts` and `--max-posts` apply to recomputed counts.

Sort fields are shown by each command's `--help`. `--desc` reverses values while missing values stay last; ties have a stable order. Campaign `--sort date` means its latest selected post date. View totals use recorded numeric values only, with `views_known_count` exposing coverage.

Dataset exit codes differ from draft verdicts: `0` means query complete for the supplied snapshot, `1` means a requested account is absent from the account index, and `2` means invalid input or unavailable data. A missing handle is never returned as a listed zero-post account. Failure does not establish absence.

## Bring your own authorized access

An agent can first query a handle without X access. To compare original posts it uses the operator's existing API, connector, browser, or account archive through its intended interface. The tool itself neither signs in nor reads tokens or cookies. Keep private reference files outside the repository and preserve disclosures.

```json
[
  {"id":"1595055431763779584","author_handle":"JackPosobiec","date":"2022-11-22"},
  {"url":"https://x.com/JackPosobiec/status/1589654913734578176"}
]
```

Imports support JSON/JSONL, X API `data` lists or objects with optional `includes.users`, and X archive `tweets.js` assignments. Archives are parsed without executing JavaScript. The import retains IDs, optional author/date evidence and source pointers; it omits text and credentials. JavaScript-unsafe numeric IDs are rejected unless an exact string ID is also supplied.

Exact matching reports `matched`, `not_in_dataset`, and `skipped`. Other-platform references are skipped because this dataset uses X IDs. Duplicate IDs count once, while supplied conflicting author/date evidence is retained. A URL's handle is a routing label rather than independent author verification. API pagination is reported as incomplete coverage; supplied references never establish complete account history. Access errors stay unresolved.

## Offline files

`prepare` refuses every existing output path and writes `manifest.json` last. Its files are:

- `raw/all.json`: exact source bytes.
- `dataset.sqlite`: accounts, campaigns, posts, categories and metadata, with indexed joins and a `post_details` view.
- `accounts.csv`, `campaigns.csv`, `posts.csv`, `categories.csv`: normalized rows with source pointers.
- `account-counts.json`: the zero/one inventory including sole-post records.
- `manifest.json`: source metadata, counts, file hashes, CSV conventions and SQL examples.

Open SQLite read-only, for example using a `file:.../dataset.sqlite?mode=ro` URI. Useful queries:

```sql
SELECT handle, post_count
FROM accounts
ORDER BY post_count DESC, handle;

SELECT handle, post_id, post_date, source_pointer
FROM post_details
WHERE handle IN (SELECT handle FROM accounts WHERE post_count = 1)
ORDER BY handle;

SELECT post_id, post_date, campaign_title, source_pointer
FROM post_details
WHERE handle = 'JackPosobiec' COLLATE NOCASE
ORDER BY post_date, post_id;

SELECT category, COUNT(*) AS post_count,
       COUNT(DISTINCT account_index) AS account_count
FROM post_details
GROUP BY category
ORDER BY post_count DESC;
```

The workspace contains the publisher's public snapshot only. It contains no imported private post text or access credentials. Keep a private audit workspace until publication is explicitly authorized. Dataset membership alone leaves payment, coordination, author identity and original wording unverified.

# explore-dataset

Prepare and query the public snapshot. This workflow reads existing published records and performs no live account collection.

```bash
linkcheck dataset prepare --output ./audit-snapshot --json
linkcheck dataset counts --source ./audit-snapshot/raw/all.json --json
linkcheck dataset accounts --source ./audit-snapshot/raw/all.json --sort posts --desc --all --json
linkcheck dataset accounts --source ./audit-snapshot/raw/all.json --min-posts 1 --max-posts 1 --sort handle --all --json
linkcheck dataset posts --source ./audit-snapshot/raw/all.json --category ai --since 2025-01-01 --sort date --desc --all --json
linkcheck dataset campaigns --source ./audit-snapshot/raw/all.json --search nvidia --sort accounts --desc --all --json
```

Use a new local directory. Preparation refuses existing paths and writes a completion manifest last. Preserve `raw/all.json`; all source pointers refer to those bytes. The workspace contains SQLite, CSV tables, exact-count reports, and hashes. Keep it private unless the user explicitly authorizes publication.

Filters include exact handle, topic ID, destination-group ID, literal metadata search, inclusive dates, disclosure flag, and recorded availability flag. `--search` cannot search original post wording because the source omits it. Default query output is 100 rows; use `--all` or paginate with `--offset`. JSON states the number matched and returned.

Account and destination-group counts are recomputed after filters. `total_post_count` retains the full-snapshot count. An unfiltered account query includes listed accounts with zero posts. A filtered query drops zero-match groups. For the global zero/one inventory use `dataset counts`, or an unfiltered account query with count bounds.

Sort options are listed by each command's `--help`; null values stay last. `--format csv` exports selected rows with spreadsheet escaping. JSON and SQLite retain exact IDs. CSV has no report envelope, so retain the snapshot manifest alongside it.

Dataset status `complete` means the supplied JSON passed structural and declared-count checks. It does not establish that the publisher collected all posts. Count post IDs, not destination cards. Preserve deleted/private-flagged records when counting dataset membership. Run `linkcheck runtime --schema dataset` for the bundled schema and SQL examples, also available in `docs/dataset.md` in a checkout.

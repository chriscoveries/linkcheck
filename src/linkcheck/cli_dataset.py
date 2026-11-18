"""Agent-facing, read-only dataset exploration commands."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import sys
from typing import Any

from .dataset import DEFAULT_DATASET_URL, DatasetError, load_dataset, load_post_references


def _source_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", "--dataset", default=DEFAULT_DATASET_URL,
                        help="Complete explorer JSON URL or local snapshot file")
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text")
    parser.add_argument("--json", action="store_const", const="json", dest="format",
                        help="Emit machine-readable JSON")


def _filter_options(parser: argparse.ArgumentParser, entity: str) -> None:
    parser.add_argument("--handle", help="Exact X handle (case-insensitive; @ optional)")
    parser.add_argument("--category", help="Exact topic ID, such as ai or immigration")
    parser.add_argument("--campaign", help="Exact destination-group ID")
    parser.add_argument("--search", help="Literal metadata search; post text is not in this dataset")
    parser.add_argument("--since", help="Inclusive start date, YYYY-MM-DD")
    parser.add_argument("--until", help="Inclusive end date, YYYY-MM-DD")
    parser.add_argument("--ad", choices=("any", "labelled", "unlabelled"), default="any",
                        help="Dataset disclosure flag; unlabelled does not mean unpaid")
    parser.add_argument("--availability", choices=("all", "available", "deleted", "private", "unavailable"), default="all",
                        help="Dataset flags, not a fresh availability check")
    from .explore import ACCOUNT_SORTS, CAMPAIGN_SORTS, POST_SORTS

    sorts = {"posts": POST_SORTS, "accounts": ACCOUNT_SORTS, "campaigns": CAMPAIGN_SORTS}[entity]
    parser.add_argument("--sort", choices=sorts, default="date" if entity == "posts" else "posts")
    parser.add_argument("--descending", "--desc", action="store_true")
    parser.add_argument("--limit", type=int, default=100, help="Maximum rows; default 100. Use --all for every row")
    parser.add_argument("--all", action="store_true", help="Return every matching row")
    parser.add_argument("--offset", type=int, default=0)
    if entity != "posts":
        parser.add_argument("--min-posts", type=int, help="Minimum posts after applying filters")
        parser.add_argument("--max-posts", type=int, help="Maximum posts after applying filters")


def add_dataset_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("dataset", help="Look up, sort and prepare the public campaign dataset")
    commands = parser.add_subparsers(dest="dataset_command", required=True)
    account = commands.add_parser("account", help="Decode every listed post for one handle")
    _source_options(account)
    account.add_argument("--handle", required=True)
    counts = commands.add_parser("counts", help="List every account with zero or exactly one distinct post")
    _source_options(counts)
    for entity in ("posts", "accounts", "campaigns"):
        query = commands.add_parser(entity, help=f"Filter and sort {entity}")
        _source_options(query)
        _filter_options(query, entity)
    match = commands.add_parser("match", help="Join IDs from your agent's authorized access or X archive")
    _source_options(match)
    match.add_argument("--posts-file", required=True, type=Path,
                       help="JSON, JSONL, or X archive tweets.js containing exact post IDs/URLs")
    prepare = commands.add_parser("prepare", help="Create an offline snapshot, SQLite database and CSV tables")
    _source_options(prepare)
    prepare.add_argument("--output", required=True, type=Path, help="New directory to create; existing paths are refused")


def _rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    if "rows" in report:
        return report["rows"]
    if "zero_post_accounts" in report:
        return [{**a, "post": a.get("post")} for a in report["zero_post_accounts"] + report["one_post_accounts"]]
    if "matched" in report:
        matched = [{**m["post"], "match_status": "matched", "author_check": m["author_check"],
                    "date_check": m["date_check"], "input_pointer": m["reference"]["source_pointer"]}
                   for m in report["matched"]]
        absent = [{"id": m["id"], "match_status": "not_in_dataset", "input_pointer": m["source_pointer"]}
                  for m in report["not_in_dataset"]]
        skipped = [{"id": m["reference"]["id"], "match_status": "skipped", "reason": m["reason"],
                    "input_pointer": m["reference"]["source_pointer"]} for m in report["skipped"]]
        return matched + absent + skipped
    if "output_dir" in report:
        return report["files"]
    return report.get("posts", [])


def _csv_cell(value: Any, *, text_id: bool = False) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str):
        trimmed = value
        while trimmed and (trimmed[0].isspace() or ord(trimmed[0]) < 32 or trimmed[0] == "\ufeff"):
            trimmed = trimmed[1:]
        if trimmed.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
        if value.isdigit() and (text_id or len(value) > 15):
            return "'" + value
    return value


def _emit(report: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if output_format == "csv":
        metadata = {key: value for key, value in report.items()
                    if key not in {"rows", "posts", "matched", "not_in_dataset", "skipped", "one_post_accounts", "zero_post_accounts", "files"}}
        metadata["csv_note"] = "Row-only export; retain this metadata. Formula-like cells and long IDs are apostrophe-escaped. JSON/SQLite retain exact values."
        print(json.dumps(metadata, ensure_ascii=False), file=sys.stderr)
        rows = _rows(report)
        columns = list(dict.fromkeys(key for row in rows for key in row))
        if not columns:
            columns = {"accounts": ["handle", "post_count", "source_pointer"],
                       "campaigns": ["id", "title", "post_count", "source_pointer"]}.get(
                           report.get("entity", "posts"), ["id", "handle", "date", "source_pointer"])
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: _csv_cell(value, text_id=key in {"id", "post_id", "campaign_id", "category_id"})
                          for key, value in row.items()} for row in rows)
        print(buffer.getvalue(), end="")
        return
    print(f"Status: {report['status']}")
    metadata = report.get("snapshot", report.get("provenance", {}))
    if metadata:
        print(f"Snapshot: {metadata.get('built', '')} | SHA-256 {metadata.get('sha256', '')}")
    if report.get("status") == "account_not_listed":
        print(f"@{report['requested_handle']} is absent from this snapshot's account index.")
        return
    if "output_dir" in report:
        print(f"Prepared: {report['output_dir']}")
        return
    if "zero_post_count" in report:
        print(f"Zero-post accounts: {report['zero_post_count']}; one-post accounts: {report['one_post_count']}")
    if "matched_count" in report:
        print(f"Exact matches: {report['matched_count']}; absent IDs: {report['not_in_dataset_count']}; skipped: {report['skipped_count']}")
    if "post_count" in report:
        print(f"Listed posts: {report['post_count']}; destination groups: {report.get('campaign_count', '')}")
    if "total_matched" in report:
        print(f"Rows: {report['returned_count']} of {report['total_matched']} matched (offset {report['offset']})")
    for row in _rows(report):
        if "match_status" in row:
            print(f"Match: {row['match_status']}  id={row.get('id', '')}  "
                  f"author={row.get('author_check', 'not_compared')}  date={row.get('date_check', 'not_compared')}"
                  + (f"  reason={row['reason']}" if row.get("reason") else ""))
            if row["match_status"] != "matched":
                continue
        if "date" in row and "id" in row:
            print(f"{row['date']}  @{row.get('handle', '')}  {row['id']}  {row.get('campaign_title', '')}")
            print(f"  {row.get('source_pointer', '')}  {row.get('url', '')}")
        else:
            identity = row.get("handle", row.get("id", ""))
            print(f"{identity}  posts={row.get('post_count', '')}  {row.get('title', row.get('name', ''))}")
    if report.get("interpretation"):
        print(report["interpretation"])
    if report.get("reference_coverage"):
        print("Reference coverage: " + json.dumps(report["reference_coverage"], ensure_ascii=False))
    if report.get("verification_note"):
        print(report["verification_note"])


def run_dataset_command(args: argparse.Namespace) -> int:
    try:
        snapshot = load_dataset(args.source)
        command = args.dataset_command
        if command == "account":
            report = snapshot.account_report(args.handle)
        elif command == "counts":
            report = snapshot.counts_report()
        elif command == "match":
            report = snapshot.match_posts(load_post_references(args.posts_file))
        elif command == "prepare":
            from .workspace import prepare_workspace

            report = prepare_workspace(snapshot, args.output)
        else:
            from .explore import query_accounts, query_campaigns, query_posts

            options = {key: getattr(args, key) for key in
                       ("handle", "category", "campaign", "search", "since", "until", "availability", "sort", "descending", "offset")}
            options["ad"] = None if args.ad == "any" else args.ad == "labelled"
            options["limit"] = None if args.all else args.limit
            if command != "posts":
                options.update(min_posts=args.min_posts, max_posts=args.max_posts)
            report = {"posts": query_posts, "accounts": query_accounts, "campaigns": query_campaigns}[command](snapshot, **options)
        _emit(report, args.format)
        return 1 if report["status"] == "account_not_listed" else 0
    except (DatasetError, OSError, ValueError) as exc:
        status = getattr(exc, "status", "error")
        exit_code = 1 if status == "account_not_listed" else 2
        error = {"schema_version": "1.0", "status": status,
                 "error": str(exc), "exit_code": exit_code,
                 "interpretation": "No zero-match or zero-post conclusion was established."}
        if args.format == "json":
            print(json.dumps(error, ensure_ascii=False, indent=2))
        else:
            print(f"Dataset query failed: {error['error']}", file=sys.stderr)
        return exit_code

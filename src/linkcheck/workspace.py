"""Prepare a local, traceable dataset workspace without fetching source posts.

Only the supplied explorer snapshot is exported.  X tokens, browser sessions,
own-post reference files and original post text are outside this module's scope.
The raw snapshot and SQLite retain exact values; the CSV copies add spreadsheet
escaping where needed and should not be used to reconstruct source bytes.
"""

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .dataset import DatasetError, DatasetSnapshot, parse_dataset


ACCOUNT_COLUMNS = (
    "account_index", "handle", "name", "followers", "gone", "post_count",
    "campaign_count", "labelled_ad_count", "deleted_count", "private_count",
    "first_date", "last_date", "source_pointer",
)
CAMPAIGN_COLUMNS = (
    "campaign_index", "campaign_id", "category", "title", "publisher",
    "destination_url", "published_date", "first_date", "last_date", "post_count",
    "account_count", "labelled_ad_count", "deleted_count", "private_count",
    "source_pointer",
)
POST_COLUMNS = (
    "id", "handle", "name", "date", "campaign_id", "campaign_title", "publisher",
    "category", "destination_url", "url", "archive_url", "flags", "labelled_as_ad",
    "deleted", "private", "uninterpreted_flags", "views", "account_index",
    "campaign_index", "source_pointer", "account_pointer", "campaign_pointer",
)
CATEGORY_COLUMNS = ("category_index", "category_id", "name", "source_pointer")


def _dump(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=indent)


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_integer(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _csv_cell(value: Any, *, text_id: bool = False) -> str:
    """Use apostrophe text escaping, including long IDs Excel would round."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    text = str(value)
    # Spreadsheet importers may discard whitespace, control characters or a
    # BOM before deciding whether a cell starts with a formula operator.
    offset = 0
    while offset < len(text) and (text[offset].isspace() or ord(text[offset]) < 32 or text[offset] == "\ufeff"):
        offset += 1
    trimmed = text[offset:]
    formula = bool(text) and (
        text[0] in "\t\r\n" or bool(trimmed) and trimmed[0] in "=+-@"
    )
    if formula or (text_id and text.isdecimal()):
        return "'" + text
    return text


def _write_csv(path: Path, columns: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                column: _csv_cell(row.get(column), text_id=column in {"id", "campaign_id", "category_id"})
                for column in columns
            })


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_dump(value, indent=2) + "\n")


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [row["date"] for row in rows]
    return {
        "post_count": len(rows),
        "labelled_ad_count": sum(row["labelled_as_ad"] for row in rows),
        "deleted_count": sum(row["deleted"] for row in rows),
        "private_count": sum(row["private"] for row in rows),
        "first_date": min(dates, default=None),
        "last_date": max(dates, default=None),
    }


def _normalized_rows(snapshot: DatasetSnapshot) -> dict[str, list[dict[str, Any]]]:
    posts = [snapshot.post_record(i) for i in range(len(snapshot.data["posts"]))]
    by_account: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_campaign: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        by_account[post["account_index"]].append(post)
        by_campaign[post["campaign_index"]].append(post)
    accounts = []
    for index, account in enumerate(snapshot.data["accounts"]):
        rows = by_account[index]
        accounts.append({
            "account_index": index, "handle": account["h"],
            "name": _string(account.get("name")),
            "followers": _optional_integer(account.get("fol")),
            "gone": _optional_integer(account.get("gone")),
            "campaign_count": len({row["campaign_index"] for row in rows}),
            "source_pointer": f"/accounts/{index}", "raw_json": _dump(account),
            **_summary(rows),
        })
    campaigns = []
    for index, campaign in enumerate(snapshot.data["campaigns"]):
        rows = by_campaign[index]
        campaigns.append({
            "campaign_index": index, "campaign_id": campaign["id"],
            "category": campaign["cat"], "title": _string(campaign.get("title")),
            "publisher": _string(campaign.get("pub")),
            "destination_url": _string(campaign.get("url")),
            "published_date": _string(campaign.get("date")),
            "account_count": len({row["account_index"] for row in rows}),
            "source_pointer": f"/campaigns/{index}", "raw_json": _dump(campaign),
            **_summary(rows),
        })
    categories = [
        {"category_index": i, "category_id": category["id"],
         "name": _string(category.get("name")), "source_pointer": f"/cats/{i}",
         "raw_json": _dump(category)}
        for i, category in enumerate(snapshot.data["cats"])
    ]
    return {"posts": posts, "accounts": accounts, "campaigns": campaigns, "categories": categories}


_SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA user_version = 1;
CREATE TABLE meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE categories (
  category_index INTEGER PRIMARY KEY, category_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL, source_pointer TEXT NOT NULL, raw_json TEXT NOT NULL
);
CREATE TABLE accounts (
  account_index INTEGER PRIMARY KEY, handle TEXT NOT NULL COLLATE NOCASE UNIQUE,
  name TEXT NOT NULL, followers INTEGER, gone INTEGER,
  post_count INTEGER NOT NULL, campaign_count INTEGER NOT NULL,
  labelled_ad_count INTEGER NOT NULL, deleted_count INTEGER NOT NULL,
  private_count INTEGER NOT NULL, first_date TEXT, last_date TEXT,
  source_pointer TEXT NOT NULL, raw_json TEXT NOT NULL
);
CREATE TABLE campaigns (
  campaign_index INTEGER PRIMARY KEY, campaign_id TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL REFERENCES categories(category_id), title TEXT NOT NULL,
  publisher TEXT NOT NULL, destination_url TEXT NOT NULL, published_date TEXT NOT NULL,
  first_date TEXT, last_date TEXT, post_count INTEGER NOT NULL, account_count INTEGER NOT NULL,
  labelled_ad_count INTEGER NOT NULL, deleted_count INTEGER NOT NULL,
  private_count INTEGER NOT NULL, source_pointer TEXT NOT NULL, raw_json TEXT NOT NULL
);
CREATE TABLE posts (
  post_id TEXT PRIMARY KEY, source_index INTEGER NOT NULL UNIQUE,
  account_index INTEGER NOT NULL REFERENCES accounts(account_index),
  campaign_index INTEGER NOT NULL REFERENCES campaigns(campaign_index),
  post_date TEXT NOT NULL, flags INTEGER NOT NULL,
  labelled_as_ad INTEGER NOT NULL CHECK (labelled_as_ad IN (0, 1)),
  deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
  private INTEGER NOT NULL CHECK (private IN (0, 1)),
  uninterpreted_flags INTEGER NOT NULL, views INTEGER,
  archive_url TEXT, post_url TEXT NOT NULL, source_pointer TEXT NOT NULL,
  raw_json TEXT NOT NULL
);
CREATE INDEX idx_posts_account_date ON posts(account_index, post_date);
CREATE INDEX idx_posts_campaign_date ON posts(campaign_index, post_date);
CREATE INDEX idx_posts_date ON posts(post_date, post_id);
CREATE INDEX idx_posts_ad_date ON posts(labelled_as_ad, post_date);
CREATE INDEX idx_posts_availability ON posts(deleted, private, post_date);
CREATE INDEX idx_accounts_post_count ON accounts(post_count, handle);
CREATE INDEX idx_campaigns_category ON campaigns(category);
CREATE INDEX idx_campaigns_publisher ON campaigns(publisher);
CREATE INDEX idx_campaigns_post_count ON campaigns(post_count, campaign_id);
CREATE VIEW post_details AS
SELECT p.post_id, a.handle, a.name, p.post_date, c.campaign_id,
       c.title AS campaign_title, c.publisher, c.category, c.destination_url,
       p.post_url, p.archive_url, p.flags, p.labelled_as_ad, p.deleted, p.private,
       p.uninterpreted_flags, p.views, p.account_index, p.campaign_index,
       p.source_pointer, a.source_pointer AS account_pointer,
       c.source_pointer AS campaign_pointer
FROM posts AS p JOIN accounts AS a ON p.account_index = a.account_index
JOIN campaigns AS c ON p.campaign_index = c.campaign_index;
"""


def _write_database(path: Path, snapshot: DatasetSnapshot, rows: dict[str, list[dict[str, Any]]]) -> None:
    # Reserve this filename exclusively before SQLite opens it.
    with path.open("xb"):
        pass
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        with connection:
            connection.execute("INSERT INTO meta VALUES (?, ?)", ("snapshot", _dump(snapshot.metadata())))
            connection.execute("INSERT INTO meta VALUES (?, ?)", ("count_unit", _dump("distinct post IDs, including deleted/private flags")))
            connection.execute("INSERT INTO meta VALUES (?, ?)", ("interpretation", _dump("Dataset inclusion is not proof of payment. Source post text is not included.")))
            for table, columns in (("categories", CATEGORY_COLUMNS), ("accounts", ACCOUNT_COLUMNS), ("campaigns", CAMPAIGN_COLUMNS)):
                fields = (*columns, "raw_json")
                query = f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})"
                connection.executemany(query, [tuple(row.get(field) for field in fields) for row in rows[table]])
            connection.executemany(
                "INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(
                    post["id"], i, post["account_index"], post["campaign_index"], post["date"],
                    post["flags"], int(post["labelled_as_ad"]), int(post["deleted"]), int(post["private"]),
                    post["uninterpreted_flags"], post["views"], post["archive_url"], post["url"],
                    post["source_pointer"], _dump(post["raw_record"]),
                ) for i, post in enumerate(rows["posts"])],
            )
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise DatasetError("Generated SQLite failed its integrity check.")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise DatasetError("Generated SQLite failed its reference check.")
    finally:
        connection.close()


def _file_info(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def prepare_workspace(
    snapshot: DatasetSnapshot, output_dir: str | Path, *, raw_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Write a new workspace and return its manifest plus absolute output path.

    An existing target, even an empty directory or a symlink, is refused. Raw
    bytes must match the validated snapshot. A failed export leaves its new
    directory for inspection but never writes a completed manifest.
    """
    raw = raw_bytes if raw_bytes is not None else getattr(snapshot, "raw_content", b"")
    if not isinstance(raw, bytes) or not raw:
        raise DatasetError("Exact raw snapshot bytes are required to prepare a workspace.")
    if len(raw) != snapshot.raw_bytes or hashlib.sha256(raw).hexdigest() != snapshot.sha256:
        raise DatasetError("Raw snapshot bytes do not match the validated snapshot hash and size.")
    # Dataclasses are mutable; check that a caller did not alter the parsed data
    # after its byte hash and validation were established.
    checked = parse_dataset(raw, source=snapshot.source, fetched_at_utc=snapshot.fetched_at_utc)
    if checked.data != snapshot.data:
        raise DatasetError("Parsed dataset changed after validation; reload the snapshot.")
    target = Path(output_dir).absolute()
    try:
        target.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise DatasetError("Workspace output already exists; choose a new directory.") from exc
    except OSError as exc:
        raise DatasetError("Workspace directory could not be created.", status="unavailable") from exc
    try:
        (target / "raw").mkdir()
        with (target / "raw" / "all.json").open("xb") as stream:
            stream.write(raw)
        rows = _normalized_rows(checked)
        _write_database(target / "dataset.sqlite", checked, rows)
        for table, columns in (("accounts", ACCOUNT_COLUMNS), ("campaigns", CAMPAIGN_COLUMNS), ("posts", POST_COLUMNS), ("categories", CATEGORY_COLUMNS)):
            _write_csv(target / f"{table}.csv", columns, rows[table])
        counts = checked.counts_report()
        _write_json(target / "account-counts.json", counts)
        names = ["raw/all.json", "dataset.sqlite", "accounts.csv", "campaigns.csv", "posts.csv", "categories.csv", "account-counts.json"]
        manifest = {
            "schema_version": "1.0", "status": "complete",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot": checked.metadata(),
            "counts": {
                "accounts": len(rows["accounts"]), "campaigns": len(rows["campaigns"]),
                "posts": len(rows["posts"]), "categories": len(rows["categories"]),
                "zero_post_accounts": counts["zero_post_count"],
                "one_post_accounts": counts["one_post_count"],
            },
            "files": [_file_info(target, name) for name in names],
            "count_unit": "distinct post IDs, including records flagged deleted/private",
            "source_scope": "supplied public explorer snapshot only; no X API requests or private post imports",
            "interpretation": "Dataset inclusion is not proof of payment. Campaigns are destination groups. Original post text and redirect chains are absent.",
            "csv": {
                "encoding": "utf-8", "quoting": "all fields",
                "escaping": "Formula-like cells and numeric string IDs receive a leading apostrophe; JSON and SQLite keep exact values.",
                "nulls": "empty cell; use JSON/SQLite when null and empty-string distinctions matter",
            },
            "sqlite": {
                "schema_version": 1, "post_id_type": "TEXT",
                "read_only": "Open dataset.sqlite with a SQLite URI ending in ?mode=ro for analysis.",
                "queries": [
                    "SELECT handle, post_count FROM accounts ORDER BY post_count DESC, handle;",
                    "SELECT handle FROM accounts WHERE post_count = 1 ORDER BY handle;",
                    "SELECT post_id, handle, post_date, campaign_title, source_pointer FROM post_details WHERE handle = ? COLLATE NOCASE ORDER BY post_date;",
                ],
            },
        }
        # Written last: its presence and status distinguish completed exports.
        _write_json(target / "manifest.json", manifest)
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError) as exc:
        raise DatasetError("Workspace export failed; its new directory may contain partial files and has no completed manifest.", status="incomplete") from exc
    return {**manifest, "output_dir": str(target)}

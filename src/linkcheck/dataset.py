"""Read-only, evidence-preserving lookup of the campaign explorer snapshot.

The explorer's posts are compact arrays, not objects containing handles.  Index
joins and completeness checks are deliberately separate from link-risk verdicts.
This module never reads credentials, fetches a timeline, or changes a live post.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import stat
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

DEFAULT_DATASET_URL = "https://influencer-campaign-explorer.com/data/all.json"
MAX_BYTES = 25 * 1024 * 1024
_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}\Z")
_ID = re.compile(r"[0-9]+\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}
_X_PATH = re.compile(r"^/(?:(?P<handle>[A-Za-z0-9_]{1,15})/status|i/web/status|i/status)/(?P<id>[0-9]+)(?:/.*)?$")
_ARCHIVE = re.compile(r"\A\s*window\.YTD\.(?:tweets|tweet)\.part\d+\s*=\s*", re.ASCII)


class DatasetError(ValueError):
    """An unavailable or invalid source must never be mistaken for zero matches."""

    def __init__(self, message: str, *, status: str = "invalid") -> None:
        super().__init__(message)
        self.status = status


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _handle(value: str) -> str:
    if not isinstance(value, str):
        raise DatasetError("Account handle must be a string.")
    value = value.strip().removeprefix("@")
    if not _HANDLE.fullmatch(value):
        raise DatasetError("Invalid X handle; supply 1–15 letters, digits or underscores.")
    return value


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetError("JSON contains a duplicate object key.")
        result[key] = value
    return result


def _json(text: str) -> Any:
    def bad_constant(_: str) -> None:
        raise DatasetError("JSON contains a non-finite number.")

    try:
        return json.loads(text, object_pairs_hook=_json_object, parse_constant=bad_constant)
    except DatasetError:
        raise
    except (ValueError, RecursionError) as exc:
        raise DatasetError("Source is invalid or truncated JSON.") from exc


def _text(raw: bytes) -> str:
    if len(raw) > MAX_BYTES:
        raise DatasetError("Source exceeds the 25 MiB size limit.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError("Source must be UTF-8 text.") from exc


def _date(value: Any, context: str) -> None:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise DatasetError(f"{context}: expected YYYY-MM-DD date.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise DatasetError(f"{context}: invalid date.") from exc


def _public_url(url: str) -> None:
    """Reject local/private targets, including redirect targets, before a GET."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        host = parsed.hostname.rstrip(".").lower()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
        if not addresses or any(not address.is_global for address in addresses):
            raise ValueError
    except socket.gaierror as exc:
        raise DatasetError("Dataset host could not be resolved.", status="unavailable") from exc
    except (ValueError, OSError) as exc:
        raise DatasetError("Dataset URL must use HTTP(S) and a public host without embedded credentials.") from exc


def _source_label(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class _NoAuth(requests.auth.AuthBase):
    """Suppress automatic .netrc auth without bypassing configured proxies/CA."""

    def __call__(self, request: requests.PreparedRequest) -> requests.PreparedRequest:
        request.headers.pop("Authorization", None)
        return request


class _PublicSession(requests.Session):
    def resolve_redirects(self, *args: Any, **kwargs: Any) -> Any:
        # Even allow_redirects=False normally prepares Response.next, consuming
        # the redirect body and consulting .netrc. Redirects are handled below.
        return iter(())


def _fetch(url: str) -> bytes:
    # An explicit auth handler prevents .netrc discovery. Keep trust_env enabled
    # so configured network proxies and CA bundles remain in force.
    with _PublicSession() as session:
        session.auth = _NoAuth()
        for _ in range(6):
            _public_url(url)
            try:
                with session.get(url, timeout=(5, 20), allow_redirects=False, stream=True) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if not location:
                            raise DatasetError("Dataset redirect has no destination.", status="unavailable")
                        try:
                            url = urljoin(url, location)
                        except ValueError as exc:
                            raise DatasetError("Dataset redirect has an invalid destination.") from exc
                        continue
                    if response.status_code != 200:
                        raise DatasetError(f"Dataset request returned HTTP {response.status_code}.", status="unavailable")
                    declared = response.headers.get("Content-Length", "")
                    if declared.isdigit() and int(declared) > MAX_BYTES:
                        raise DatasetError("Source exceeds the 25 MiB size limit.")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise DatasetError("Source exceeds the 25 MiB size limit.")
                        chunks.append(chunk)
                    return b"".join(chunks)
            except requests.RequestException as exc:
                raise DatasetError("Dataset request failed; no account counts were established.", status="unavailable") from exc
    raise DatasetError("Dataset exceeded the redirect limit.", status="unavailable")


def _read_file(path: str | Path) -> bytes:
    try:
        source = Path(path)
        info = source.stat()
        if not stat.S_ISREG(info.st_mode):
            raise DatasetError("Source must be a regular file.")
        if info.st_size > MAX_BYTES:
            raise DatasetError("Source exceeds the 25 MiB size limit.")
        with source.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise DatasetError("Source exceeds the 25 MiB size limit.")
        return raw
    except OSError as exc:
        raise DatasetError("Source file could not be read.", status="unavailable") from exc


def load_dataset(source: str = DEFAULT_DATASET_URL) -> DatasetSnapshot:
    """Load and validate the whole public snapshot or a local snapshot file."""
    source = str(source)
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", source):
        raw = _fetch(source)
        label = _source_label(source)
    else:
        raw = _read_file(source)
        label = str(Path(source).resolve())
    return parse_dataset(raw, source=label)


def parse_dataset(raw: bytes, *, source: str = "memory", fetched_at_utc: str | None = None) -> DatasetSnapshot:
    """Validate completeness and joins; retain the original byte hash."""
    body = _json(_text(raw))
    if not isinstance(body, dict):
        raise DatasetError("Dataset must be a JSON object.")
    for key in ("accounts", "campaigns", "posts", "cats"):
        if not isinstance(body.get(key), list):
            raise DatasetError(f"Dataset is incomplete: {key} must be an array.")
    if not isinstance(body.get("built"), str) or not body["built"].strip():
        raise DatasetError("Dataset has no build timestamp.")
    cats: set[str] = set()
    for category in body["cats"]:
        if (not isinstance(category, dict) or not isinstance(category.get("id"), str)
                or not category["id"].strip() or category["id"] in cats):
            raise DatasetError("Dataset contains an invalid or duplicate category.")
        if category.get("name") is not None and not isinstance(category["name"], str):
            raise DatasetError("Dataset contains an invalid category name.")
        cats.add(category["id"])
    handles: set[str] = set()
    for i, account in enumerate(body["accounts"]):
        if not isinstance(account, dict):
            raise DatasetError(f"/accounts/{i}: invalid account.")
        normalized = _handle(account.get("h"))
        if normalized != account["h"]:
            raise DatasetError(f"/accounts/{i}: handle must not contain whitespace or @.")
        handle = normalized.casefold()
        if handle in handles:
            raise DatasetError("Dataset contains duplicate account handles.")
        for key in ("name", "av"):
            if account.get(key) is not None and not isinstance(account[key], str):
                raise DatasetError(f"/accounts/{i}: invalid {key} field.")
        for key in ("fol", "gone"):
            if account.get(key) is not None and not _integer(account[key]):
                raise DatasetError(f"/accounts/{i}: invalid {key} field.")
        handles.add(handle)
    campaign_ids: set[str] = set()
    for i, campaign in enumerate(body["campaigns"]):
        if not isinstance(campaign, dict) or not isinstance(campaign.get("id"), str) or not campaign["id"].strip():
            raise DatasetError(f"/campaigns/{i}: invalid campaign.")
        if (campaign["id"].casefold() in campaign_ids or not isinstance(campaign.get("cat"), str)
                or campaign["cat"] not in cats):
            raise DatasetError(f"/campaigns/{i}: duplicate ID or unknown category.")
        campaign_ids.add(campaign["id"].casefold())
        for key in ("title", "pub", "url", "date", "fav"):
            if campaign.get(key) is not None and not isinstance(campaign[key], str):
                raise DatasetError(f"/campaigns/{i}: invalid {key} field.")
        if not _integer(campaign.get("n")) or not _integer(campaign.get("na")):
            raise DatasetError(f"/campaigns/{i}: missing or invalid declared counts.")
    seen: set[str] = set()
    per_campaign: dict[int, list[list[Any]]] = defaultdict(list)
    for i, post in enumerate(body["posts"]):
        location = f"/posts/{i}"
        if not isinstance(post, list) or len(post) not in {6, 7}:
            raise DatasetError(f"{location}: expected six compact fields and an optional archive URL.")
        if not isinstance(post[0], str) or not _ID.fullmatch(post[0]):
            raise DatasetError(f"{location}: post ID must be an exact digit string.")
        if post[0] in seen:
            raise DatasetError(f"{location}: duplicate post ID.")
        seen.add(post[0])
        for position, key in ((1, "accounts"), (2, "campaigns")):
            if not _integer(post[position]) or post[position] >= len(body[key]):
                raise DatasetError(f"{location}: invalid {key} reference.")
        _date(post[3], location)
        if not _integer(post[4]) or (post[5] is not None and not _integer(post[5])):
            raise DatasetError(f"{location}: flags/views must be nonnegative integers (or null views).")
        if len(post) > 6 and post[6] is not None:
            if not isinstance(post[6], str):
                raise DatasetError(f"{location}: invalid archive URL.")
            if post[6]:
                try:
                    archived = urlsplit(post[6])
                    if (archived.scheme not in {"http", "https"} or not archived.hostname
                            or archived.username is not None or archived.password is not None):
                        raise ValueError
                    archived.port  # Validate malformed/non-numeric ports without fetching.
                except ValueError as exc:
                    raise DatasetError(f"{location}: archive URL must use HTTP(S) without credentials.") from exc
        per_campaign[post[2]].append(post)
    for i, campaign in enumerate(body["campaigns"]):
        rows = per_campaign[i]
        if campaign["n"] != len(rows) or campaign["na"] != len({row[1] for row in rows}):
            raise DatasetError(f"/campaigns/{i}: declared counts disagree with post records; snapshot is incomplete or inconsistent.")
        for field_name, observed in (("first", min((row[3] for row in rows), default="")), ("last", max((row[3] for row in rows), default=""))):
            if field_name in campaign and campaign[field_name] != observed:
                raise DatasetError(f"/campaigns/{i}: {field_name} date disagrees with post records.")
    return DatasetSnapshot(
        data=body, source=source, sha256=hashlib.sha256(raw).hexdigest(), raw_bytes=len(raw),
        fetched_at_utc=fetched_at_utc or datetime.now(timezone.utc).isoformat(),
        raw_content=raw,
    )


@dataclass
class DatasetSnapshot:
    data: dict[str, Any]
    source: str
    sha256: str
    raw_bytes: int
    fetched_at_utc: str
    raw_content: bytes = field(default=b"", repr=False)
    _by_handle: dict[str, int] = field(init=False, repr=False)
    _by_account: dict[int, list[int]] = field(init=False, repr=False)
    _by_id: dict[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_handle = {a["h"].casefold(): i for i, a in enumerate(self.data["accounts"])}
        self._by_account = defaultdict(list)
        self._by_id = {}
        for i, post in enumerate(self.data["posts"]):
            self._by_account[post[1]].append(i)
            self._by_id[post[0]] = i

    def metadata(self) -> dict[str, Any]:
        return {"source": self.source, "sha256": self.sha256, "bytes": self.raw_bytes,
                "fetched_at_utc": self.fetched_at_utc, "built": self.data["built"],
                "account_count": len(self.data["accounts"]), "campaign_count": len(self.data["campaigns"]),
                "post_count": len(self.data["posts"]), "unique_post_count": len(self._by_id)}

    def _base(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "status": "complete", "snapshot": self.metadata(),
                "coverage": "Counts describe the complete supplied snapshot after internal consistency checks, not all posts ever made by an account.",
                "interpretation": "Published dataset inclusion is not proof of payment. Original post text and redirect chains are not stored in this snapshot."}

    def post_record(self, index: int) -> dict[str, Any]:
        post = self.data["posts"][index]
        account, campaign = self.data["accounts"][post[1]], self.data["campaigns"][post[2]]
        flags = post[4]
        # Match the publisher's frontend display rule while preserving the
        # original zero in data, raw_record and the byte-identical snapshot.
        views = None if post[5] == 0 and post[3] < "2023-01-01" else post[5]
        return {"id": post[0], "handle": account["h"], "name": account.get("name", account["h"]),
                "date": post[3], "url": f"https://x.com/{account['h']}/status/{post[0]}",
                "source_pointer": f"/posts/{index}", "account_pointer": f"/accounts/{post[1]}",
                "campaign_pointer": f"/campaigns/{post[2]}", "account_index": post[1], "campaign_index": post[2],
                "campaign_id": campaign["id"], "campaign_title": campaign.get("title", ""),
                "publisher": campaign.get("pub", ""), "category": campaign["cat"],
                "destination_url": campaign.get("url", ""), "flags": flags,
                "labelled_as_ad": bool(flags & 8), "deleted": bool(flags & 2), "private": bool(flags & 4),
                "uninterpreted_flags": flags & ~14, "views": views,
                "archive_url": post[6] if len(post) > 6 else None, "raw_record": list(post)}

    def account_report(self, handle: str) -> dict[str, Any]:
        handle = _handle(handle)
        report = self._base()
        index = self._by_handle.get(handle.casefold())
        if index is None:
            report.update(status="account_not_listed", requested_handle=handle, account=None,
                          post_count=None, campaign_count=None, posts=[])
            return report
        account = self.data["accounts"][index]
        posts = [self.post_record(i) for i in self._by_account[index]]
        public_account = {key: account[key] for key in ("h", "name", "av", "fol", "gone") if key in account}
        report.update(account={**public_account, "index": index, "source_pointer": f"/accounts/{index}"},
                      post_count=len(posts), campaign_count=len({p["campaign_index"] for p in posts}), posts=posts)
        return report

    def counts_report(self) -> dict[str, Any]:
        report = self._base()
        zero, one = [], []
        for index, account in enumerate(self.data["accounts"]):
            indices = self._by_account[index]
            item = {"handle": account["h"], "name": account.get("name", account["h"]),
                    "account_index": index, "source_pointer": f"/accounts/{index}", "post_count": len(indices)}
            if not indices:
                zero.append(item)
            elif len(indices) == 1:
                one.append({**item, "post": self.post_record(indices[0])})
        report.update(zero_post_count=len(zero), one_post_count=len(one),
                      zero_post_accounts=sorted(zero, key=lambda row: row["handle"].casefold()),
                      one_post_accounts=sorted(one, key=lambda row: row["handle"].casefold()),
                      count_unit="distinct post IDs, including records flagged deleted/private")
        return report

    def match_posts(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        report = self._base()
        matched, absent, skipped = [], [], []
        references: dict[str, list[dict[str, Any]]] = defaultdict(list)
        duplicates = 0
        for position, record in enumerate(records):
            reference = _reference(record, f"/references/{position}")
            if reference["platform"] != "x":
                skipped.append({"reference": reference, "reason": "platform_not_x"})
                continue
            post_id = reference["id"]
            if post_id in references:
                duplicates += 1
            references[post_id].append(reference)
        for post_id, supplied in references.items():
            index = self._by_id.get(post_id)
            if index is None:
                absent.append({**supplied[0], "references": supplied})
                continue
            post = self.post_record(index)
            authors = {ref["author_handle"].casefold() for ref in supplied if ref.get("author_handle")}
            dates = {ref["date"] for ref in supplied if ref.get("date")}
            def compare(values: set[str], expected: str) -> str:
                if not values:
                    return "not_supplied"
                if len(values) > 1:
                    return "conflicting"
                return "agrees" if expected in values else "differs"
            matched.append({"reference": supplied[0], "references": supplied,
                            "author_check": compare(authors, post["handle"].casefold()),
                            "date_check": compare(dates, post["date"]), "post": post})
        report.update(scope="supplied_post_references_only", supplied_count=len(records),
                      matched_count=len(matched), not_in_dataset_count=len(absent), skipped_count=len(skipped),
                      duplicate_reference_count=duplicates, matched=matched, not_in_dataset=absent, skipped=skipped)
        report["reference_coverage"] = getattr(records, "coverage", {"scope": "supplied_references_only", "complete_account_history": False})
        report["verification_note"] = "Exact IDs establish snapshot membership. Author/date checks compare supplied metadata with dataset labels; original post content and authorship have not been independently verified. A URL path handle is not proof of authorship."
        return report


def _reference_date(value: Any, pointer: str) -> str:
    if not isinstance(value, str):
        raise DatasetError(f"{pointer}: post date must be a string.")
    if _DATE.fullmatch(value):
        _date(value, pointer)
        return value
    try:
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            timestamp = datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp.astimezone(timezone.utc).date().isoformat()
    except (ValueError, OverflowError) as exc:
        raise DatasetError(f"{pointer}: post date must be YYYY-MM-DD or a timestamp with a timezone.") from exc


def _reference(item: Any, pointer: str, *, authors: dict[str, str] | None = None) -> dict[str, Any]:
    if isinstance(item, str):
        item = {"url": item} if "://" in item else {"id": item}
    if not isinstance(item, dict):
        raise DatasetError(f"{pointer}: expected a post ID, URL, or record object.")
    if "tweet" in item:
        if not isinstance(item["tweet"], dict):
            raise DatasetError(f"{pointer}: invalid archive tweet wrapper.")
        item = item["tweet"]
        pointer += "/tweet"
    if item.get("errors") or item.get("error"):
        raise DatasetError(f"{pointer}: post reference reported an error.")
    platform = item.get("platform", "x")
    if not isinstance(platform, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", platform):
        raise DatasetError(f"{pointer}: invalid platform name.")
    platform = platform.lower()
    if platform in {"twitter", "twitter.com", "x.com"}:
        platform = "x"
    source_pointer = item.get("source_pointer", pointer)
    if (not isinstance(source_pointer, str) or (source_pointer and not source_pointer.startswith("/"))
            or re.search(r"~(?![01])", source_pointer)):
        raise DatasetError(f"{pointer}: invalid reference source pointer.")
    reference: dict[str, Any] = {"platform": platform, "source_pointer": source_pointer}
    if platform != "x":
        # Avoid confusing another platform's numeric IDs with X status IDs.
        unsupported_id = item.get("id_str") or item.get("post_id") or item.get("id") or ""
        reference["id"] = str(unsupported_id) if isinstance(unsupported_id, str) or type(unsupported_id) is int else ""
        return reference
    post_url = item.get("url") or item.get("post_url") or item.get("permalink")
    author_values = [_handle(item[key]) for key in ("author_handle", "handle", "username") if item.get(key)]
    if len({value.casefold() for value in author_values}) > 1:
        raise DatasetError(f"{pointer}: supplied author handle fields disagree.")
    url_id, author = None, author_values[0] if author_values else None
    author_source = item.get("author_handle_source", "supplied")
    if not isinstance(author_source, str) or author_source not in {"supplied", "url_path", "api_expansion"}:
        raise DatasetError(f"{pointer}: invalid author evidence source.")
    author_id = item.get("author_id")
    if author_id is not None:
        if type(author_id) is int and 0 <= author_id <= 2**53 - 1:
            author_id = str(author_id)
        if not isinstance(author_id, str) or not _ID.fullmatch(author_id):
            raise DatasetError(f"{pointer}: author ID must be an exact digit string.")
        reference["author_id"] = author_id
        expanded_author = (authors or {}).get(author_id)
        if expanded_author:
            if author and _handle(author).casefold() != expanded_author.casefold():
                raise DatasetError(f"{pointer}: author handle disagrees with API user expansion.")
            author, author_source = expanded_author, "api_expansion"
    if post_url:
        if not isinstance(post_url, str):
            raise DatasetError(f"{pointer}: post URL must be a string.")
        try:
            parsed = urlsplit(post_url)
            if parsed.username is not None or parsed.password is not None:
                raise ValueError
            parsed.port
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in _X_HOSTS:
                reference.update(platform="other", id="")
                return reference
            match = _X_PATH.fullmatch(parsed.path)
            if not match:
                raise ValueError
            url_id = match.group("id")
            if not author and match.group("handle"):
                author, author_source = match.group("handle"), "url_path"
        except ValueError as exc:
            raise DatasetError(f"{pointer}: invalid X status URL.") from exc
    supplied_id = item.get("id_str") or item.get("post_id") or item.get("id") or url_id
    if type(supplied_id) is int and 0 <= supplied_id <= (2**53 - 1):
        supplied_id = str(supplied_id)
    if not isinstance(supplied_id, str) or not _ID.fullmatch(supplied_id):
        raise DatasetError(f"{pointer}: supply an exact string post ID; unsafe numeric IDs are rejected.")
    explicit_strings = {item[key] for key in ("id_str", "post_id", "id") if isinstance(item.get(key), str)}
    if any(value != supplied_id for value in explicit_strings):
        raise DatasetError(f"{pointer}: supplied ID fields disagree.")
    if url_id and supplied_id != url_id:
        raise DatasetError(f"{pointer}: post ID disagrees with the status URL.")
    reference["id"] = supplied_id
    if author:
        reference["author_handle"] = _handle(author)
        reference["author_handle_source"] = author_source
    dates = {_reference_date(item[key], pointer) for key in ("date", "created_at") if item.get(key) is not None}
    if len(dates) > 1:
        raise DatasetError(f"{pointer}: supplied post date fields disagree.")
    if dates:
        reference["date"] = next(iter(dates))
    return reference


class PostReferences(list[dict[str, Any]]):
    """Normalized IDs with non-secret pagination/completeness information."""

    def __init__(self, items: list[dict[str, Any]], *, more_pages: bool = False) -> None:
        super().__init__(items)
        self.coverage = {"scope": "supplied_reference_file_only", "complete_account_history": False,
                         "more_pages_available": more_pages}


def load_post_references(path: str | Path) -> list[dict[str, Any]]:
    """Read JSON/JSONL, X API data, or a recognized X archive assignment.

    JavaScript is never executed. Only IDs, platform and optional author/date
    evidence survive normalization; text, credentials and unrelated content are omitted.
    """
    content = _text(_read_file(path)).strip()
    if not content:
        raise DatasetError("Post reference file is empty.")
    wrapper = _ARCHIVE.match(content)
    if wrapper:
        content = content[wrapper.end():].strip()
        if content.endswith(";"):
            content = content[:-1].rstrip()
    try:
        body = _json(content)
    except DatasetError:
        if wrapper or str(path).lower().endswith(".js"):
            raise DatasetError("X archive must be a recognized assignment containing only JSON.")
        lines = [line for line in content.splitlines() if line.strip()]
        if len(lines) < 2:
            raise
        body = [_json(line) for line in lines]
    if isinstance(body, dict):
        if body.get("errors") or body.get("error"):
            raise DatasetError("Post reference source reported an error; an empty result is not established.")
        authors: dict[str, str] = {}
        included = body.get("includes", {})
        if not isinstance(included, dict):
            raise DatasetError("Post reference includes must be an object.")
        users = included.get("users", [])
        if not isinstance(users, list):
            raise DatasetError("Post reference includes.users must be an array.")
        for user in users:
            if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not _ID.fullmatch(user["id"]):
                raise DatasetError("Post reference includes.users contains an invalid user ID.")
            username = _handle(user.get("username"))
            if user["id"] in authors and authors[user["id"]].casefold() != username.casefold():
                raise DatasetError("Post reference includes.users contains conflicting author labels.")
            authors[user["id"]] = username
        meta = body.get("meta", {})
        if not isinstance(meta, dict):
            raise DatasetError("Post reference meta must be an object.")
        next_token = meta.get("next_token")
        if next_token is not None and not isinstance(next_token, str):
            raise DatasetError("Post reference next-page marker must be a string.")
        for key in ("data", "posts", "tweets"):
            if key in body:
                entries = body[key]
                if key == "data" and isinstance(entries, dict):
                    if "result_count" in meta and (not _integer(meta["result_count"]) or meta["result_count"] != 1):
                        raise DatasetError("Post reference result count disagrees with the supplied page.")
                    return PostReferences([_reference(entries, "/data", authors=authors)], more_pages=bool(next_token))
                if not isinstance(entries, list):
                    raise DatasetError(f"Post reference {key} must be an array.")
                if key == "data" and "result_count" in meta:
                    if not _integer(meta["result_count"]) or meta["result_count"] != len(entries):
                        raise DatasetError("Post reference result count disagrees with the supplied page.")
                return PostReferences([_reference(item, f"/{key}/{i}", authors=authors) for i, item in enumerate(entries)], more_pages=bool(next_token))
        body = [body]
    if isinstance(body, str):
        body = [body]
    if not isinstance(body, list):
        raise DatasetError("Post references must be records or an array of records.")
    return PostReferences([_reference(item, f"/{i}") for i, item in enumerate(body)])

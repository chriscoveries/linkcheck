"""Pure, provenance-preserving queries over a validated explorer snapshot.

Search covers the metadata published by the explorer. The snapshot contains no
post text. Availability and disclosure filters use its recorded flags only;
they do not perform a live check or establish payment.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import re
from typing import Any, Callable

from .dataset import DatasetError, DatasetSnapshot


AVAILABILITY = ("all", "available", "deleted", "private", "unavailable")
POST_SORTS = ("date", "id", "handle", "campaign", "campaign_id", "category", "views", "ads")
ACCOUNT_SORTS = ("posts", "campaigns", "handle", "name", "followers", "first", "last", "ads", "views")
CAMPAIGN_SORTS = ("posts", "accounts", "date", "first", "last", "title", "publisher", "category", "ads", "views")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}\Z")


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _sort_text(value: Any) -> str | None:
    return value.casefold() if isinstance(value, str) and value else None


def _id_order(value: str) -> tuple[int, str, str]:
    # Decimal strings can be compared numerically without converting them to a
    # float or relying on Python's limit for converting huge decimal integers.
    digits = value.lstrip("0") or "0"
    return len(digits), digits, value


def _option(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{name} must be a nonempty string.")
    return value.strip()


def _date(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise DatasetError(f"{name} must use YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise DatasetError(f"{name} is an invalid date.") from exc
    return value


def _nonnegative(value: Any, name: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not int or value < 0:
        raise DatasetError(f"{name} must be a nonnegative integer.")


def _filters(
    snapshot: DatasetSnapshot, *, handle: str | None, category: str | None,
    campaign: str | None, search: str | None, since: str | None,
    until: str | None, ad: bool | None, availability: str,
) -> dict[str, Any]:
    handle = _option(handle, "handle")
    if handle is not None:
        handle = handle.removeprefix("@")
        if not _HANDLE.fullmatch(handle):
            raise DatasetError("Invalid X handle.")
        matches = [a["h"] for a in snapshot.data["accounts"] if a["h"].casefold() == handle.casefold()]
        if not matches:
            raise DatasetError("Requested account is not listed in this snapshot.", status="account_not_listed")
        handle = matches[0]
    category = _option(category, "category")
    if category is not None:
        matches = [c["id"] for c in snapshot.data["cats"] if c["id"].casefold() == category.casefold()]
        if not matches:
            raise DatasetError("Unknown category ID in this snapshot.")
        if len(matches) != 1:
            raise DatasetError("Category ID is ambiguous after case normalization.")
        category = matches[0]
    campaign = _option(campaign, "campaign")
    if campaign is not None:
        matches = [c["id"] for c in snapshot.data["campaigns"] if c["id"].casefold() == campaign.casefold()]
        if not matches:
            raise DatasetError("Unknown campaign ID in this snapshot.")
        if len(matches) != 1:
            raise DatasetError("Campaign ID is ambiguous after case normalization.")
        campaign = matches[0]
    search = _option(search, "search")
    since, until = _date(since, "since"), _date(until, "until")
    if since is not None and until is not None and since > until:
        raise DatasetError("since must be on or before until.")
    if ad is not None and type(ad) is not bool:
        raise DatasetError("ad must be true, false, or omitted.")
    if not isinstance(availability, str) or availability not in AVAILABILITY:
        raise DatasetError("availability must be one of: " + ", ".join(AVAILABILITY))
    return {"handle": handle, "category": category, "campaign": campaign,
            "search": search, "since": since, "until": until, "ad": ad,
            "availability": availability}


def _selected(snapshot: DatasetSnapshot, filters: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    search = filters["search"].casefold() if filters["search"] else None
    category_names = {c["id"]: _text(c.get("name")) for c in snapshot.data["cats"]}
    for index in range(len(snapshot.data["posts"])):
        row = snapshot.post_record(index)
        if filters["handle"] is not None and row["handle"] != filters["handle"]:
            continue
        if filters["category"] is not None and row["category"] != filters["category"]:
            continue
        if filters["campaign"] is not None and row["campaign_id"] != filters["campaign"]:
            continue
        if filters["since"] is not None and row["date"] < filters["since"]:
            continue
        if filters["until"] is not None and row["date"] > filters["until"]:
            continue
        if filters["ad"] is not None and row["labelled_as_ad"] != filters["ad"]:
            continue
        availability = filters["availability"]
        unavailable = row["deleted"] or row["private"]
        if availability == "available" and unavailable:
            continue
        if availability == "unavailable" and not unavailable:
            continue
        if availability == "deleted" and not row["deleted"]:
            continue
        if availability == "private" and not row["private"]:
            continue
        if search:
            fields = ("id", "handle", "name", "campaign_id", "campaign_title", "publisher", "category", "destination_url")
            text = "\n".join(_text(row.get(key)) for key in fields)
            text += "\n" + category_names.get(row["category"], "")
            if search not in text.casefold():
                continue
        result.append(row)
    return result


def _summary(posts: list[dict[str, Any]]) -> dict[str, Any]:
    values = [p["views"] for p in posts if p["views"] is not None]
    return {
        "post_count": len(posts), "ad_count": sum(p["labelled_as_ad"] for p in posts),
        "deleted_count": sum(p["deleted"] for p in posts), "private_count": sum(p["private"] for p in posts),
        "uninterpreted_flag_count": sum(bool(p["uninterpreted_flags"]) for p in posts),
        "first": min((p["date"] for p in posts), default=None),
        "last": max((p["date"] for p in posts), default=None),
        "views": sum(values) if values else None, "views_known_count": len(values),
    }


def _bounds(min_posts: int | None, max_posts: int | None) -> None:
    _nonnegative(min_posts, "min_posts", optional=True)
    _nonnegative(max_posts, "max_posts", optional=True)
    if min_posts is not None and max_posts is not None and min_posts > max_posts:
        raise DatasetError("min_posts must be at most max_posts.")


def _in_bounds(count: int, minimum: int | None, maximum: int | None) -> bool:
    return (minimum is None or count >= minimum) and (maximum is None or count <= maximum)


def _sorted(
    rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any],
    tie: Callable[[dict[str, Any]], Any], descending: bool,
) -> list[dict[str, Any]]:
    # Stable two-pass sort keeps tie order ascending even when the primary sort
    # is descending. Null values always follow known values in either direction.
    rows = sorted(rows, key=tie)
    present = [row for row in rows if key(row) is not None]
    absent = [row for row in rows if key(row) is None]
    return sorted(present, key=key, reverse=descending) + absent


def _finish(
    snapshot: DatasetSnapshot, entity: str, rows: list[dict[str, Any]],
    filters: dict[str, Any], *, sort: str, descending: bool,
    limit: int | None, offset: int, sorts: dict[str, Callable[[dict[str, Any]], Any]],
    tie: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    if not isinstance(sort, str) or sort not in sorts:
        raise DatasetError(f"Unknown {entity} sort; use: " + ", ".join(sorts))
    if type(descending) is not bool:
        raise DatasetError("descending must be true or false.")
    _nonnegative(limit, "limit", optional=True)
    _nonnegative(offset, "offset")
    sorted_rows = _sorted(rows, sorts[sort], tie, descending)
    page = sorted_rows[offset:] if limit is None else sorted_rows[offset:offset + limit]
    return {
        "schema_version": "1.0", "status": "complete", "snapshot": snapshot.metadata(),
        "entity": entity, "filters": dict(filters), "sort": sort, "descending": descending,
        "offset": offset, "limit": limit, "total_matched": len(rows), "returned_count": len(page),
        "rows": page,
        "count_scope": "Distinct post IDs selected by these filters, within the validated published snapshot. Deleted/private records count unless excluded by availability.",
        "search_scope": "Literal case-insensitive metadata search; the snapshot stores no post text.",
        "interpretation": "Dataset inclusion and ad labels are the source's assertions. Availability reflects source flags, not a live X check. Counts do not establish payment or complete X history.",
    }


def query_posts(
    snapshot: DatasetSnapshot, *, handle: str | None = None, category: str | None = None,
    campaign: str | None = None, search: str | None = None, since: str | None = None,
    until: str | None = None, ad: bool | None = None, availability: str = "all",
    sort: str = "date", descending: bool = False, limit: int | None = None, offset: int = 0,
) -> dict[str, Any]:
    """Filter exact post records, then sort and paginate without losing totals."""
    filters = _filters(snapshot, handle=handle, category=category, campaign=campaign,
                       search=search, since=since, until=until, ad=ad, availability=availability)
    sorts = {"date": lambda r: r["date"], "id": lambda r: _id_order(r["id"]),
             "handle": lambda r: r["handle"].casefold(), "campaign": lambda r: _sort_text(r["campaign_title"]),
             "campaign_id": lambda r: r["campaign_id"].casefold(), "category": lambda r: r["category"].casefold(),
             "views": lambda r: r["views"], "ads": lambda r: r["labelled_as_ad"]}
    return _finish(snapshot, "posts", _selected(snapshot, filters), filters, sort=sort,
                   descending=descending, limit=limit, offset=offset, sorts=sorts,
                   tie=lambda r: (_id_order(r["id"]), r["source_pointer"]))


def _post_filters_active(filters: dict[str, Any], except_key: str) -> bool:
    return any(value is not None for key, value in filters.items()
               if key not in {except_key, "availability"}) or filters["availability"] != "all"


def query_accounts(
    snapshot: DatasetSnapshot, *, handle: str | None = None, category: str | None = None,
    campaign: str | None = None, search: str | None = None, since: str | None = None,
    until: str | None = None, ad: bool | None = None, availability: str = "all",
    min_posts: int | None = None, max_posts: int | None = None, sort: str = "posts",
    descending: bool = False, limit: int | None = None, offset: int = 0,
) -> dict[str, Any]:
    """Aggregate selected posts per account.

    With no post filters, include every listed account, including genuine zeros.
    With post filters, include accounts having at least one selected post. An
    exact handle selector alone still retains a listed zero-post account.
    """
    _bounds(min_posts, max_posts)
    filters = _filters(snapshot, handle=handle, category=category, campaign=campaign,
                       search=search, since=since, until=until, ad=ad, availability=availability)
    by_account: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for post in _selected(snapshot, filters):
        by_account[post["account_index"]].append(post)
    full_counts = Counter(p[1] for p in snapshot.data["posts"])
    filtered = _post_filters_active(filters, "handle")
    rows = []
    for index, account in enumerate(snapshot.data["accounts"]):
        if filters["handle"] is not None and account["h"] != filters["handle"]:
            continue
        posts = by_account[index]
        if (filtered and not posts) or not _in_bounds(len(posts), min_posts, max_posts):
            continue
        followers = account.get("fol")
        if type(followers) is not int or followers < 0:
            followers = None
        rows.append({"handle": account["h"], "name": account.get("name", account["h"]),
                     "followers": followers, "account_index": index, "source_pointer": f"/accounts/{index}",
                     "campaign_count": len({p["campaign_index"] for p in posts}),
                     "category_ids": sorted({p["category"] for p in posts}),
                     "total_post_count": full_counts[index], "raw_record": dict(account), **_summary(posts)})
    sorts = {"posts": lambda r: r["post_count"], "campaigns": lambda r: r["campaign_count"],
             "handle": lambda r: r["handle"].casefold(), "name": lambda r: _sort_text(r["name"]),
             "followers": lambda r: r["followers"], "first": lambda r: r["first"], "last": lambda r: r["last"],
             "ads": lambda r: r["ad_count"], "views": lambda r: r["views"]}
    filters.update(min_posts=min_posts, max_posts=max_posts)
    report = _finish(snapshot, "accounts", rows, filters, sort=sort, descending=descending,
                     limit=limit, offset=offset, sorts=sorts, tie=lambda r: (r["handle"].casefold(), r["account_index"]))
    report["zero_group_policy"] = "Listed zero-post accounts appear only when no post filters are active; handle and count bounds may still select them."
    return report


def query_campaigns(
    snapshot: DatasetSnapshot, *, handle: str | None = None, category: str | None = None,
    campaign: str | None = None, search: str | None = None, since: str | None = None,
    until: str | None = None, ad: bool | None = None, availability: str = "all",
    min_posts: int | None = None, max_posts: int | None = None, sort: str = "posts",
    descending: bool = False, limit: int | None = None, offset: int = 0,
) -> dict[str, Any]:
    """Aggregate selected posts per source-defined destination group."""
    _bounds(min_posts, max_posts)
    filters = _filters(snapshot, handle=handle, category=category, campaign=campaign,
                       search=search, since=since, until=until, ad=ad, availability=availability)
    by_campaign: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for post in _selected(snapshot, filters):
        by_campaign[post["campaign_index"]].append(post)
    full_counts = Counter(p[2] for p in snapshot.data["posts"])
    filtered = _post_filters_active(filters, "campaign")
    rows = []
    for index, item in enumerate(snapshot.data["campaigns"]):
        if filters["campaign"] is not None and item["id"] != filters["campaign"]:
            continue
        posts = by_campaign[index]
        if (filtered and not posts) or not _in_bounds(len(posts), min_posts, max_posts):
            continue
        rows.append({"id": item["id"], "title": item.get("title", ""),
                     "publisher": item.get("pub", ""), "category": item["cat"],
                     "destination_url": item.get("url", ""), "published_date": item.get("date") or None,
                     "campaign_index": index, "source_pointer": f"/campaigns/{index}",
                     "account_count": len({p["account_index"] for p in posts}),
                     "total_post_count": full_counts[index], "raw_record": dict(item), **_summary(posts)})
    sorts = {"posts": lambda r: r["post_count"], "accounts": lambda r: r["account_count"],
             "date": lambda r: r["last"], "first": lambda r: r["first"], "last": lambda r: r["last"],
             "title": lambda r: _sort_text(r["title"]), "publisher": lambda r: _sort_text(r["publisher"]),
             "category": lambda r: r["category"].casefold(), "ads": lambda r: r["ad_count"], "views": lambda r: r["views"]}
    filters.update(min_posts=min_posts, max_posts=max_posts)
    report = _finish(snapshot, "campaigns", rows, filters, sort=sort, descending=descending,
                     limit=limit, offset=offset, sorts=sorts, tie=lambda r: (r["id"].casefold(), r["campaign_index"]))
    report["zero_group_policy"] = "Zero-post groups appear only when no post filters are active; campaign and count bounds may still select them."
    report["campaign_unit"] = "Source-defined destination URL group, not a verified distinct commercial campaign."
    return report

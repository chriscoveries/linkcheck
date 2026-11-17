"""Resumable full-history all-posts scan: link-only, minimal payload, next_token paging."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import EXIT_CODES, Severity, worst_severity
from .tracking import analyze_tracking_params, extract_tracking_codes
from .urls import strip_tracking
from .x_api import (
    MAX_RESULTS,
    RATE_PER_DAY_UTC,
    RATE_PER_MINUTE,
    finalize_plan,
    link_account_query,
    link_search_args,
    mcp_call,
)
from .x_ingest import _is_tco, extract_posts, strip_wrappers

STATE_VERSION = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def empty_state(
    username: str,
    *,
    include_reposts: bool = False,
    exclude_replies: bool = False,
    with_text: bool = False,
) -> dict[str, Any]:
    user = username.lstrip("@")
    return {
        "schema_version": STATE_VERSION,
        "playbook": "all-posts",
        "username": user,
        "query": link_account_query(
            user, include_reposts=include_reposts, exclude_replies=exclude_replies
        ),
        "include_reposts": include_reposts,
        "exclude_replies": exclude_replies,
        "with_text": with_text,
        "done": False,
        "mode": "full",  # full | incremental
        "next_token": None,
        "newest_id": None,
        "checkpoint_newest_id": None,  # high-water from prior completed full/incremental
        "call_timestamps": [],
        "post_ids": [],
        "posts": {},
        "pages": 0,
        "report": None,
    }


def load_state(path: Path, *, username: str | None = None) -> dict[str, Any]:
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if username:
            user = username.lstrip("@")
            if data.get("username") and data["username"] != user:
                raise ValueError(
                    f"state username {data['username']!r} != --username {user!r}"
                )
        return data
    if not username:
        raise ValueError("all-posts requires --username when creating a new state file")
    return empty_state(username)


def save_state(path: Path, state: dict[str, Any]) -> None:
    # Drop ephemeral keys
    state.pop("_now", None)
    state.pop("_minute_ago", None)
    path.write_text(
        json.dumps(state, separators=(",", ":"), sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _prune_timestamps(state: dict[str, Any], now: datetime | None = None) -> None:
    now = now or _now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    kept: list[str] = []
    for raw in state.get("call_timestamps") or []:
        dt = _parse_iso(str(raw))
        if dt is None:
            continue
        if dt >= day_start:
            kept.append(_iso(dt))
    state["call_timestamps"] = kept


def rate_limit_wait(state: dict[str, Any], now: datetime | None = None) -> datetime | None:
    now = now or _now()
    _prune_timestamps(state, now)
    stamps = [_parse_iso(s) for s in state.get("call_timestamps") or []]
    stamps = [s for s in stamps if s is not None]
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = [s for s in stamps if s >= day_start]
    if len(today) >= RATE_PER_DAY_UTC:
        return day_start + timedelta(days=1)
    minute_ago = now - timedelta(minutes=1)
    recent = sorted(s for s in stamps if s >= minute_ago)
    if len(recent) >= RATE_PER_MINUTE:
        return recent[0] + timedelta(minutes=1)
    return None


def record_call(state: dict[str, Any], when: datetime | None = None) -> None:
    when = when or _now()
    stamps = list(state.get("call_timestamps") or [])
    stamps.append(_iso(when))
    state["call_timestamps"] = stamps
    _prune_timestamps(state, when)


def estimate_reads(post_count: int) -> dict[str, int]:
    """posts_with_links / 25 = reads (pages)."""
    pages = (max(0, int(post_count)) + MAX_RESULTS - 1) // MAX_RESULTS if post_count else 0
    return {"posts_with_links": int(post_count), "reads": pages, "page_size": MAX_RESULTS}


def plan_all_posts(
    *,
    username: str | None,
    state_path: Path,
    include_reposts: bool = False,
    exclude_replies: bool = False,
    with_text: bool = False,
    preflight: bool = False,
    full: bool = False,
    incremental: bool = False,
) -> dict[str, Any]:
    state = load_state(state_path, username=username)
    user = (username or state.get("username") or "").lstrip("@")
    if not user:
        raise ValueError("all-posts requires --username")

    # Refresh query flags on each plan (flags are source of truth for new scans)
    query = link_account_query(
        user, include_reposts=include_reposts, exclude_replies=exclude_replies
    )
    state["username"] = user
    state["query"] = query
    state["include_reposts"] = include_reposts
    state["exclude_replies"] = exclude_replies
    state["with_text"] = with_text

    if full:
        state = empty_state(
            user,
            include_reposts=include_reposts,
            exclude_replies=exclude_replies,
            with_text=with_text,
        )
        state["mode"] = "full"
    elif (
        incremental
        and state.get("done")
        and state.get("newest_id")
        and not state.get("next_token")
    ):
        # Later run: only new link posts since last newest_id
        state["done"] = False
        state["mode"] = "incremental"
        state["checkpoint_newest_id"] = state["newest_id"]
        state["next_token"] = None
        state["pages"] = 0
        state["report"] = None
    elif state.get("done"):
        report = state.get("report") or build_report(state)
        save_state(state_path, state)
        return finalize_plan(
            "all-posts",
            [],
            done=True,
            wait_until=None,
            report=report,
            post_count=len(state.get("post_ids") or []),
            query=query,
            read_estimate=estimate_reads(len(state.get("post_ids") or [])),
        )

    wait = rate_limit_wait(state)
    if wait is not None:
        save_state(state_path, state)
        return finalize_plan(
            "all-posts",
            [],
            done=False,
            wait_until=_iso(wait),
            post_count=len(state.get("post_ids") or []),
            query=query,
        )

    calls: list[dict[str, Any]] = []
    # Preflight only on the first page of a run
    if preflight and int(state.get("pages") or 0) == 0 and not state.get("next_token"):
        calls.append(
            mcp_call(
                "get_posts_counts_recent",
                {"query": query, "granularity": "day"},
            )
        )

    since_id = None
    if state.get("mode") == "incremental" and state.get("checkpoint_newest_id") and not state.get(
        "next_token"
    ):
        since_id = str(state["checkpoint_newest_id"])

    args = link_search_args(
        query,
        next_token=state.get("next_token") or None,
        since_id=since_id if not state.get("next_token") else None,
        with_text=with_text,
    )
    calls.append(mcp_call("search_posts_all", args))

    # Rough estimate note: without preflight result we only know page size
    read_estimate = {
        "page_size": MAX_RESULTS,
        "formula": "ceil(posts_with_links / 25) = reads",
        "this_plan_reads": len([c for c in calls if c["tool"] == "search_posts_all"]),
    }

    save_state(state_path, state)
    return finalize_plan(
        "all-posts",
        calls,
        done=False,
        wait_until=None,
        post_count=len(state.get("post_ids") or []),
        pages=state.get("pages") or 0,
        query=query,
        mode=state.get("mode") or "full",
        read_estimate=read_estimate,
    )


def _meta_from_raw(raw: str) -> dict[str, Any]:
    text = strip_wrappers(raw)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(text)
        except json.JSONDecodeError:
            return {}
    if not isinstance(obj, dict):
        return {}
    meta = obj.get("meta") or {}
    return meta if isinstance(meta, dict) else {}


def _slim_post(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(post.get("id") or ""),
        "created_at": post.get("created_at"),
        "urls": list(post.get("urls") or []),
    }


def append_page(
    raw: str,
    state_path: Path,
    *,
    offline: bool = True,
) -> dict[str, Any]:
    """Merge one search_posts_all page into state. Idempotent by post id."""
    del offline  # reserved; link checks are local on expanded urls
    state = load_state(state_path)
    if state.get("done") and not state.get("next_token"):
        report = state.get("report") or build_report(state)
        return {
            "playbook": "all-posts",
            "done": True,
            "added": 0,
            "post_count": len(state.get("post_ids") or []),
            "report": report,
            "verdict": report.get("verdict", "OK"),
            "exit_code": report.get("exit_code", 0),
        }

    record_call(state)
    posts, truncated = extract_posts(raw)
    meta = _meta_from_raw(raw)

    posts_map: dict[str, Any] = dict(state.get("posts") or {})
    ids: list[str] = list(state.get("post_ids") or [])
    seen = set(ids)
    added = 0
    page_ids: list[str] = []
    for post in posts:
        slim = _slim_post(post)
        pid = slim["id"]
        if not pid:
            continue
        page_ids.append(pid)
        if pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)
        posts_map[pid] = slim
        added += 1

    state["posts"] = posts_map
    state["post_ids"] = ids
    state["pages"] = int(state.get("pages") or 0) + 1

    next_token = meta.get("next_token")
    if isinstance(next_token, str) and next_token.strip():
        state["next_token"] = next_token.strip()
    else:
        state["next_token"] = None

    # Track newest snowflake id seen
    all_numeric = []
    for pid in ids:
        try:
            all_numeric.append(int(pid))
        except ValueError:
            continue
    if all_numeric:
        state["newest_id"] = str(max(all_numeric))

    page_count = len(posts)
    if state.get("next_token"):
        state["done"] = False
    elif page_count == 0 or page_count < MAX_RESULTS:
        state["done"] = True
    elif added == 0:
        state["done"] = True
    else:
        # Full page without next_token — stop (next_token-only paging)
        state["done"] = True

    out: dict[str, Any] = {
        "playbook": "all-posts",
        "done": bool(state.get("done")),
        "added": added,
        "post_count": len(ids),
        "pages": state["pages"],
        "next_token": state.get("next_token"),
        "truncated": truncated,
        "read_estimate": estimate_reads(len(ids)),
    }

    if state.get("done"):
        report = build_report(state)
        state["report"] = report
        out["report"] = report
        out["verdict"] = report["verdict"]
        out["exit_code"] = report["exit_code"]
        out["flagged_posts"] = report["flagged_posts"]
        out["clean_urls"] = report["clean_urls"]
        out["shared_codes"] = report["shared_codes"]
    else:
        out["verdict"] = "OK"
        out["exit_code"] = 0

    save_state(state_path, state)
    return out


def build_report(state: dict[str, Any]) -> dict[str, Any]:
    posts_map: dict[str, Any] = state.get("posts") or {}
    flagged: list[dict[str, Any]] = []
    clean_urls: list[str] = []
    clean_seen: set[str] = set()
    code_posts: dict[tuple[str, str], set[str]] = defaultdict(set)

    for pid in state.get("post_ids") or []:
        post = posts_map.get(pid) or {}
        for url in post.get("urls") or []:
            if _is_tco(url):
                continue
            for finding in analyze_tracking_params(url):
                if finding.severity == Severity.INFO.value and finding.code != "dead_link":
                    continue
                flagged.append(
                    {
                        "id": pid,
                        "url": url,
                        "reason": finding.message,
                        "code": finding.code,
                    }
                )
            for code in extract_tracking_codes(url):
                code_posts[code].add(pid)
            cleaned = strip_tracking(url)
            if cleaned and not _is_tco(cleaned) and cleaned not in clean_seen:
                clean_seen.add(cleaned)
                clean_urls.append(cleaned)

    shared_codes = [
        {
            "key": key,
            "value": val,
            "post_ids": sorted(pids),
            "count": len(pids),
        }
        for (key, val), pids in sorted(code_posts.items(), key=lambda x: (x[0][0], x[0][1]))
        if len(pids) >= 2
    ]
    for entry in shared_codes:
        flagged.append(
            {
                "id": entry["post_ids"][0],
                "url": "",
                "reason": (
                    f"Tracking code {entry['key']}={entry['value']} appears in "
                    f"{entry['count']} posts on this account"
                ),
                "code": "shared_tracking_code",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen_f: set[tuple[str, str, str]] = set()
    for row in flagged:
        key = (str(row.get("id") or ""), str(row.get("code") or ""), str(row.get("url") or ""))
        if key in seen_f:
            continue
        seen_f.add(key)
        deduped.append(row)

    severities = []
    for row in deduped:
        code = row.get("code") or ""
        if code == "blocklisted_hop":
            severities.append("BLOCK")
        elif code in {
            "tracking_param",
            "tracking_token",
            "campaign_code",
            "shared_tracking_code",
            "intermediate_hop",
        }:
            severities.append("WARN")
    verdict = worst_severity(*severities) if severities else Severity.OK

    return {
        "verdict": verdict.value,
        "exit_code": EXIT_CODES[verdict],
        "flagged_posts": deduped,
        "clean_urls": clean_urls,
        "shared_codes": shared_codes,
        "post_count": len(state.get("post_ids") or []),
    }

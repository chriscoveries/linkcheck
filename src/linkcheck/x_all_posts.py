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
MIN_PAGE_SIZE = 10


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
    max_results: int = MAX_RESULTS,
) -> dict[str, Any]:
    user = username.lstrip("@")
    n = max(MIN_PAGE_SIZE, min(int(max_results), MAX_RESULTS))
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
        "max_results": n,
        "done": False,
        "mode": "full",
        "next_token": None,
        "until_id": None,
        "page_incomplete": False,
        "saw_truncation": False,
        "newest_id": None,
        "checkpoint_newest_id": None,
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


def estimate_reads(post_count: int, page_size: int = MAX_RESULTS) -> dict[str, int]:
    size = max(MIN_PAGE_SIZE, int(page_size) or MAX_RESULTS)
    pages = (max(0, int(post_count)) + size - 1) // size if post_count else 0
    return {"posts_with_links": int(post_count), "reads": pages, "page_size": size}


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
    max_results: int | None = None,
) -> dict[str, Any]:
    state = load_state(state_path, username=username)
    user = (username or state.get("username") or "").lstrip("@")
    if not user:
        raise ValueError("all-posts requires --username")

    query = link_account_query(
        user, include_reposts=include_reposts, exclude_replies=exclude_replies
    )
    state["username"] = user
    state["query"] = query
    state["include_reposts"] = include_reposts
    state["exclude_replies"] = exclude_replies
    state["with_text"] = with_text
    if max_results is not None and not state.get("page_incomplete"):
        # Don't override an active post-truncation halved size unless explicit and not incomplete
        state["max_results"] = max(MIN_PAGE_SIZE, min(int(max_results), MAX_RESULTS))
    elif "max_results" not in state:
        state["max_results"] = MAX_RESULTS

    if full:
        state = empty_state(
            user,
            include_reposts=include_reposts,
            exclude_replies=exclude_replies,
            with_text=with_text,
            max_results=max_results if max_results is not None else MAX_RESULTS,
        )
        state["mode"] = "full"
    elif (
        incremental
        and state.get("done")
        and state.get("newest_id")
        and not state.get("next_token")
        and not state.get("page_incomplete")
    ):
        state["done"] = False
        state["mode"] = "incremental"
        state["checkpoint_newest_id"] = state["newest_id"]
        state["next_token"] = None
        state["until_id"] = None
        state["page_incomplete"] = False
        state["pages"] = 0
        state["report"] = None
    elif state.get("done") and not state.get("page_incomplete"):
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
            read_estimate=estimate_reads(
                len(state.get("post_ids") or []), state.get("max_results") or MAX_RESULTS
            ),
        )

    # Never treat incomplete/truncated work as finished
    if state.get("page_incomplete") or state.get("saw_truncation"):
        state["done"] = False

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
    if (
        preflight
        and int(state.get("pages") or 0) == 0
        and not state.get("next_token")
        and not state.get("until_id")
        and not state.get("page_incomplete")
    ):
        calls.append(
            mcp_call(
                "get_posts_counts_recent",
                {"query": query, "granularity": "day"},
            )
        )

    page_size = max(MIN_PAGE_SIZE, min(int(state.get("max_results") or MAX_RESULTS), MAX_RESULTS))
    next_token = state.get("next_token") or None
    until_id = None if next_token else (state.get("until_id") or None)
    since_id = None
    if (
        state.get("mode") == "incremental"
        and state.get("checkpoint_newest_id")
        and not next_token
        and not until_id
    ):
        since_id = str(state["checkpoint_newest_id"])

    args = link_search_args(
        query,
        next_token=next_token,
        since_id=since_id,
        until_id=str(until_id) if until_id else None,
        with_text=with_text,
        max_results=page_size,
    )
    calls.append(mcp_call("search_posts_all", args))

    read_estimate = {
        "page_size": page_size,
        "formula": "ceil(posts_with_links / page_size) = reads",
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
        page_incomplete=bool(state.get("page_incomplete")),
    )


def _parse_payload(raw: str) -> tuple[dict[str, Any] | None, dict[str, Any], bool]:
    """Return (root_or_None, meta, complete). complete means full JSON parse succeeded."""
    text = strip_wrappers(raw)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
            return obj, meta, True
        return None, {}, True
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(text)
            if isinstance(obj, dict):
                # raw_decode without consuming all input ⇒ incomplete wrapper/body
                meta = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
                # If trailing junk remains after decode, treat as incomplete
                return obj, meta, False
        except json.JSONDecodeError:
            pass
        return None, {}, False


def _slim_post(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(post.get("id") or ""),
        "created_at": post.get("created_at"),
        "urls": list(post.get("urls") or []),
    }


def _halve_page_size(current: int) -> int:
    return max(MIN_PAGE_SIZE, int(current) // 2)


def append_page(
    raw: str,
    state_path: Path,
    *,
    offline: bool = True,
) -> dict[str, Any]:
    """Merge one search_posts_all page into state. Idempotent by post id."""
    del offline
    state = load_state(state_path)
    if state.get("done") and not state.get("page_incomplete") and not state.get("next_token"):
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
    posts, truncated_extract = extract_posts(raw)
    root, meta, complete = _parse_payload(raw)
    truncated = truncated_extract or (not complete)
    # Missing meta on a truncated body is the critical host-cutoff case
    if truncated:
        meta = meta if meta else {}

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

    # Newest id
    all_numeric: list[int] = []
    for pid in ids:
        try:
            all_numeric.append(int(pid))
        except ValueError:
            continue
    if all_numeric:
        state["newest_id"] = str(max(all_numeric))

    result_count = meta.get("result_count")
    next_token = meta.get("next_token")
    has_meta = bool(meta) or (
        complete and isinstance(root, dict) and "meta" in root
    )

    if truncated:
        # Never finish on truncated input — continue via until_id + smaller page
        state["done"] = False
        state["page_incomplete"] = True
        state["saw_truncation"] = True
        state["next_token"] = None
        cur = int(state.get("max_results") or MAX_RESULTS)
        state["max_results"] = _halve_page_size(cur)
        page_numeric = []
        for pid in page_ids:
            try:
                page_numeric.append(int(pid))
            except ValueError:
                continue
        if page_numeric:
            state["until_id"] = str(min(page_numeric) - 1)
        # else: keep prior until_id / retry same window at smaller size
    else:
        state["page_incomplete"] = False
        if isinstance(next_token, str) and next_token.strip():
            state["next_token"] = next_token.strip()
            state["until_id"] = None
            state["done"] = False
        elif result_count == 0 or (has_meta and not next_token):
            # Complete response: meta present with no next_token, or empty result
            state["next_token"] = None
            state["until_id"] = None
            state["done"] = True
        elif not has_meta and len(posts) == 0:
            state["next_token"] = None
            state["until_id"] = None
            state["done"] = True
        else:
            # Complete but ambiguous — do not silently clear
            state["done"] = False
            if not next_token:
                state["next_token"] = None

    out: dict[str, Any] = {
        "playbook": "all-posts",
        "done": bool(state.get("done")),
        "added": added,
        "post_count": len(ids),
        "pages": state["pages"],
        "next_token": state.get("next_token"),
        "until_id": state.get("until_id"),
        "truncated": truncated,
        "page_incomplete": bool(state.get("page_incomplete")),
        "max_results": state.get("max_results"),
        "read_estimate": estimate_reads(len(ids), state.get("max_results") or MAX_RESULTS),
    }

    if truncated:
        out["verdict"] = "WARN"
        out["exit_code"] = 1
        out["reasons"] = [
            {
                "severity": "WARN",
                "code": "input_truncated",
                "message": (
                    f"Page truncated; recovered {len(page_ids)} post(s). "
                    f"Will continue with until_id={state.get('until_id')!r} "
                    f"max_results={state.get('max_results')}"
                ),
            }
        ]
    elif state.get("done"):
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

    if state.get("saw_truncation") or state.get("page_incomplete"):
        flagged.append(
            {
                "id": "",
                "url": "",
                "reason": "One or more MCP pages were truncated during the scan",
                "code": "input_truncated",
            }
        )

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
            "input_truncated",
        }:
            severities.append("WARN")
    verdict = worst_severity(*severities) if severities else Severity.OK
    # Truncation during the scan must never yield a silent OK final report
    if state.get("saw_truncation") and verdict == Severity.OK:
        verdict = Severity.WARN

    return {
        "verdict": verdict.value,
        "exit_code": EXIT_CODES[verdict],
        "flagged_posts": deduped,
        "clean_urls": clean_urls,
        "shared_codes": shared_codes,
        "post_count": len(state.get("post_ids") or []),
    }

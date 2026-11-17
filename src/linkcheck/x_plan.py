"""Build deterministic, ordered X MCP call plans for agents to run verbatim."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .tracking import extract_tracking_codes
from .urls import extract_urls
from .x_api import (
    MAX_CALLS_PER_PLAN,
    MAX_RESULTS,
    POST_FIELDS,
    USER_FIELDS,
    EXPANSIONS,
    finalize_plan,
    from_ref,
    mcp_call,
    search_posts_args,
)

PLAYBOOKS = ("own-posts", "shared-code", "shared-script", "cluster")

_TOKEN_RE = re.compile(r"\b([a-f0-9]{8}|[A-Za-z0-9_-]{16,})\b")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")
_WORD_RE = re.compile(r"[a-z0-9]+", re.I)

MIN_PHRASE_WORDS = 5
MAX_PHRASE_CALLS = 5


def extract_codes_from_text(text: str) -> list[str]:
    """Stable-ordered unique tracking codes / opaque tokens from draft URLs and text."""
    found: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        v = (value or "").strip()
        if not v or v in seen:
            return
        seen.add(v)
        found.append(v)

    for url in extract_urls(text or ""):
        for _key, val in extract_tracking_codes(url):
            add(val)
        try:
            qs = parse_qs(urlparse(url).query, keep_blank_values=False)
        except ValueError:
            qs = {}
        for values in qs.values():
            for val in values:
                if _TOKEN_RE.fullmatch(val or ""):
                    add(val)

    for match in _TOKEN_RE.finditer(text or ""):
        add(match.group(1))

    return sorted(found)


def extract_distinctive_phrases(text: str, *, limit: int = MAX_PHRASE_CALLS) -> list[str]:
    """Exact phrases for search_posts_all. Longer first, then lexicographic; stable."""
    cleaned = re.sub(r"https?://\S+", " ", text or "")
    cleaned = re.sub(r"@\w+", " ", cleaned)
    cleaned = re.sub(r"#\w+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []

    candidates: list[str] = []
    for raw in _SENTENCE_RE.findall(cleaned):
        phrase = raw.strip(" \t\n\r\"'()[]{}")
        words = _WORD_RE.findall(phrase)
        if len(words) >= MIN_PHRASE_WORDS:
            candidates.append(" ".join(words).lower())

    words_all = _WORD_RE.findall(cleaned)
    if len(words_all) >= MIN_PHRASE_WORDS and not candidates:
        for i in range(0, len(words_all) - MIN_PHRASE_WORDS + 1, MIN_PHRASE_WORDS):
            window = words_all[i : i + MIN_PHRASE_WORDS + 2]
            if len(window) >= MIN_PHRASE_WORDS:
                candidates.append(" ".join(window).lower())

    uniq: list[str] = []
    seen: set[str] = set()
    for phrase in sorted(candidates, key=lambda p: (-len(p.split()), p)):
        if phrase in seen:
            continue
        if any(phrase in other for other in uniq):
            continue
        seen.add(phrase)
        uniq.append(phrase)
        if len(uniq) >= limit:
            break
    return uniq


def plan_own_posts(
    *,
    username: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    if not username and not user_id:
        raise ValueError("own-posts requires --username or --user-id")

    calls: list[dict[str, Any]] = []
    if username and not user_id:
        calls.append(
            mcp_call(
                "get_users_by_username",
                {
                    "username": username.lstrip("@"),
                    "user.fields": list(USER_FIELDS),
                },
            )
        )
        calls.append(
            mcp_call(
                "get_users_posts",
                {
                    "id": from_ref("step1.data.id"),
                    "max_results": MAX_RESULTS,
                    "post.fields": list(POST_FIELDS),
                    "expansions": list(EXPANSIONS),
                    "user.fields": list(USER_FIELDS),
                },
            )
        )
    else:
        calls.append(
            mcp_call(
                "get_users_posts",
                {
                    "id": str(user_id),
                    "max_results": MAX_RESULTS,
                    "post.fields": list(POST_FIELDS),
                    "expansions": list(EXPANSIONS),
                    "user.fields": list(USER_FIELDS),
                },
            )
        )
    return finalize_plan("own-posts", calls)


def plan_shared_code(
    *,
    text: str = "",
    codes: list[str] | None = None,
) -> dict[str, Any]:
    values = list(codes or [])
    if text:
        for code in extract_codes_from_text(text):
            if code not in values:
                values.append(code)
    values = sorted(set(values))[:MAX_CALLS_PER_PLAN]
    calls = [
        mcp_call("search_posts_all", search_posts_args(f'"{code}"'))
        for code in values
    ]
    return finalize_plan("shared-code", calls, codes=values)


def plan_shared_script(*, text: str) -> dict[str, Any]:
    phrases = extract_distinctive_phrases(text)[:MAX_CALLS_PER_PLAN]
    calls = [
        mcp_call("search_posts_all", search_posts_args(f'"{phrase}"'))
        for phrase in phrases
    ]
    return finalize_plan("shared-script", calls, phrases=phrases)


def plan_cluster(
    *,
    query: str,
    start_time: str,
    end_time: str | None = None,
    since_id: str | None = None,
    until_id: str | None = None,
) -> dict[str, Any]:
    if not query:
        raise ValueError("cluster requires --query")
    if not start_time and not since_id:
        raise ValueError("cluster requires --start-time or --since-id")
    calls = [
        mcp_call(
            "search_posts_all",
            search_posts_args(
                query,
                start_time=start_time or None,
                end_time=end_time,
                since_id=since_id,
                until_id=until_id,
                sort_order="recency",
            ),
        )
    ]
    return finalize_plan("cluster", calls)


def build_plan(playbook: str, **kwargs: Any) -> dict[str, Any]:
    if playbook not in PLAYBOOKS:
        known = ", ".join(PLAYBOOKS)
        raise KeyError(f"unknown x-plan playbook {playbook!r}; known: {known}")
    if playbook == "own-posts":
        return plan_own_posts(
            username=kwargs.get("username"),
            user_id=kwargs.get("user_id"),
        )
    if playbook == "shared-code":
        return plan_shared_code(text=kwargs.get("text") or "", codes=kwargs.get("codes"))
    if playbook == "shared-script":
        text = kwargs.get("text") or ""
        if not text:
            raise ValueError("shared-script requires --file or --text")
        return plan_shared_script(text=text)
    return plan_cluster(
        query=kwargs.get("query") or "",
        start_time=kwargs.get("start_time") or "",
        end_time=kwargs.get("end_time"),
        since_id=kwargs.get("since_id"),
        until_id=kwargs.get("until_id"),
    )


def _lookup_path(root: Any, path: str) -> Any:
    """Resolve dotted path like step1.data.id against a step outputs map."""
    parts = path.split(".")
    if not parts:
        raise KeyError("empty $from path")
    cur: Any = root
    for part in parts:
        if isinstance(cur, dict):
            if part not in cur:
                # X user lookup sometimes nests as data: {id: ...}
                raise KeyError(f"missing {part!r} while resolving {path!r}")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError) as exc:
                raise KeyError(f"bad index {part!r} in {path!r}") from exc
        else:
            raise KeyError(f"cannot resolve {part!r} on {type(cur).__name__} for {path!r}")
    return cur


def _replace_from(value: Any, outputs: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        if set(value.keys()) == {"$from"} and isinstance(value["$from"], str):
            path = value["$from"]
            # path is stepN.... — first segment selects the step output
            resolved = _lookup_path(outputs, path)
            return resolved
        return {k: _replace_from(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_from(v, outputs) for v in value]
    return value


def load_step_outputs(raw: str | dict | list) -> dict[str, Any]:
    """Accept {step1: {...}, ...}, a list (→ step1..), or a single object (→ step1)."""
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    if isinstance(data, dict) and any(str(k).startswith("step") for k in data):
        return {str(k): v for k, v in data.items()}
    if isinstance(data, list):
        return {f"step{i + 1}": item for i, item in enumerate(data)}
    if isinstance(data, dict):
        return {"step1": data}
    raise ValueError("outputs must be an object, list, or step-keyed map")


def resolve_plan(plan: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    """Substitute {$from: stepN...} placeholders using prior step outputs."""
    calls_in = plan.get("calls") or []
    calls_out: list[dict[str, Any]] = []
    for call in calls_in:
        new_call = {
            "namespace": call["namespace"],
            "tool": call["tool"],
            "arguments": _replace_from(call.get("arguments") or {}, outputs),
        }
        calls_out.append(new_call)
    out = dict(plan)
    out["calls"] = calls_out
    out["resolved"] = True
    return out


def resolve_plan_files(plan_path: Path, outputs_path: Path) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    outputs = load_step_outputs(outputs_path.read_text(encoding="utf-8"))
    return resolve_plan(plan, outputs)

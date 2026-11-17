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
    finalize_plan,
    link_account_query,
    link_search_args,
    mcp_call,
    search_posts_args,
)
from .x_ingest import strip_wrappers

PLAYBOOKS = ("own-posts", "shared-code", "shared-script", "cluster", "all-posts")

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
    max_results: int | None = None,
    include_reposts: bool = False,
    exclude_replies: bool = False,
    with_text: bool = False,
    preflight: bool = False,
) -> dict[str, Any]:
    """Recent link posts only via search_posts_all (never pages link-less posts)."""
    del max_results  # always 25 for link reads
    if not username and not user_id:
        raise ValueError("own-posts requires --username (preferred) or --user-id")
    if not username:
        # user_id alone cannot build from: query; keep a minimal resolve+posts path unused
        raise ValueError("own-posts link scan requires --username for from: query")

    query = link_account_query(
        username, include_reposts=include_reposts, exclude_replies=exclude_replies
    )
    calls: list[dict[str, Any]] = []
    if preflight:
        calls.append(
            mcp_call(
                "get_posts_counts_recent",
                {"query": query, "granularity": "day"},
            )
        )
    calls.append(
        mcp_call(
            "search_posts_all",
            link_search_args(query, with_text=with_text),
        )
    )
    return finalize_plan(
        "own-posts",
        calls,
        query=query,
        read_estimate={
            "page_size": MAX_RESULTS,
            "formula": "ceil(posts_with_links / 25) = reads",
            "this_plan_reads": 1,
        },
    )


def plan_shared_code(
    *,
    text: str = "",
    codes: list[str] | None = None,
    max_results: int | None = None,
) -> dict[str, Any]:
    values = list(codes or [])
    if text:
        for code in extract_codes_from_text(text):
            if code not in values:
                values.append(code)
    values = sorted(set(values))[:MAX_CALLS_PER_PLAN]
    calls = [
        mcp_call(
            "search_posts_all",
            search_posts_args(f'"{code}"', max_results=max_results),
        )
        for code in values
    ]
    return finalize_plan("shared-code", calls, codes=values)


def plan_shared_script(*, text: str, max_results: int | None = None) -> dict[str, Any]:
    phrases = extract_distinctive_phrases(text)[:MAX_CALLS_PER_PLAN]
    calls = [
        mcp_call(
            "search_posts_all",
            search_posts_args(f'"{phrase}"', max_results=max_results),
        )
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
    max_results: int | None = None,
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
                max_results=max_results,
            ),
        )
    ]
    return finalize_plan("cluster", calls)


def build_plan(playbook: str, **kwargs: Any) -> dict[str, Any]:
    if playbook not in PLAYBOOKS:
        known = ", ".join(PLAYBOOKS)
        raise KeyError(f"unknown x-plan playbook {playbook!r}; known: {known}")
    max_results = kwargs.get("max_results")
    if playbook == "own-posts":
        return plan_own_posts(
            username=kwargs.get("username"),
            user_id=kwargs.get("user_id"),
            max_results=max_results,
            include_reposts=bool(kwargs.get("include_reposts")),
            exclude_replies=bool(kwargs.get("exclude_replies")),
            with_text=bool(kwargs.get("with_text")),
            preflight=bool(kwargs.get("preflight")),
        )
    if playbook == "shared-code":
        return plan_shared_code(
            text=kwargs.get("text") or "",
            codes=kwargs.get("codes"),
            max_results=max_results,
        )
    if playbook == "shared-script":
        text = kwargs.get("text") or ""
        if not text:
            raise ValueError("shared-script requires --file or --text")
        return plan_shared_script(text=text, max_results=max_results)
    if playbook == "all-posts":
        from .x_all_posts import plan_all_posts

        state_path = kwargs.get("state_path")
        if state_path is None:
            raise ValueError("all-posts requires --state")
        return plan_all_posts(
            username=kwargs.get("username"),
            state_path=Path(state_path),
            include_reposts=bool(kwargs.get("include_reposts")),
            exclude_replies=bool(kwargs.get("exclude_replies")),
            with_text=bool(kwargs.get("with_text")),
            preflight=bool(kwargs.get("preflight")),
            full=bool(kwargs.get("full")),
            incremental=bool(kwargs.get("incremental")),
            max_results=max_results,
        )
    return plan_cluster(
        query=kwargs.get("query") or "",
        start_time=kwargs.get("start_time") or "",
        end_time=kwargs.get("end_time"),
        since_id=kwargs.get("since_id"),
        until_id=kwargs.get("until_id"),
        max_results=max_results,
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


def _parse_one_output_blob(raw: str) -> Any:
    """Parse one saved tool-output blob (XML tags / fences / footers OK)."""
    text = strip_wrappers(raw)
    if not text:
        raise ValueError("empty step output after stripping wrappers")
    # strip_wrappers already starts at first { or [; raw_decode tolerates trailing junk
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(text)
        return obj
    except json.JSONDecodeError:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"could not parse step output JSON: {exc}") from exc


def load_step_outputs(raw: str | dict | list) -> dict[str, Any]:
    """Accept {step1: {...}}, a list (→ step1..), a single object (→ step1), or fenced raw."""
    if isinstance(raw, (dict, list)):
        data = raw
    else:
        data = _parse_one_output_blob(raw)
    if isinstance(data, dict) and any(str(k).startswith("step") for k in data):
        return {str(k): v for k, v in data.items()}
    if isinstance(data, list):
        return {f"step{i + 1}": item for i, item in enumerate(data)}
    if isinstance(data, dict):
        return {"step1": data}
    raise ValueError("outputs must be an object, list, or step-keyed map")


def load_step_outputs_from_paths(paths: list[Path]) -> dict[str, Any]:
    """
    Load prior step outputs from one or more files.

    - One file that is already {step1: ...} / a list → use that map.
    - One or more raw tool-output files (fenced OK) → step1, step2, … in order.
    """
    if not paths:
        raise ValueError("--outputs requires at least one file")
    if len(paths) == 1:
        return load_step_outputs(paths[0].read_text(encoding="utf-8"))
    out: dict[str, Any] = {}
    for i, path in enumerate(paths):
        out[f"step{i + 1}"] = _parse_one_output_blob(path.read_text(encoding="utf-8"))
    return out


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


def resolve_plan_files(plan_path: Path, outputs_paths: Path | list[Path]) -> dict[str, Any]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if isinstance(outputs_paths, Path):
        paths = [outputs_paths]
    else:
        paths = list(outputs_paths)
    outputs = load_step_outputs_from_paths(paths)
    return resolve_plan(plan, outputs)

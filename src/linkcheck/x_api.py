"""Fixed X MCP tool field lists and call shapes (deterministic, agent-copyable)."""

from __future__ import annotations

from typing import Any

# Namespace every bot's X MCP server uses (CallDynamicTool namespace:"x").
X_NAMESPACE = "x"

# Cap results per call (tool max for this runtime contract).
MAX_RESULTS = 25
# Default for legacy get_users_posts paths (search_posts_all min is 10).
DEFAULT_OWN_POSTS_MAX_RESULTS = 10
MIN_RESULTS = 5

# Rate limits the consumer must respect; plans never exceed max_calls_per_plan.
RATE_PER_MINUTE = 30
RATE_PER_DAY_UTC = 1000
MAX_CALLS_PER_PLAN = 30

# Minimal payload for link scans — entities.urls carries expanded_url.
LINK_POST_FIELDS: list[str] = [
    "id",
    "created_at",
    "entities",
]
LINK_POST_FIELDS_WITH_TEXT: list[str] = [
    "id",
    "created_at",
    "entities",
    "text",
]

# Broader field sets kept for shared-code / cluster / shared-script searches.
POST_FIELDS: list[str] = [
    "id",
    "text",
    "entities",
    "created_at",
    "author_id",
]
USER_FIELDS: list[str] = [
    "id",
    "username",
    "name",
]
EXPANSIONS: list[str] = [
    "author_id",
]

# Read-only tools only — never plan create/delete/post.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "get_users_by_username",
        "get_users_by_usernames",
        "get_users_by_id",
        "get_users_posts",
        "get_users_mentions",
        "get_posts_by_id",
        "get_posts_by_ids",
        "get_posts_quoted_posts",
        "get_posts_reposted_by",
        "get_posts_counts_recent",
        "search_posts_all",
        "search_news",
        "get_trends_by_woeid",
    }
)


def from_ref(path: str) -> dict[str, str]:
    """Placeholder: agent / x-plan --resolve fills this from a prior step output."""
    return {"$from": path}


def mcp_call(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """One ordered MCP call. Exact shape: {namespace, tool, arguments}."""
    if tool not in READ_ONLY_TOOLS:
        raise ValueError(f"refusing non-read-only X tool: {tool}")
    return {
        "namespace": X_NAMESPACE,
        "tool": tool,
        "arguments": arguments,
    }


def clamp_max_results(value: int | None, *, default: int = MAX_RESULTS) -> int:
    n = default if value is None else int(value)
    return max(MIN_RESULTS, min(n, MAX_RESULTS))


def link_account_query(
    username: str,
    *,
    include_reposts: bool = False,
    exclude_replies: bool = False,
) -> str:
    """Only posts that contain links. Default excludes retweets."""
    parts = [f"from:{username.lstrip('@')}", "has:links"]
    if not include_reposts:
        parts.append("-is:retweet")
    if exclude_replies:
        parts.append("-is:reply")
    return " ".join(parts)


def link_search_args(
    query: str,
    *,
    next_token: str | None = None,
    since_id: str | None = None,
    until_id: str | None = None,
    with_text: bool = False,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Minimal search_posts_all args: no expansions, no user.fields."""
    # search_posts_all minimum is 10; cap at 25
    n = MAX_RESULTS if max_results is None else int(max_results)
    n = max(10, min(n, MAX_RESULTS))
    args: dict[str, Any] = {
        "query": query,
        "max_results": n,
        "sort_order": "recency",
        "post.fields": list(LINK_POST_FIELDS_WITH_TEXT if with_text else LINK_POST_FIELDS),
    }
    if next_token is not None:
        args["next_token"] = next_token
    if since_id is not None:
        args["since_id"] = since_id
    if until_id is not None:
        args["until_id"] = until_id
    return args


def search_posts_args(
    query: str,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
    since_id: str | None = None,
    until_id: str | None = None,
    next_token: str | None = None,
    sort_order: str = "recency",
    max_results: int | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "query": query,
        "max_results": clamp_max_results(max_results, default=MAX_RESULTS),
        "sort_order": sort_order,
        "post.fields": list(POST_FIELDS),
        "user.fields": list(USER_FIELDS),
        "expansions": list(EXPANSIONS),
    }
    if start_time is not None:
        args["start_time"] = start_time
    if end_time is not None:
        args["end_time"] = end_time
    if since_id is not None:
        args["since_id"] = since_id
    if until_id is not None:
        args["until_id"] = until_id
    if next_token is not None:
        args["next_token"] = next_token
    return args


def limits_block() -> dict[str, int]:
    return {
        "max_results": MAX_RESULTS,
        "max_calls_per_plan": MAX_CALLS_PER_PLAN,
        "rate_per_minute": RATE_PER_MINUTE,
        "rate_per_day_utc": RATE_PER_DAY_UTC,
    }


def finalize_plan(playbook: str, calls: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    if len(calls) > MAX_CALLS_PER_PLAN:
        calls = calls[:MAX_CALLS_PER_PLAN]
    for call in calls:
        args = call.get("arguments") or {}
        if "max_results" in args:
            args["max_results"] = min(int(args["max_results"]), MAX_RESULTS)
    body: dict[str, Any] = {
        "playbook": playbook,
        "call_count": len(calls),
        "limits": limits_block(),
        "read_only": True,
        "calls": calls,
    }
    for key, value in extra.items():
        if value is not None:
            body[key] = value
    return body

"""Optional: poll the creator's own recent posts via X API v2."""

from __future__ import annotations

import os
from typing import Any

import requests

from .check import run_check


def monitor_user(user_id: str, *, max_results: int = 10) -> dict[str, Any]:
    token = os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN")
    if not token:
        return {
            "exit_code": 1,
            "message": "Set X_BEARER_TOKEN (or TWITTER_BEARER_TOKEN) to use monitor.",
            "posts": [],
        }

    url = f"https://api.x.com/2/users/{user_id}/tweets"
    try:
        resp = requests.get(
            url,
            params={
                "max_results": max(5, min(max_results, 100)),
                "tweet.fields": "created_at,text",
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        return {"exit_code": 1, "message": f"X API request failed: {exc}", "posts": []}

    if resp.status_code != 200:
        return {
            "exit_code": 1,
            "message": f"X API HTTP {resp.status_code}: {resp.text[:300]}",
            "posts": [],
        }

    posts_out: list[dict[str, Any]] = []
    worst = 0
    for item in resp.json().get("data") or []:
        text = item.get("text") or ""
        result = run_check(text, check_age=False)
        worst = max(worst, result.exit_code)
        if result.verdict != "OK":
            posts_out.append(
                {
                    "id": item.get("id"),
                    "verdict": result.verdict,
                    "exit_code": result.exit_code,
                    "text_excerpt": result.text_excerpt,
                    "reasons": [r.to_dict() for r in result.reasons],
                }
            )

    return {
        "exit_code": worst,
        "message": f"Checked posts; {len(posts_out)} had WARN/BLOCK",
        "posts": posts_out,
    }

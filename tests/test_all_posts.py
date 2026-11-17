"""Fixture tests for all-posts / own-posts link-only plans (golden query + fields)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from linkcheck.cli import main
from linkcheck.x_all_posts import append_page, load_state, plan_all_posts, rate_limit_wait, record_call
from linkcheck.x_api import LINK_POST_FIELDS, MAX_RESULTS, RATE_PER_MINUTE
from linkcheck.x_plan import build_plan

FIXTURES = Path(__file__).parent / "fixtures" / "x_mcp"

OWN_POSTS_GOLDEN_ARGS = {
    "query": "from:operator has:links -is:retweet",
    "max_results": 25,
    "sort_order": "recency",
    "post.fields": ["id", "created_at", "entities"],
}


def test_own_posts_golden_query_and_fields():
    plan = build_plan("own-posts", username="operator")
    assert plan["call_count"] == 1
    call = plan["calls"][0]
    assert set(call.keys()) == {"namespace", "tool", "arguments"}
    assert call["namespace"] == "x"
    assert call["tool"] == "search_posts_all"
    assert call["arguments"] == OWN_POSTS_GOLDEN_ARGS
    assert "expansions" not in call["arguments"]
    assert "user.fields" not in call["arguments"]
    assert "text" not in call["arguments"]["post.fields"]


def test_own_posts_flags_reposts_replies_text_preflight():
    plan = build_plan(
        "own-posts",
        username="operator",
        include_reposts=True,
        exclude_replies=True,
        with_text=True,
        preflight=True,
    )
    assert plan["call_count"] == 2
    assert plan["calls"][0]["tool"] == "get_posts_counts_recent"
    assert plan["calls"][0]["arguments"]["query"] == "from:operator has:links -is:reply"
    search = plan["calls"][1]
    assert search["arguments"]["query"] == "from:operator has:links -is:reply"
    assert search["arguments"]["post.fields"] == ["id", "created_at", "entities", "text"]


def test_all_posts_plan_golden_first_page(tmp_path):
    state = tmp_path / "state.json"
    plan = plan_all_posts(username="operator", state_path=state)
    assert plan["playbook"] == "all-posts"
    assert plan["done"] is False
    assert plan["query"] == "from:operator has:links -is:retweet"
    assert plan["call_count"] == 1
    call = plan["calls"][0]
    assert call["tool"] == "search_posts_all"
    assert call["arguments"] == OWN_POSTS_GOLDEN_ARGS
    assert "next_token" not in call["arguments"]


def test_all_posts_paging_resume_dedupe_incremental(tmp_path):
    state = tmp_path / "state.json"
    plan_all_posts(username="operator", state_path=state)

    page1 = (FIXTURES / "all_posts_page1.json").read_text(encoding="utf-8")
    out1 = append_page(page1, state)
    assert out1["done"] is False
    assert out1["added"] == 3
    assert out1["next_token"] == "page2token"
    # State stores slim posts only
    body = json.loads(state.read_text(encoding="utf-8"))
    sample = body["posts"]["1003"]
    assert set(sample.keys()) == {"id", "created_at", "urls"}
    assert "text" not in sample

    plan2 = plan_all_posts(username="operator", state_path=state)
    assert plan2["calls"][0]["arguments"]["next_token"] == "page2token"
    assert plan2["calls"][0]["arguments"]["post.fields"] == LINK_POST_FIELDS
    assert plan2["calls"][0]["arguments"]["max_results"] == MAX_RESULTS

    page2 = (FIXTURES / "all_posts_page2.json").read_text(encoding="utf-8")
    out2 = append_page(page2, state)
    assert out2["added"] == 1
    assert out2["post_count"] == 4
    assert out2["done"] is True
    assert out2["report"]["shared_codes"]
    assert all("t.co" not in u for u in out2["report"]["clean_urls"])

    # Re-append idempotent
    assert append_page(page2, state)["added"] == 0

    # Completed scan: plan returns done until --incremental
    plan_done = plan_all_posts(username="operator", state_path=state)
    assert plan_done["done"] is True
    assert plan_done["call_count"] == 0

    # Incremental: since_id=newest_id
    plan_inc = plan_all_posts(username="operator", state_path=state, incremental=True)
    assert plan_inc["done"] is False
    assert plan_inc["mode"] == "incremental"
    assert plan_inc["calls"][0]["arguments"]["since_id"] == "1003"
    assert "next_token" not in plan_inc["calls"][0]["arguments"]


def test_all_posts_rate_limit_wait_until(tmp_path):
    state_path = tmp_path / "state.json"
    plan_all_posts(username="operator", state_path=state_path)
    state = load_state(state_path)
    wall = datetime.now(timezone.utc)
    state["call_timestamps"] = [
        (wall - timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(RATE_PER_MINUTE)
    ]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    assert rate_limit_wait(load_state(state_path)) is not None
    capped = plan_all_posts(username="operator", state_path=state_path)
    assert capped["call_count"] == 0
    assert capped.get("wait_until")


def test_cli_all_posts_loop(tmp_path):
    state = tmp_path / "state.json"
    assert main(["x-plan", "all-posts", "--username", "operator", "--state", str(state), "--json"]) == 0
    assert main(["x-ingest", "--file", str(FIXTURES / "all_posts_page1.json"), "--append", str(state), "--json"]) == 0
    code = main(["x-ingest", "--file", str(FIXTURES / "all_posts_page2.json"), "--append", str(state), "--json"])
    assert code in (0, 1, 2)
    body = json.loads(state.read_text(encoding="utf-8"))
    assert body["done"] is True
    assert len(body["post_ids"]) == 4


def test_all_posts_truncated_page_never_done_uses_until_id(tmp_path):
    """Host cutoff loses meta/next_token — must not silent-OK / done after partial recover."""
    state = tmp_path / "state.json"
    plan_all_posts(username="operator", state_path=state, max_results=25)

    raw = (FIXTURES / "all_posts_truncated_page.json").read_text(encoding="utf-8")
    assert "[... 6124 bytes from" in raw
    out = append_page(raw, state)

    assert out["truncated"] is True
    assert out["done"] is False
    assert out["verdict"] == "WARN"
    assert out["exit_code"] == 1
    assert any(r["code"] == "input_truncated" for r in out.get("reasons") or [])
    assert out["added"] >= 2
    # smallest recovered id among complete posts is 2001 → until_id 2000
    assert out["until_id"] == "2000"
    assert out["max_results"] == 12  # 25 // 2
    assert out["next_token"] is None

    body = json.loads(state.read_text(encoding="utf-8"))
    assert body["done"] is False
    assert body["page_incomplete"] is True
    assert body["saw_truncation"] is True
    assert body["until_id"] == "2000"
    assert body["max_results"] == 12

    nxt = plan_all_posts(username="operator", state_path=state)
    assert nxt["done"] is False
    assert nxt["call_count"] == 1
    args = nxt["calls"][0]["arguments"]
    assert args["until_id"] == "2000"
    assert args["max_results"] == 12
    assert "next_token" not in args
    assert args["query"] == "from:operator has:links -is:retweet"
    assert args["post.fields"] == ["id", "created_at", "entities"]

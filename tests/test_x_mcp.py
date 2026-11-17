"""Fixture-based tests for x-plan / x-ingest (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from linkcheck.cli import main
from linkcheck.x_ingest import extract_posts, ingest_to_dict, run_ingest, strip_wrappers
from linkcheck.x_plan import build_plan, resolve_plan, resolve_plan_files

FIXTURES = Path(__file__).parent / "fixtures" / "x_mcp"


def test_x_plan_own_posts_shape_and_from_placeholder():
    plan = build_plan("own-posts", username="operator")
    assert plan["call_count"] == 2
    assert plan["read_only"] is True
    assert plan["limits"]["max_results"] == 25
    assert plan["limits"]["max_calls_per_plan"] == 30
    assert len(plan["calls"]) == 2
    step1, step2 = plan["calls"]
    assert set(step1.keys()) == {"namespace", "tool", "arguments"}
    assert step1["namespace"] == "x"
    assert step1["tool"] == "get_users_by_username"
    assert isinstance(step1["arguments"]["user.fields"], list)
    assert step2["tool"] == "get_users_posts"
    assert step2["arguments"]["id"] == {"$from": "step1.data.id"}
    assert step2["arguments"]["max_results"] == 10  # default own-posts
    assert isinstance(step2["arguments"]["post.fields"], list)
    assert "entities" in step2["arguments"]["post.fields"]


def test_x_plan_own_posts_max_results_flag():
    plan = build_plan("own-posts", user_id="99", max_results=25)
    assert plan["calls"][0]["arguments"]["max_results"] == 25
    plan_hi = build_plan("own-posts", user_id="99", max_results=100)
    assert plan_hi["calls"][0]["arguments"]["max_results"] == 25


def test_x_plan_resolve_substitutes_from():
    plan = build_plan("own-posts", username="operator")
    outputs = {"step1": {"data": {"id": "99", "username": "operator"}}}
    resolved = resolve_plan(plan, outputs)
    assert resolved["calls"][1]["arguments"]["id"] == "99"
    assert resolved["resolved"] is True


def test_x_plan_resolve_accepts_fenced_raw_outputs_file(tmp_path):
    plan = build_plan("own-posts", username="operator")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    step1 = FIXTURES / "step1_user_fenced.txt"
    resolved = resolve_plan_files(plan_path, [step1])
    assert resolved["calls"][1]["arguments"]["id"] == "99"
    # CLI path
    assert (
        main(
            [
                "x-plan",
                "--resolve",
                str(plan_path),
                "--outputs",
                str(step1),
                "--json",
            ]
        )
        == 0
    )


def test_x_plan_resolve_and_ingest_xml_tag_wrappers(tmp_path):
    """Real host wraps JSON in <tag …> … </tag> plus an 'X reads left' footer."""
    plan = build_plan("own-posts", username="operator")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    step1 = FIXTURES / "step1_user_xml.txt"
    raw_step = step1.read_text(encoding="utf-8")
    assert "<" in raw_step and "CallDynamicTool" in raw_step
    assert "X reads left" in raw_step

    body = strip_wrappers(raw_step)
    assert body.lstrip().startswith("{")
    assert "reads left" not in body.lower()
    assert "<" not in body

    resolved = resolve_plan_files(plan_path, [step1])
    assert resolved["calls"][1]["arguments"]["id"] == "99"
    assert (
        main(
            ["x-plan", "--resolve", str(plan_path), "--outputs", str(step1), "--json"]
        )
        == 0
    )

    posts_raw = FIXTURES / "own_posts_xml.txt"
    posts, truncated = extract_posts(posts_raw.read_text(encoding="utf-8"))
    assert truncated is False
    assert len(posts) == 1
    assert posts[0]["urls"] == [
        "https://news.example/story?utm_campaign=a1b2c3d4&fbclid=IwAR99"
    ]
    assert all("t.co" not in u for u in posts[0]["urls"])

    result = run_ingest(posts_raw.read_text(encoding="utf-8"), offline=True)
    compact = ingest_to_dict(result)
    assert compact["clean_urls"]
    assert all("t.co" not in u for u in compact["clean_urls"])
    assert any("news.example" in u for u in compact["clean_urls"])
    assert main(["x-ingest", "--file", str(posts_raw), "--json"]) in (0, 1, 2)


def test_x_plan_shared_code_stable_order():
    plan = build_plan(
        "shared-code",
        text="See https://news.example/a?cid=zzzz1111&utm_campaign=aaaa2222",
    )
    assert plan["call_count"] == len(plan["calls"])
    codes = [c["arguments"]["query"].strip('"') for c in plan["calls"]]
    assert codes == sorted(codes)
    for call in plan["calls"]:
        assert call["tool"] == "search_posts_all"
        assert call["arguments"]["max_results"] == 25


def test_x_ingest_wrapped_fence_and_footer():
    raw = (FIXTURES / "own_posts_wrapped.json").read_text(encoding="utf-8")
    assert "untrusted-data" in raw
    assert "Reads left" in raw
    body = strip_wrappers(raw)
    assert body.lstrip().startswith("{")
    assert "Reads left" not in body

    posts, truncated = extract_posts(raw)
    assert truncated is False
    assert len(posts) == 2
    assert posts[0]["account"] == "operator"
    assert posts[0]["urls"][0].startswith("https://news.example/")

    result = run_ingest(raw, offline=True)
    assert result.verdict in {"WARN", "BLOCK"}
    assert any(r.code == "campaign_code" or r.code == "tracking_param" for r in result.reasons)

    compact = ingest_to_dict(result)
    assert set(compact.keys()) == {"verdict", "exit_code", "reasons", "clean_urls"}
    assert "urls" not in compact
    verbose = ingest_to_dict(result, posts=posts, verbose=True)
    assert "urls" in verbose
    assert "posts" in verbose


def test_x_ingest_truncated_input_recovers_posts_no_traceback():
    raw = (FIXTURES / "posts_truncated.json").read_text(encoding="utf-8")
    assert "[... 36988 bytes from" in raw
    # Must not raise
    posts, truncated = extract_posts(raw)
    assert truncated is True
    assert len(posts) >= 2
    assert {p["id"] for p in posts} >= {"111", "222"}

    result = run_ingest(raw, offline=True)
    assert any(r.code == "input_truncated" for r in result.reasons)
    assert result.verdict in {"OK", "WARN", "BLOCK"}
    assert result.exit_code in (0, 1, 2)
    # CLI must also not traceback
    code = main(["x-ingest", "--file", str(FIXTURES / "posts_truncated.json"), "--json"])
    assert code in (0, 1, 2)


def test_x_ingest_cluster_fixture_posting_time():
    raw = (FIXTURES / "search_cluster.json").read_text(encoding="utf-8")
    result = run_ingest(raw, offline=True, min_accounts=3, cluster_hours=24)
    assert any(r.code == "posting_time_cluster" for r in result.reasons)


def test_cli_x_plan_and_ingest(tmp_path):
    plan_path = tmp_path / "plan.json"
    out_path = tmp_path / "out.json"
    plan = build_plan("own-posts", username="operator")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    out_path.write_text(json.dumps({"step1": {"data": {"id": "99"}}}), encoding="utf-8")
    assert main(["x-plan", "--resolve", str(plan_path), "--outputs", str(out_path), "--json"]) == 0

    raw = FIXTURES / "own_posts_wrapped.json"
    assert main(["x-ingest", "--file", str(raw), "--json"]) in (0, 1, 2)

"""One test path per leak type described in docs/PROBLEM.md."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from linkcheck import check as check_mod
from linkcheck.check import analyze_url, run_check
from linkcheck.domain_age import check_domain_age
from linkcheck.models import Hop
from linkcheck.script_match import compare_to_corpus
from linkcheck.tracking import analyze_tracking_params


def test_shared_tracker_redirect_hop_warns(tmp_path):
    """Leak: shared tracker / redirect hop → intermediate_hop."""
    shorteners = tmp_path / "shorteners.txt"
    shorteners.write_text("short.example\n", encoding="utf-8")
    block = tmp_path / "blocklist.txt"
    block.write_text("# empty\n", encoding="utf-8")

    hops = [
        Hop(index=0, url="https://short.example/abc", status=302, via="location"),
        Hop(
            index=1,
            url="https://tracker.example/c/?utm_campaign=a1b2c3d4",
            status=302,
            via="location",
        ),
        Hop(index=2, url="https://news.example/story", status=200, via="final"),
    ]

    def stub_trace(url, **_kwargs):
        return list(hops)

    original = check_mod.trace_url
    check_mod.trace_url = stub_trace
    try:
        result = run_check(
            "See https://short.example/abc",
            blocklist_path=block,
            shorteners_path=shorteners,
            check_age=False,
        )
    finally:
        check_mod.trace_url = original

    assert any(r.code == "intermediate_hop" for r in result.reasons)
    assert result.verdict == "WARN"


def test_ids_and_tokens_in_params():
    """Leak: IDs or tokens in params → tracking_param / campaign_code."""
    findings = analyze_tracking_params(
        "https://tracker.example/c/?cid=creatorA&utm_campaign=a1b2c3d4"
    )
    assert any(f.code == "tracking_param" and f.detail.get("key") == "cid" for f in findings)
    assert any(f.code == "campaign_code" for f in findings)


def test_young_domain_age_warns():
    """Leak: new-domain age → young_domain."""
    young = datetime.now(timezone.utc) - timedelta(days=2)
    with patch(
        "linkcheck.domain_age.lookup_registration_date",
        return_value=(young, None),
    ):
        finding = check_domain_age("newtrack.example", young_days=90)
    assert finding is not None
    assert finding.code == "young_domain"
    assert finding.severity == "WARN"


def test_shared_codes_across_accounts():
    """Leak: shared codes across accounts → shared_tracking_code (covered in script tests)."""
    now = datetime.now(timezone.utc).isoformat()
    draft = "note"
    corpus = [
        {"account": "a1", "text": "x", "created_at": now, "urls": ["https://e.example/?cid=deadbeef"]},
        {"account": "a2", "text": "y", "created_at": now, "urls": ["https://e.example/?cid=deadbeef"]},
        {"account": "a3", "text": "z", "created_at": now, "urls": ["https://e.example/?cid=deadbeef"]},
    ]
    report = compare_to_corpus(
        draft,
        corpus,
        draft_urls=["https://mine.example/?cid=deadbeef"],
        threshold=0.99,
        min_accounts=3,
    )
    assert any(f.code == "shared_tracking_code" for f in report.findings)


def test_scripted_wording_across_accounts():
    """Leak: scripted wording → script_near_duplicate."""
    now = datetime.now(timezone.utc).isoformat()
    line = (
        "this shared product update ensures continued leadership in the open market "
        "and rewards early supporters who stay engaged"
    )
    corpus = [
        {"account": "alice", "text": line, "created_at": now, "urls": []},
        {"account": "bob", "text": line + " !", "created_at": now, "urls": []},
        {"account": "carol", "text": line, "created_at": now, "urls": []},
    ]
    report = compare_to_corpus(line, corpus, threshold=0.85, min_accounts=3)
    assert any(f.code == "script_near_duplicate" for f in report.findings)


def test_posting_time_clustering():
    """Leak: posting-time clustering → posting_time_cluster."""
    base = datetime.now(timezone.utc)
    line = (
        "this shared product update ensures continued leadership in the open market "
        "and rewards early supporters who stay engaged"
    )
    corpus = [
        {
            "account": "alice",
            "text": line,
            "created_at": (base - timedelta(hours=10)).isoformat(),
            "urls": [],
        },
        {
            "account": "bob",
            "text": line + " !",
            "created_at": (base - timedelta(hours=8)).isoformat(),
            "urls": [],
        },
        {
            "account": "carol",
            "text": line,
            "created_at": (base - timedelta(hours=5)).isoformat(),
            "urls": [],
        },
        {
            "account": "dave",
            "text": "totally unrelated gardening tips for spring",
            "created_at": (base - timedelta(days=3)).isoformat(),
            "urls": [],
        },
    ]
    report = compare_to_corpus(
        line,
        corpus,
        threshold=0.85,
        min_accounts=3,
        cluster_hours=24,
        now=base,
    )
    assert any(f.code == "posting_time_cluster" for f in report.findings)


def test_analyze_url_flags_young_intermediate(tmp_path):
    """Young intermediate hop surfaces young_domain on analyze_url."""
    young = datetime.now(timezone.utc) - timedelta(days=1)
    hops = [
        Hop(index=0, url="https://short.example/x", status=302, via="location"),
        Hop(index=1, url="https://newtrack.example/r", status=302, via="location"),
        Hop(index=2, url="https://news.example/a", status=200, via="final"),
    ]

    def stub_trace(url, **_kwargs):
        return list(hops)

    with patch("linkcheck.check.trace_url", side_effect=stub_trace), patch(
        "linkcheck.domain_age.lookup_registration_date",
        return_value=(young, None),
    ):
        report = analyze_url(
            "https://short.example/x",
            blocklist=set(),
            allowlist=set(),
            shorteners={"short.example"},
            check_age=True,
        )
    assert any(f.code == "young_domain" for f in report.findings)
    assert any(f.code == "intermediate_hop" for f in report.findings)

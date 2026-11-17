"""Regression tests for live-test bugs reported against main."""

from __future__ import annotations

from linkcheck.check import analyze_url, run_check
from linkcheck.cli import main
from linkcheck.models import Hop
from linkcheck.tracking import analyze_tracking_params
from linkcheck.urls import strip_tracking


def test_tracking_params_ref_si_s_t_click_ids():
    cases = [
        ("https://bit.ly/abc?ref=creator123", "ref"),
        ("https://www.youtube.com/watch?v=dQw4w9wg&si=AbCdEfGhIjKlMnop", "si"),
        ("https://x.com/i/status/1?s=20", "s"),
        ("https://x.com/i/status/1?t=abcDEF1234567890", "t"),
        ("https://news.example/a?fbclid=IwAR1234567890abcdef", "fbclid"),
        ("https://news.example/a?gclid=Cj0KCQjw", "gclid"),
        ("https://news.example/a?igshid=YmMyMTA2M2Y=", "igshid"),
        ("https://news.example/a?mc_eid=deadbeefcafebabe", "mc_eid"),
    ]
    for url, key in cases:
        findings = analyze_tracking_params(url)
        assert any(
            f.code == "tracking_param" and f.detail.get("key", "").lower() == key
            for f in findings
        ), (url, [f.to_dict() for f in findings])


def test_youtube_si_and_x_t_are_not_ok_verdict(tmp_path):
    block = tmp_path / "blocklist.txt"
    block.write_text("# empty\n", encoding="utf-8")

    def stub_trace(url, **_kwargs):
        return [Hop(index=0, url=url, status=200, via="final")]

    import linkcheck.check as check_mod

    original = check_mod.trace_url
    check_mod.trace_url = stub_trace
    try:
        yt = run_check(
            "https://www.youtube.com/watch?v=aaaaaaaaaaa&si=AbCdEfGhIjKlMnop",
            blocklist_path=block,
            check_age=False,
        )
        xt = run_check(
            "https://x.com/i/status/1?t=abcDEF1234567890",
            blocklist_path=block,
            check_age=False,
        )
    finally:
        check_mod.trace_url = original

    assert yt.verdict == "WARN"
    assert any(r.code == "tracking_param" for r in yt.reasons)
    assert xt.verdict == "WARN"
    assert any(r.code == "tracking_param" for r in xt.reasons)


def test_clean_url_strips_fbclid_and_platform_params():
    dirty = (
        "https://news.example/story?utm_source=x&fbclid=IwAR99&gclid=Cj0"
        "&si=sharetokenhere1234&ref=creator123&keep=yes"
    )
    clean = strip_tracking(dirty)
    for key in ("utm_source", "fbclid", "gclid", "si", "ref"):
        assert f"{key}=" not in clean, clean
    assert "keep=yes" in clean


def test_intermediate_hop_deduped_for_repeated_host():
    hops = [
        Hop(index=0, url="https://t.co/x", status=302, via="location"),
        Hop(index=1, url="https://track.example/a", status=302, via="location"),
        Hop(index=2, url="https://track.example/b", status=302, via="location"),
        Hop(index=3, url="https://news.example/z", status=200, via="final"),
    ]

    import linkcheck.check as check_mod

    original = check_mod.trace_url
    check_mod.trace_url = lambda url, **_k: list(hops)
    try:
        report = analyze_url(
            "https://t.co/x",
            blocklist=set(),
            allowlist=set(),
            shorteners={"t.co"},
            check_age=False,
        )
    finally:
        check_mod.trace_url = original

    mid = [f for f in report.findings if f.code == "intermediate_hop"]
    assert len(mid) == 1
    assert mid[0].detail["host"] == "track.example"


def test_positional_urls_not_invalid_choice():
    from linkcheck.cli import build_check_parser, _first_subcommand

    assert _first_subcommand(["https://news.example/a", "https://news.example/b"]) is None
    assert _first_subcommand(["runtime", "--json"]) == "runtime"
    args = build_check_parser().parse_args(
        ["https://news.example/a", "https://news.example/b", "--no-age", "--json"]
    )
    assert args.urls == ["https://news.example/a", "https://news.example/b"]
    # Must not raise SystemExit from argparse "invalid choice" for URL positionals
    import linkcheck.cli as cli

    original = cli._cmd_check
    cli._cmd_check = lambda _args: 0
    try:
        assert main(["https://news.example/a", "https://news.example/b", "--no-age"]) == 0
    finally:
        cli._cmd_check = original


def test_platform_hops_are_benign_intermediate():
    hops = [
        Hop(index=0, url="https://t.co/abc", status=200, via="js"),
        Hop(index=1, url="https://www.google.com/url?q=https://news.example/a", status=302, via="location"),
        Hop(index=2, url="https://news.example/a", status=200, via="final"),
    ]

    import linkcheck.check as check_mod

    original = check_mod.trace_url
    check_mod.trace_url = lambda url, **_k: list(hops)
    try:
        report = analyze_url(
            "https://t.co/abc",
            blocklist=set(),
            allowlist=set(),
            shorteners={"t.co"},
            check_age=False,
        )
    finally:
        check_mod.trace_url = original

    assert not any(f.code == "intermediate_hop" for f in report.findings), [
        f.to_dict() for f in report.findings
    ]


def test_final_404_emits_dead_link_info():
    hops = [
        Hop(index=0, url="https://news.example/gone", status=404, via="final"),
    ]

    import linkcheck.check as check_mod

    original = check_mod.trace_url
    check_mod.trace_url = lambda url, **_k: list(hops)
    try:
        report = analyze_url(
            "https://news.example/gone",
            blocklist=set(),
            allowlist=set(),
            shorteners=set(),
            check_age=False,
        )
    finally:
        check_mod.trace_url = original

    dead = [f for f in report.findings if f.code == "dead_link"]
    assert len(dead) == 1
    assert dead[0].severity == "INFO"
    assert dead[0].detail["status"] == 404

"""Orchestrate link and draft checks into a CheckResult."""

from __future__ import annotations

from pathlib import Path

import requests

from .domain_age import check_domain_age
from .lists import domain_matches, load_domain_list, load_phrases
from .models import (
    EXIT_CODES,
    CheckResult,
    Finding,
    Severity,
    UrlReport,
    worst_severity,
)
from .paths import default_path
from .script_match import run_script_checks
from .tracking import analyze_tracking_params
from .tracer import final_url, trace_url
from .urls import extract_urls, hostname, strip_tracking


def analyze_url(
    url: str,
    *,
    blocklist: set[str],
    allowlist: set[str],
    shorteners: set[str],
    check_age: bool = True,
    session: requests.Session | None = None,
    fetch=None,
) -> UrlReport:
    hops = trace_url(url, session=session, fetch=fetch)
    report = UrlReport(input_url=url, hops=hops)
    report.final_url = final_url(hops)
    target = report.final_url or url
    report.clean_url = strip_tracking(target)

    hop_hosts: list[str] = []
    for hop in hops:
        host = hostname(hop.url)
        if host:
            hop_hosts.append(host)

        if domain_matches(host, allowlist):
            continue

        blocked = domain_matches(host, blocklist)
        if blocked:
            report.findings.append(
                Finding(
                    severity="BLOCK",
                    code="blocklisted_hop",
                    message=f"Hop domain '{host}' is on the blocklist ({blocked})",
                    detail={"host": host, "url": hop.url, "matched": blocked},
                )
            )

        for finding in analyze_tracking_params(hop.url):
            report.findings.append(finding)

    # Intermediate hop that is neither a known shortener nor the destination
    dest = hostname(report.final_url or "")
    if len(hop_hosts) >= 2:
        for host in hop_hosts[:-1]:
            if domain_matches(host, allowlist):
                continue
            if domain_matches(host, shorteners):
                continue
            if dest and host == dest:
                continue
            report.findings.append(
                Finding(
                    severity="WARN",
                    code="intermediate_hop",
                    message=(
                        f"Intermediate hop '{host}' is neither a known shortener "
                        f"nor the destination '{dest or '?'}'"
                    ),
                    detail={"host": host, "destination": dest},
                )
            )

    if check_age:
        checked: set[str] = set()
        for host in hop_hosts:
            if host in checked or domain_matches(host, allowlist) or domain_matches(host, shorteners):
                continue
            checked.add(host)
            age_finding = check_domain_age(host, session=session)
            if age_finding:
                report.findings.append(age_finding)

    if report.clean_url and report.final_url and report.clean_url != report.final_url:
        report.findings.append(
            Finding(
                severity="INFO",
                code="clean_url_suggestion",
                message=f"Suggested clean link (tracking stripped): {report.clean_url}",
                detail={"clean": report.clean_url, "final": report.final_url},
            )
        )

    return report


def run_check(
    text: str,
    extra_urls: list[str] | None = None,
    *,
    blocklist_path: Path | None = None,
    allowlist_path: Path | None = None,
    shorteners_path: Path | None = None,
    phrases_path: Path | None = None,
    corpus_path: Path | None = None,
    check_age: bool = True,
    session: requests.Session | None = None,
    fetch=None,
) -> CheckResult:
    blocklist = load_domain_list(blocklist_path or default_path("blocklist.txt"))
    allowlist = load_domain_list(allowlist_path or default_path("allowlist.txt"))
    shorteners = load_domain_list(shorteners_path or default_path("shorteners.txt"))
    phrases = load_phrases(phrases_path or default_path("phrases.txt"))
    corpus = corpus_path or default_path("corpus.jsonl")

    urls = extract_urls(text)
    for u in extra_urls or []:
        if u not in urls:
            urls.append(u)

    url_reports = [
        analyze_url(
            u,
            blocklist=blocklist,
            allowlist=allowlist,
            shorteners=shorteners,
            check_age=check_age,
            session=session,
            fetch=fetch,
        )
        for u in urls
    ]

    script = run_script_checks(
        text,
        corpus_path=corpus if Path(corpus).exists() else None,
        phrases=phrases,
        draft_urls=[r.final_url or r.input_url for r in url_reports] or urls,
    )

    reasons: list[Finding] = []
    for ur in url_reports:
        reasons.extend(ur.findings)
    reasons.extend(script.findings)

    # Collapse to worst non-INFO for verdict; INFO alone → OK
    severities = [r.severity for r in reasons if r.severity != Severity.INFO.value]
    if not severities:
        # all info or empty
        if any(r.severity == Severity.INFO.value for r in reasons):
            verdict = Severity.OK
        else:
            verdict = Severity.OK
    else:
        verdict = worst_severity(*severities)

    excerpt = (text or "").strip().replace("\n", " ")
    if len(excerpt) > 200:
        excerpt = excerpt[:197] + "..."

    return CheckResult(
        verdict=verdict.value,
        exit_code=EXIT_CODES[verdict],
        reasons=reasons,
        urls=url_reports,
        script_match=script,
        text_excerpt=excerpt,
    )


def format_human(result: CheckResult) -> str:
    lines = [f"Verdict: {result.verdict}"]
    linkable = [
        r for r in result.reasons
        if r.code in {
            "blocklisted_hop",
            "intermediate_hop",
            "campaign_code",
            "tracking_param",
            "tracking_token",
            "shared_tracking_code",
            "script_near_duplicate",
            "script_phrase",
            "young_domain",
        }
    ]
    if linkable:
        lines.append("What would let someone group this draft with others:")
        for r in linkable:
            lines.append(f"  - {r.message}")
    if not result.reasons:
        lines.append("No issues found.")
    else:
        lines.append("Reasons:")
        for r in result.reasons:
            lines.append(f"  [{r.severity}] {r.code}: {r.message}")
    for ur in result.urls:
        lines.append(f"\nURL: {ur.input_url}")
        for hop in ur.hops:
            status = hop.status if hop.status is not None else "-"
            via = hop.via or ""
            err = f" ({hop.error})" if hop.error else ""
            lines.append(f"  {hop.index}. [{status}] {hop.url} {via}{err}".rstrip())
        if ur.clean_url:
            lines.append(f"  Clean: {ur.clean_url}")
    return "\n".join(lines) + "\n"

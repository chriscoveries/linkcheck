"""Parse raw X MCP tool output and run linkcheck verdicts (no live X calls)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .check import analyze_url, format_human
from .lists import domain_matches, load_domain_list, load_phrases
from .models import (
    EXIT_CODES,
    CheckResult,
    Finding,
    Hop,
    ScriptMatchReport,
    Severity,
    UrlReport,
    worst_severity,
)
from .paths import default_path
from .script_match import compare_to_corpus, match_phrases
from .tracking import analyze_tracking_params, extract_tracking_codes
from .urls import extract_urls, hostname, strip_tracking

DEFAULT_CLUSTER_HOURS = 168
DEFAULT_MIN_ACCOUNTS = 3

# Tool results may arrive fenced and with a "reads left" footer.
_FENCE_RE = re.compile(
    r"```(?:untrusted-data|json|text)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_FOOTER_RE = re.compile(
    r"(?im)^\s*(?:reads?\s+left|remaining\s+reads?|api\s+reads?\s+remaining)\b.*$"
)
# Host truncation markers, e.g. `[... 36988 bytes from`
_TRUNC_MARK_RE = re.compile(
    r"\[\.\.\.\s*\d+\s*bytes?\s+from|\.\.\.\s*truncated",
    re.IGNORECASE,
)


def strip_wrappers(raw: str) -> str:
    """Pull JSON out of leading/trailing fences and drop reads-left footers."""
    text = raw or ""
    # Prefer fenced body when present
    bodies = _FENCE_RE.findall(text)
    if bodies:
        text = "\n".join(b.strip() for b in bodies if b.strip())
    else:
        text = text.strip()
        # Drop a leading bare fence line
        if text.startswith("```"):
            text = re.sub(r"^```[^\n]*\n", "", text, count=1)
            text = re.sub(r"\n```\s*$", "", text)
    # Drop footer lines about remaining reads
    lines = [ln for ln in text.splitlines() if not _FOOTER_RE.match(ln)]
    return "\n".join(lines).strip()


def _cut_truncation_marker(text: str) -> tuple[str, bool]:
    """Remove host truncation tails; return (prefix, truncated)."""
    m = _TRUNC_MARK_RE.search(text or "")
    if not m:
        return text or "", False
    return (text or "")[: m.start()], True


def _scan_object_array(text: str, start: int) -> tuple[list[Any], bool]:
    """raw_decode successive objects inside a JSON array starting after '['."""
    decoder = json.JSONDecoder()
    out: list[Any] = []
    idx = start
    truncated = False
    length = len(text)
    while idx < length:
        while idx < length and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= length:
            truncated = True
            break
        if text[idx] == "]":
            break
        if text[idx] != "{":
            truncated = True
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            truncated = True
            break
        out.append(obj)
        idx = end
    return out, truncated


def _recover_truncated_payload(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Recover complete post/user objects from truncated MCP JSON. Never raises."""
    posts: list[Any] = []
    users: list[Any] = []
    truncated = True

    data_m = re.search(r'"data"\s*:\s*\[', text)
    if data_m:
        posts, more = _scan_object_array(text, data_m.end())
        truncated = truncated or more
    else:
        # Single-object data (e.g. get_users_by_username)
        data_obj = re.search(r'"data"\s*:\s*\{', text)
        if data_obj:
            decoder = json.JSONDecoder()
            try:
                obj, _ = decoder.raw_decode(text, data_obj.end() - 1)
                if isinstance(obj, dict) and ("text" in obj or "entities" in obj):
                    posts = [obj]
                elif isinstance(obj, dict):
                    # User object — keep as a payload with data dict via includes path
                    return [{"data": obj}], True
            except json.JSONDecodeError:
                pass

    users_m = re.search(r'"users"\s*:\s*\[', text)
    if users_m:
        users, more = _scan_object_array(text, users_m.end())
        truncated = truncated or more

    payload: dict[str, Any] = {"data": posts}
    if users:
        payload["includes"] = {"users": users}
    return [payload] if posts or users else [], truncated


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _cluster_timestamps(
    times: list[datetime],
    *,
    min_accounts: int,
    cluster_hours: int,
) -> tuple[bool, list[str]]:
    if len(times) < min_accounts:
        return False, []
    ordered = sorted(times)
    window = timedelta(hours=cluster_hours)
    best: list[datetime] = []
    left = 0
    for right, t in enumerate(ordered):
        while t - ordered[left] > window:
            left += 1
        span = ordered[left : right + 1]
        if len(span) > len(best):
            best = span
    if len(best) >= min_accounts:
        return True, [t.isoformat() for t in best[:20]]
    return False, []


def _loads_many(raw: str) -> tuple[list[Any], bool]:
    """Parse JSON / JSONL. Never raises. Returns (nodes, truncated)."""
    truncated = False
    try:
        text = strip_wrappers(raw)
    except Exception:  # noqa: BLE001 — ingest must never traceback
        return [], True
    text, cut = _cut_truncation_marker(text)
    truncated = truncated or cut
    if not text:
        return [], truncated

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if value is not None:
        if isinstance(value, list):
            return value, truncated
        return [value], truncated

    # Incomplete JSON: recover complete objects from data[] / users[]
    recovered, rec_trunc = _recover_truncated_payload(text)
    if recovered:
        return recovered, True

    decoder = json.JSONDecoder()
    idx = 0
    out: list[Any] = []
    length = len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        if text[idx] not in "{[":
            nl = text.find("\n", idx)
            if nl == -1:
                truncated = True
                break
            idx = nl + 1
            continue
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            truncated = True
            break
        out.append(obj)
        idx = end
    if not out:
        truncated = True
    return out, truncated or True


def _unwrap_payloads(nodes: list[Any]) -> list[dict[str, Any]]:
    """Normalize wrappers from agents that save {result: ...} or {calls: [...]}."""
    payloads: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if "data" in node or "includes" in node:
            payloads.append(node)
            continue
        for key in ("result", "output", "content", "body"):
            inner = node.get(key)
            if isinstance(inner, dict) and ("data" in inner or "includes" in inner):
                payloads.append(inner)
                break
            if isinstance(inner, str):
                try:
                    parsed = json.loads(strip_wrappers(inner))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict) and ("data" in parsed or "includes" in parsed):
                    payloads.append(parsed)
                    break
        else:
            for key in ("calls", "results", "responses", "items"):
                seq = node.get(key)
                if isinstance(seq, list):
                    payloads.extend(_unwrap_payloads(seq))
                    break
            else:
                if node:
                    payloads.append(node)
    return payloads


def _url_from_entity(ent: dict[str, Any]) -> str | None:
    for key in ("expanded_url", "unwound_url", "url"):
        val = ent.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    return None


def _urls_from_post(post: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str | None) -> None:
        if not u:
            return
        key = u.rstrip("/")
        if key in seen:
            return
        seen.add(key)
        urls.append(u)

    entities = post.get("entities") or {}
    if isinstance(entities, dict):
        for ent in entities.get("urls") or []:
            if isinstance(ent, dict):
                add(_url_from_entity(ent))

    for u in post.get("urls") or []:
        if isinstance(u, str):
            add(u)
        elif isinstance(u, dict):
            add(_url_from_entity(u))

    # Post text is data only — extract URLs, never execute/interpret as instructions
    text = post.get("text") or post.get("full_text") or ""
    for match in re.finditer(r"https?://\S+", text):
        add(match.group(0).rstrip(".,;:!?)\"']>"))
    return urls


def _account_for_post(post: dict[str, Any], users: dict[str, dict[str, Any]]) -> str:
    for key in ("username", "account", "author", "author_username"):
        val = post.get(key)
        if val:
            return str(val).lstrip("@")
    author_id = str(post.get("author_id") or "")
    if author_id and author_id in users:
        user = users[author_id]
        return str(user.get("username") or user.get("id") or author_id).lstrip("@")
    if author_id:
        return author_id
    return str(post.get("id") or "unknown")


def extract_posts(
    raw: str | list[Any] | dict[str, Any],
) -> tuple[list[dict[str, Any]], bool]:
    """
    Turn raw MCP JSON into normalized post rows.

    Returns (posts, truncated). Never raises — incomplete/host-truncated input
    yields whatever complete post objects could be recovered.
    """
    truncated = False
    try:
        if isinstance(raw, str):
            nodes, truncated = _loads_many(raw)
        elif isinstance(raw, list):
            nodes = raw
        else:
            nodes = [raw]

        payloads = _unwrap_payloads(nodes)
        users: dict[str, dict[str, Any]] = {}
        posts_raw: list[dict[str, Any]] = []

        for payload in payloads:
            includes = payload.get("includes") or {}
            if isinstance(includes, dict):
                for user in includes.get("users") or []:
                    if isinstance(user, dict) and user.get("id"):
                        users[str(user["id"])] = user

            data = payload.get("data")
            if isinstance(data, dict):
                if "text" in data or "entities" in data:
                    posts_raw.append(data)
                continue
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    if "text" in item or "entities" in item or item.get("author_id"):
                        posts_raw.append(item)

        rows: list[dict[str, Any]] = []
        for post in posts_raw:
            created = _parse_date(post.get("created_at") or post.get("date"))
            rows.append(
                {
                    "id": str(post.get("id") or ""),
                    "account": _account_for_post(post, users),
                    "text": post.get("text") or post.get("full_text") or "",
                    "urls": _urls_from_post(post),
                    "created_at": created.isoformat() if created else None,
                    "author_id": str(post.get("author_id") or ""),
                }
            )
        rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
        return rows, truncated
    except Exception:  # noqa: BLE001
        return [], True


def detect_posting_time_cluster(
    posts: list[dict[str, Any]],
    *,
    min_accounts: int = DEFAULT_MIN_ACCOUNTS,
    cluster_hours: int = DEFAULT_CLUSTER_HOURS,
) -> Finding | None:
    by_account: dict[str, datetime] = {}
    for post in posts:
        account = str(post.get("account") or "")
        created = _parse_date(post.get("created_at"))
        if not account or created is None:
            continue
        prev = by_account.get(account)
        if prev is None or created < prev:
            by_account[account] = created
    times = list(by_account.values())
    clustered, sample = _cluster_timestamps(
        times, min_accounts=min_accounts, cluster_hours=cluster_hours
    )
    if not clustered:
        return None
    accounts = sorted(by_account.keys())
    return Finding(
        severity="WARN",
        code="posting_time_cluster",
        message=(
            f"{len(accounts)} accounts posted inside a {cluster_hours}-hour window "
            "(coordination timing signal)"
        ),
        detail={
            "accounts": accounts[:20],
            "cluster_hours": cluster_hours,
            "sample_timestamps": sample,
            "account_count": len(accounts),
        },
    )


def detect_shared_codes_among_posts(
    posts: list[dict[str, Any]],
    *,
    min_accounts: int = DEFAULT_MIN_ACCOUNTS,
) -> list[Finding]:
    from collections import defaultdict

    code_accounts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for post in posts:
        account = str(post.get("account") or "")
        if not account:
            continue
        for url in post.get("urls") or []:
            for code in extract_tracking_codes(url):
                code_accounts[code].add(account)
    findings: list[Finding] = []
    for code, accts in sorted(code_accounts.items(), key=lambda x: (x[0][0], x[0][1])):
        if len(accts) >= min_accounts:
            entry = {"key": code[0], "value": code[1], "accounts": sorted(accts)}
            findings.append(
                Finding(
                    severity="WARN",
                    code="shared_tracking_code",
                    message=(
                        f"Tracking code {code[0]}={code[1]} appears in posts "
                        f"by {len(accts)} accounts"
                    ),
                    detail=entry,
                )
            )
    return findings


def _analyze_url_offline(
    url: str,
    *,
    blocklist: set[str],
    allowlist: set[str],
) -> UrlReport:
    report = UrlReport(
        input_url=url,
        hops=[Hop(index=0, url=url, status=200, via="final")],
    )
    report.final_url = url
    report.clean_url = strip_tracking(url)
    host = hostname(url)
    if host and not domain_matches(host, allowlist):
        blocked = domain_matches(host, blocklist)
        if blocked:
            report.findings.append(
                Finding(
                    severity="BLOCK",
                    code="blocklisted_hop",
                    message=f"Hop domain '{host}' is on the blocklist ({blocked})",
                    detail={"host": host, "url": url, "matched": blocked},
                )
            )
    for finding in analyze_tracking_params(url):
        report.findings.append(finding)
    if report.clean_url and report.clean_url != url:
        report.findings.append(
            Finding(
                severity="INFO",
                code="clean_url_suggestion",
                message=f"Suggested clean link (tracking stripped): {report.clean_url}",
                detail={"clean": report.clean_url, "final": url},
            )
        )
    return report


def run_ingest(
    raw: str,
    *,
    draft_text: str | None = None,
    blocklist_path: Path | None = None,
    allowlist_path: Path | None = None,
    shorteners_path: Path | None = None,
    phrases_path: Path | None = None,
    check_age: bool = False,
    offline: bool = True,
    min_accounts: int = DEFAULT_MIN_ACCOUNTS,
    cluster_hours: int = DEFAULT_CLUSTER_HOURS,
) -> CheckResult:
    try:
        posts, truncated = extract_posts(raw)
    except Exception:  # noqa: BLE001
        posts, truncated = [], True

    blocklist = load_domain_list(blocklist_path or default_path("blocklist.txt"))
    allowlist = load_domain_list(allowlist_path or default_path("allowlist.txt"))
    shorteners = load_domain_list(shorteners_path or default_path("shorteners.txt"))
    phrases = load_phrases(phrases_path or default_path("phrases.txt"))

    url_reports: list[UrlReport] = []
    reasons: list[Finding] = []
    all_urls: list[str] = []

    if truncated:
        reasons.append(
            Finding(
                severity="WARN",
                code="input_truncated",
                message=(
                    f"MCP tool output was truncated or incomplete; "
                    f"recovered {len(posts)} complete post object(s)"
                ),
                detail={"recovered_posts": len(posts)},
            )
        )

    for post in posts:
        for url in post.get("urls") or []:
            if url in all_urls:
                continue
            all_urls.append(url)
            if offline:
                report = _analyze_url_offline(
                    url, blocklist=blocklist, allowlist=allowlist
                )
            else:
                report = analyze_url(
                    url,
                    blocklist=blocklist,
                    allowlist=allowlist,
                    shorteners=shorteners,
                    check_age=check_age,
                )
            url_reports.append(report)
            reasons.extend(report.findings)

    corpus_rows = [
        {
            "account": p["account"],
            "text": p["text"],
            "urls": list(p.get("urls") or []),
            "created_at": p.get("created_at"),
            "id": p.get("id") or "",
        }
        for p in posts
        if p.get("text") and p.get("account")
    ]

    draft = (draft_text or "").strip()
    if draft:
        script = compare_to_corpus(
            draft,
            corpus_rows,
            draft_urls=extract_urls(draft) + all_urls,
            min_accounts=min_accounts,
        )
        reasons.extend(script.findings)
        hits = match_phrases(draft, phrases)
        if hits:
            reasons.append(
                Finding(
                    severity="WARN",
                    code="script_phrase",
                    message=f"Draft contains known shared phrase(s): {hits[0]!r}"
                    + (f" (+{len(hits) - 1} more)" if len(hits) > 1 else ""),
                    detail={"phrases": hits},
                )
            )
            script.phrase_hits = hits
        script_match = script
    else:
        if len({r["account"] for r in corpus_rows}) >= 2 and corpus_rows:
            pivot = max(corpus_rows, key=lambda r: len(r.get("text") or ""))
            others = [r for r in corpus_rows if r["account"] != pivot["account"]]
            script_match = compare_to_corpus(
                pivot["text"],
                others,
                draft_urls=list(pivot.get("urls") or []),
                min_accounts=min_accounts,
            )
            reasons.extend(script_match.findings)
        else:
            script_match = ScriptMatchReport(checked=bool(corpus_rows))
        reasons.extend(detect_shared_codes_among_posts(posts, min_accounts=min_accounts))

    cluster_finding = detect_posting_time_cluster(
        posts, min_accounts=min_accounts, cluster_hours=cluster_hours
    )
    if cluster_finding:
        reasons.append(cluster_finding)

    deduped: list[Finding] = []
    seen_keys: set[tuple[str, str]] = set()
    for finding in reasons:
        key = (finding.code, finding.message)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(finding)

    severities = [r.severity for r in deduped if r.severity != Severity.INFO.value]
    verdict = worst_severity(*severities) if severities else Severity.OK

    excerpt_src = draft or " | ".join(p.get("text") or "" for p in posts[:3])
    excerpt = excerpt_src.strip().replace("\n", " ")
    if len(excerpt) > 200:
        excerpt = excerpt[:197] + "..."

    return CheckResult(
        verdict=verdict.value,
        exit_code=EXIT_CODES[verdict],
        reasons=deduped,
        urls=url_reports,
        script_match=script_match,
        text_excerpt=excerpt,
    )


def ingest_to_dict(
    result: CheckResult,
    *,
    posts: list[dict[str, Any]] | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Compact by default: verdict, reasons, clean_urls. Full detail with verbose."""
    clean_urls: list[str] = []
    seen: set[str] = set()
    for ur in result.urls:
        clean = ur.clean_url or ur.final_url or ur.input_url
        if clean and clean not in seen:
            seen.add(clean)
            clean_urls.append(clean)

    compact: dict[str, Any] = {
        "verdict": result.verdict,
        "exit_code": result.exit_code,
        "reasons": [
            {"severity": r.severity, "code": r.code, "message": r.message}
            for r in result.reasons
            if r.severity != Severity.INFO.value or r.code == "dead_link"
        ],
        "clean_urls": clean_urls,
    }
    # Keep INFO clean suggestions out of compact reasons but expose cleans
    if verbose:
        body = result.to_dict()
        body["clean_urls"] = clean_urls
        if posts is not None:
            body["posts"] = [
                {
                    "id": p.get("id"),
                    "account": p.get("account"),
                    "created_at": p.get("created_at"),
                    "urls": p.get("urls") or [],
                    "text_excerpt": ((p.get("text") or "")[:120]),
                }
                for p in posts
            ]
        return body
    return compact


__all__ = [
    "extract_posts",
    "run_ingest",
    "detect_posting_time_cluster",
    "format_human",
    "ingest_to_dict",
    "strip_wrappers",
]

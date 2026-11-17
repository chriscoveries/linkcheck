"""Near-duplicate wording and shared tracking-code detection across accounts."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Finding, ScriptMatchReport
from .tracking import extract_tracking_codes

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
DEFAULT_THRESHOLD = 0.85
DEFAULT_MIN_ACCOUNTS = 3
DEFAULT_LOOKBACK_DAYS = 14
DEFAULT_CLUSTER_HOURS = 168  # 7 days: similar posts bunched in a short window


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = re.sub(r"#\w+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


def shingles(text: str, n: int = 3) -> set[str]:
    toks = tokens(text)
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def tfidf_cosine(query_tf: Counter[str], doc_tf: Counter[str], idf: dict[str, float]) -> float:
    def weighted(tf: Counter[str]) -> dict[str, float]:
        return {t: (1 + math.log(c)) * idf.get(t, 0.0) for t, c in tf.items()}

    q, d = weighted(query_tf), weighted(doc_tf)
    keys = set(q) | set(d)
    if not keys:
        return 0.0
    dot = sum(q.get(k, 0.0) * d.get(k, 0.0) for k in keys)
    nq = math.sqrt(sum(v * v for v in q.values()))
    nd = math.sqrt(sum(v * v for v in d.values()))
    if nq == 0 or nd == 0:
        return 0.0
    return dot / (nq * nd)


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


def load_corpus(path: Path | None, *, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> list[dict]:
    """JSONL rows: account, text, created_at, optional id / urls."""
    if path is None or not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = row.get("text") or row.get("full_text") or ""
        account = str(row.get("account") or row.get("username") or row.get("author") or "")
        if not text or not account:
            continue
        created = _parse_date(row.get("created_at") or row.get("date"))
        if created is not None and created < cutoff:
            continue
        rows.append(
            {
                "account": account.lstrip("@"),
                "text": text,
                "urls": list(row.get("urls") or []),
                "created_at": created.isoformat() if created else None,
                "id": str(row.get("id") or ""),
            }
        )
    return rows


def match_phrases(text: str, phrases: list[str]) -> list[str]:
    norm = normalize_text(text)
    return [p for p in phrases if normalize_text(p) and normalize_text(p) in norm]


def _cluster_timestamps(
    times: list[datetime],
    *,
    min_accounts: int,
    cluster_hours: int,
) -> tuple[bool, list[str]]:
    """True when ≥ min_accounts timestamps fall inside a cluster_hours window."""
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


def compare_to_corpus(
    draft: str,
    corpus: list[dict],
    *,
    draft_urls: list[str] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    min_accounts: int = DEFAULT_MIN_ACCOUNTS,
    cluster_hours: int = DEFAULT_CLUSTER_HOURS,
    now: datetime | None = None,
) -> ScriptMatchReport:
    report = ScriptMatchReport(checked=True)
    if not corpus:
        report.checked = False
        return report

    q_sh = shingles(draft)
    q_tf = Counter(tokens(draft))
    df: Counter[str] = Counter()
    docs_tf: list[Counter[str]] = []
    for row in corpus:
        tf = Counter(tokens(row["text"]))
        docs_tf.append(tf)
        df.update(set(tf))
    df.update(set(q_tf))
    n_docs = len(corpus) + 1
    idf = {t: math.log((n_docs + 1) / (1 + c)) + 1.0 for t, c in df.items()}

    per_account: dict[str, float] = defaultdict(float)
    best_row: dict[str, dict] = {}
    for row, tf in zip(corpus, docs_tf):
        sim = max(jaccard(q_sh, shingles(row["text"])), tfidf_cosine(q_tf, tf, idf))
        if sim > per_account[row["account"]]:
            per_account[row["account"]] = sim
            best_row[row["account"]] = row

    matched = sorted(
        ((a, s) for a, s in per_account.items() if s >= threshold),
        key=lambda x: -x[1],
    )
    report.max_similarity = max(per_account.values()) if per_account else 0.0
    report.matched_accounts = [a for a, _ in matched]
    report.match_count_accounts = len(matched)
    report.near_duplicate = len(matched) >= min_accounts

    if report.near_duplicate:
        report.findings.append(
            Finding(
                severity="WARN",
                code="script_near_duplicate",
                message=(
                    f"Draft is near-duplicate (similarity ≥ {threshold:.2f}) of posts "
                    f"by {len(matched)} distinct accounts in the lookback window"
                ),
                detail={
                    "threshold": threshold,
                    "accounts": report.matched_accounts[:20],
                    "max_similarity": round(report.max_similarity, 4),
                },
            )
        )

    # Posting-time clustering among near-duplicate matches (+ draft = now)
    matched_times: list[datetime] = []
    for account, _sim in matched:
        row = best_row.get(account) or {}
        created = _parse_date(row.get("created_at"))
        if created is not None:
            matched_times.append(created)
    draft_time = now or datetime.now(timezone.utc)
    cluster_times = list(matched_times) + [draft_time]
    clustered, sample = _cluster_timestamps(
        cluster_times,
        min_accounts=min_accounts + 1,  # draft + others, or enough peers alone
        cluster_hours=cluster_hours,
    )
    # Also flag when enough peer posts alone cluster (without requiring draft)
    peer_clustered, peer_sample = _cluster_timestamps(
        matched_times,
        min_accounts=min_accounts,
        cluster_hours=cluster_hours,
    )
    if (clustered or peer_clustered) and len(matched) >= min_accounts:
        report.findings.append(
            Finding(
                severity="WARN",
                code="posting_time_cluster",
                message=(
                    f"Near-duplicate posts by {len(matched)} accounts cluster inside "
                    f"a {cluster_hours}-hour window (coordination timing signal)"
                ),
                detail={
                    "accounts": report.matched_accounts[:20],
                    "cluster_hours": cluster_hours,
                    "sample_timestamps": sample or peer_sample,
                },
            )
        )

    # Shared tracking codes across accounts
    draft_codes = set()
    for u in draft_urls or []:
        draft_codes.update(extract_tracking_codes(u))
    if draft_codes:
        code_accounts: dict[tuple[str, str], set[str]] = defaultdict(set)
        for row in corpus:
            for u in row.get("urls") or []:
                for code in extract_tracking_codes(u):
                    if code in draft_codes:
                        code_accounts[code].add(row["account"])
        for code, accts in code_accounts.items():
            if len(accts) >= min_accounts:
                entry = {"key": code[0], "value": code[1], "accounts": sorted(accts)}
                report.shared_tracking_codes.append(entry)
                report.findings.append(
                    Finding(
                        severity="WARN",
                        code="shared_tracking_code",
                        message=(
                            f"Tracking code {code[0]}={code[1]} also appears in posts "
                            f"by {len(accts)} other accounts"
                        ),
                        detail=entry,
                    )
                )

    return report


def run_script_checks(
    draft: str,
    *,
    corpus_path: Path | None,
    phrases: list[str],
    draft_urls: list[str] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    min_accounts: int = DEFAULT_MIN_ACCOUNTS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    cluster_hours: int = DEFAULT_CLUSTER_HOURS,
) -> ScriptMatchReport:
    corpus = load_corpus(corpus_path, lookback_days=lookback_days)
    report = compare_to_corpus(
        draft,
        corpus,
        draft_urls=draft_urls,
        threshold=threshold,
        min_accounts=min_accounts,
        cluster_hours=cluster_hours,
    )
    hits = match_phrases(draft, phrases)
    report.phrase_hits = hits
    if hits:
        report.findings.append(
            Finding(
                severity="WARN",
                code="script_phrase",
                message=f"Draft contains known shared phrase(s): {hits[0]!r}"
                + (f" (+{len(hits) - 1} more)" if len(hits) > 1 else ""),
                detail={"phrases": hits},
            )
        )
    if not corpus and not phrases:
        report.checked = False
    return report

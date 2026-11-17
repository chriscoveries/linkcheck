"""Stable result types for human and --json output. See docs/schema.md."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    OK = "OK"
    INFO = "INFO"
    WARN = "WARN"
    BLOCK = "BLOCK"


SEVERITY_RANK = {
    Severity.OK: 0,
    Severity.INFO: 0,
    Severity.WARN: 1,
    Severity.BLOCK: 2,
}

EXIT_CODES = {
    Severity.OK: 0,
    Severity.INFO: 0,
    Severity.WARN: 1,
    Severity.BLOCK: 2,
}


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class Hop:
    index: int
    url: str
    status: int | None = None
    via: str | None = None  # location | meta-refresh | js | final | error
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UrlReport:
    input_url: str
    hops: list[Hop] = field(default_factory=list)
    final_url: str | None = None
    clean_url: str | None = None
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input_url,
            "hops": [h.to_dict() for h in self.hops],
            "final": self.final_url,
            "clean": self.clean_url,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class ScriptMatchReport:
    checked: bool
    near_duplicate: bool = False
    match_count_accounts: int = 0
    max_similarity: float = 0.0
    matched_accounts: list[str] = field(default_factory=list)
    phrase_hits: list[str] = field(default_factory=list)
    shared_tracking_codes: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "near_duplicate": self.near_duplicate,
            "match_count_accounts": self.match_count_accounts,
            "max_similarity": self.max_similarity,
            "matched_accounts": self.matched_accounts,
            "phrase_hits": self.phrase_hits,
            "shared_tracking_codes": self.shared_tracking_codes,
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class CheckResult:
    verdict: str
    exit_code: int
    reasons: list[Finding] = field(default_factory=list)
    urls: list[UrlReport] = field(default_factory=list)
    script_match: ScriptMatchReport | None = None
    text_excerpt: str = ""
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "verdict": self.verdict,
            "exit_code": self.exit_code,
            "reasons": [r.to_dict() for r in self.reasons],
            "urls": [u.to_dict() for u in self.urls],
            "script_match": self.script_match.to_dict() if self.script_match else None,
            "text_excerpt": self.text_excerpt,
        }


def worst_severity(*severities: str) -> Severity:
    best = Severity.OK
    for s in severities:
        try:
            sev = Severity(s)
        except ValueError:
            continue
        if SEVERITY_RANK[sev] > SEVERITY_RANK[best]:
            best = sev
    return best

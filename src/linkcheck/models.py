"""Stable result types for human and --json output. See docs/schema.md."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

HopVia = Literal["location", "meta-refresh", "js", "final", "error"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    detail: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Hop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    url: str
    status: int | None = None
    via: HopVia | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class UrlReport(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    input_url: str = Field(alias="input")
    hops: list[Hop] = Field(default_factory=list)
    final_url: str | None = Field(default=None, alias="final")
    clean_url: str | None = Field(default=None, alias="clean")
    findings: list[Finding] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class ScriptMatchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked: bool
    near_duplicate: bool = False
    match_count_accounts: int = 0
    max_similarity: float = 0.0
    matched_accounts: list[str] = Field(default_factory=list)
    phrase_hits: list[str] = Field(default_factory=list)
    shared_tracking_codes: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["OK", "WARN", "BLOCK"]
    exit_code: Literal[0, 1, 2]
    reasons: list[Finding] = Field(default_factory=list)
    urls: list[UrlReport] = Field(default_factory=list)
    script_match: ScriptMatchReport | None = None
    text_excerpt: str = ""
    schema_version: str = "1.0"

    @model_validator(mode="after")
    def exit_matches_verdict(self) -> CheckResult:
        expected = EXIT_CODES[Severity(self.verdict)]
        if self.exit_code != expected:
            raise ValueError(
                f"exit_code {self.exit_code} does not match verdict {self.verdict}"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


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

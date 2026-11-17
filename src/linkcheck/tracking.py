"""Detect identifying query parameters and opaque tokens in URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import Finding
from .urls import TRACKING_KEYS

# Identifying / attribution keys (WARN). Plain utm_* is INFO only.
IDENTIFYING_KEYS = {
    "cid",
    "creator",
    "campaign",
    "aff",
    "affiliate",
    "subid",
    "sub_id",
    "clickid",
    "click_id",
    "cb",
    "ref_id",
    "partner_id",
    "publisher_id",
}

_TOKEN_RE = re.compile(r"^[a-f0-9]{8}$|^[A-Za-z0-9_-]{16,}$")


def analyze_tracking_params(url: str) -> list[Finding]:
    findings: list[Finding] = []
    try:
        qs = parse_qs(urlparse(url).query, keep_blank_values=False)
    except ValueError:
        return findings

    utm_keys = sorted(k for k in qs if k.lower().startswith("utm_"))
    plain_utm = []
    for key in utm_keys:
        values = qs[key]
        token_vals = [v for v in values if _TOKEN_RE.match(v or "")]
        if token_vals:
            findings.append(
                Finding(
                    severity="WARN",
                    code="campaign_code",
                    message=(
                        f"'{key}' carries an opaque code ({token_vals[0]}) that can "
                        "group this post with others using the same value"
                    ),
                    detail={"key": key, "values": token_vals[:3], "url": url},
                )
            )
        else:
            plain_utm.append(key)
    if plain_utm:
        findings.append(
            Finding(
                severity="INFO",
                code="utm_params",
                message=f"Plain UTM parameters present (often benign): {', '.join(plain_utm)}",
                detail={"keys": plain_utm, "url": url},
            )
        )

    for key, values in qs.items():
        lk = key.lower()
        if lk.startswith("utm_"):
            continue
        if lk in IDENTIFYING_KEYS or lk in TRACKING_KEYS:
            findings.append(
                Finding(
                    severity="WARN",
                    code="tracking_param",
                    message=f"Identifying tracking parameter '{key}' on URL",
                    detail={"key": key, "values": values[:3], "url": url},
                )
            )
            continue
        for val in values[:2]:
            if _TOKEN_RE.match(val or ""):
                findings.append(
                    Finding(
                        severity="WARN",
                        code="tracking_token",
                        message=f"Opaque tracking-like value on parameter '{key}'",
                        detail={"key": key, "value": val, "url": url},
                    )
                )
                break

    return findings


def extract_tracking_codes(url: str) -> list[tuple[str, str]]:
    """Return (key, value) pairs that can link posts across accounts."""
    codes: list[tuple[str, str]] = []
    try:
        qs = parse_qs(urlparse(url).query, keep_blank_values=False)
    except ValueError:
        return codes
    for key, values in qs.items():
        lk = key.lower()
        for val in values:
            if not val:
                continue
            if lk in IDENTIFYING_KEYS or (lk.startswith("utm_") and _TOKEN_RE.match(val)):
                codes.append((lk, val))
            elif _TOKEN_RE.match(val) and lk not in {"id"}:
                codes.append((lk, val))
    return codes

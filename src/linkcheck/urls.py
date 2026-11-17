"""Extract and normalize http(s) URLs from draft text."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_URL_RE = re.compile(
    r"""(?xi)
    \b(
      https?://[^\s<>\[\]"'()]+
      |
      (?:www\.)?[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+
      /[^\s<>\[\]"'()]*
    )
    """
)
_TRAIL_PUNCT = ".,;:!?)\"']>"

# Query keys commonly used for cross-account linking / click attribution.
TRACKING_KEYS = {
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
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
}


def normalize_url(raw: str) -> str:
    url = raw.strip().rstrip(_TRAIL_PUNCT)
    if url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.finditer(text or ""):
        url = normalize_url(match.group(1))
        key = url.rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out


def hostname(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def strip_tracking(url: str) -> str:
    """Return a canonical URL with known tracking query params removed."""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_KEYS
    ]
    return urlunparse(
        (parts.scheme, parts.netloc, parts.path, parts.params, urlencode(kept), "")
    )

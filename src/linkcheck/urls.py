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

# Query keys to strip from clean URLs and (non-utm) to flag as tracking.
# Keep in sync with tracking.IDENTIFYING_KEYS for attribution keys.
TRACKING_KEYS = {
    # Attribution / affiliate
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
    "ref",
    "ref_id",
    "partner_id",
    "publisher_id",
    # Platform click ids
    "fbclid",
    "gclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "twclid",
    "igshid",
    "mc_eid",
    "mc_cid",
    # YouTube share / X share tokens
    "si",
    "s",
    "t",
    # UTM family
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
}

# Intermediate hops on these hosts are expected platform plumbing, not trackers.
PLATFORM_HOPS = {
    "t.co",
    "x.com",
    "twitter.com",
    "google.com",
    "youtube.com",
    "youtu.be",
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


def is_platform_hop(host: str) -> bool:
    """True when host is a known platform shortener / own hop (or a subdomain)."""
    h = (host or "").lower().removeprefix("www.")
    if not h:
        return False
    if h in PLATFORM_HOPS:
        return True
    return any(h.endswith("." + p) for p in PLATFORM_HOPS)


def strip_tracking(url: str) -> str:
    """Return a canonical URL with known tracking query params removed."""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_KEYS and not k.lower().startswith("utm_")
    ]
    return urlunparse(
        (parts.scheme, parts.netloc, parts.path, parts.params, urlencode(kept), "")
    )

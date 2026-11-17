"""Follow redirect hops manually (no auto-redirects)."""

from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urljoin

import requests

from .models import Hop

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; linkcheck/0.1; +https://example.com/linkcheck)"
)
MAX_HOPS = 10
DEFAULT_TIMEOUT = 10

_META_REFRESH_RE = re.compile(
    r"""(?is)<meta\s+[^>]*http-equiv\s*=\s*['"]?refresh['"]?[^>]*content\s*=\s*['"]?\s*\d+\s*;\s*url\s*=\s*([^'"\s>]+)""",
)
_META_REFRESH_RE_ALT = re.compile(
    r"""(?is)<meta\s+[^>]*content\s*=\s*['"]?\s*\d+\s*;\s*url\s*=\s*([^'"\s>]+)[^>]*http-equiv\s*=\s*['"]?refresh""",
)
_JS_LOC_RE = re.compile(
    r"""(?is)(?:window\.)?location(?:\.href|\.replace)?\s*=\s*['"]([^'"]+)['"]"""
)
_JS_REPLACE_RE = re.compile(
    r"""(?is)(?:window\.)?location\.replace\(\s*['"]([^'"]+)['"]\s*\)"""
)


def _extract_html_redirect(html: str, base_url: str) -> tuple[str, str] | None:
    for cre, via in (
        (_META_REFRESH_RE, "meta-refresh"),
        (_META_REFRESH_RE_ALT, "meta-refresh"),
        (_JS_REPLACE_RE, "js"),
        (_JS_LOC_RE, "js"),
    ):
        m = cre.search(html or "")
        if m:
            return urljoin(base_url, m.group(1).strip()), via
    return None


def trace_url(
    url: str,
    *,
    max_hops: int = MAX_HOPS,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = DEFAULT_UA,
    session: requests.Session | None = None,
    fetch: Callable[..., requests.Response] | None = None,
) -> list[Hop]:
    """Follow redirects hop-by-hop without requests' auto-redirect."""
    sess = session or requests.Session()
    hops: list[Hop] = []
    current = url
    seen: set[str] = set()

    for i in range(max_hops):
        if current in seen:
            hops.append(
                Hop(index=i, url=current, status=None, via="error", error="redirect loop")
            )
            break
        seen.add(current)

        try:
            if fetch is not None:
                resp = fetch(current)
            else:
                resp = sess.get(
                    current,
                    allow_redirects=False,
                    timeout=timeout,
                    headers={"User-Agent": user_agent, "Accept": "text/html,*/*"},
                )
        except requests.RequestException as exc:
            hops.append(
                Hop(index=i, url=current, status=None, via="error", error=str(exc)[:200])
            )
            break

        status = resp.status_code
        hop = Hop(index=i, url=current, status=status, via=None)

        if status in {301, 302, 303, 307, 308}:
            location = resp.headers.get("Location")
            if not location:
                hop.via = "error"
                hop.error = "redirect without Location"
                hops.append(hop)
                break
            hop.via = "location"
            hops.append(hop)
            current = urljoin(current, location.strip())
            continue

        ctype = (resp.headers.get("Content-Type") or "").lower()
        body = ""
        if "html" in ctype or not ctype:
            try:
                body = resp.text[:100_000]
            except Exception:  # noqa: BLE001
                body = ""
        html_redir = _extract_html_redirect(body, current) if body else None
        if html_redir:
            next_url, via = html_redir
            hop.via = via
            hops.append(hop)
            current = next_url
            continue

        hop.via = "final"
        hops.append(hop)
        break
    else:
        hops.append(
            Hop(
                index=len(hops),
                url=current,
                status=None,
                via="error",
                error=f"exceeded max hops ({max_hops})",
            )
        )

    return hops


def final_url(hops: list[Hop]) -> str | None:
    if not hops:
        return None
    last = hops[-1]
    if last.via == "final" or (last.status and 200 <= last.status < 300):
        return last.url
    for h in reversed(hops):
        if h.status is not None:
            return h.url
    return hops[-1].url

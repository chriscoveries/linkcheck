"""Domain age via RDAP (rdap.org), with optional python-whois fallback."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from .models import Finding

RDAP_BOOTSTRAP = "https://rdap.org/domain/{domain}"
YOUNG_DAYS = 90


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%b-%Y",
    ):
        try:
            candidate = text
            if "%z" in fmt and candidate.endswith("Z"):
                candidate = candidate[:-1] + "+0000"
            dt = datetime.strptime(candidate, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _registration_from_rdap(data: dict[str, Any]) -> datetime | None:
    events = data.get("events") or []
    for event in events:
        if (event.get("eventAction") or "").lower() in {"registration", "registered"}:
            dt = _parse_datetime(event.get("eventDate"))
            if dt:
                return dt
    dates = [_parse_datetime(e.get("eventDate")) for e in events]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def lookup_registration_date(
    domain: str,
    *,
    timeout: float = 8.0,
    session: requests.Session | None = None,
) -> tuple[datetime | None, str | None]:
    sess = session or requests.Session()
    try:
        resp = sess.get(
            RDAP_BOOTSTRAP.format(domain=domain),
            timeout=timeout,
            headers={"Accept": "application/rdap+json, application/json"},
        )
        if resp.status_code == 200:
            dt = _registration_from_rdap(resp.json())
            if dt:
                return dt, None
            return None, "RDAP response lacked a registration date"
        err = f"RDAP HTTP {resp.status_code}"
    except requests.RequestException as exc:
        err = f"RDAP error: {exc}"

    try:
        import whois  # type: ignore
    except ImportError:
        return None, err

    try:
        w = whois.whois(domain)
        created = w.creation_date
        if isinstance(created, list):
            created = created[0]
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return created.astimezone(timezone.utc), None
        if isinstance(created, str):
            dt = _parse_datetime(created)
            if dt:
                return dt, None
        return None, f"{err}; WHOIS had no creation date"
    except Exception as exc:  # noqa: BLE001
        return None, f"{err}; WHOIS error: {exc}"


def check_domain_age(
    domain: str,
    *,
    young_days: int = YOUNG_DAYS,
    timeout: float = 8.0,
    session: requests.Session | None = None,
) -> Finding | None:
    dt, err = lookup_registration_date(domain, timeout=timeout, session=session)
    if err and dt is None:
        return Finding(
            severity="INFO",
            code="domain_age_unknown",
            message=f"Could not determine age of {domain} ({err})",
            detail={"domain": domain, "error": err},
        )
    if dt is None:
        return None
    age_days = (datetime.now(timezone.utc) - dt).days
    if age_days < young_days:
        return Finding(
            severity="WARN",
            code="young_domain",
            message=f"Domain {domain} appears only {age_days} days old (threshold {young_days})",
            detail={
                "domain": domain,
                "age_days": age_days,
                "registered": dt.isoformat(),
                "threshold_days": young_days,
            },
        )
    return None

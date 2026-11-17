"""Load blocklists, allowlists, shorteners, and phrase lists."""

from __future__ import annotations

from pathlib import Path


def load_domain_list(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    domains: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        domains.add(line.lower().removeprefix("www."))
    return domains


def load_phrases(path: Path | None) -> list[str]:
    if path is None or not path.exists():
        return []
    phrases: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        phrases.append(line)
    return phrases


def domain_matches(host: str, domains: set[str]) -> str | None:
    host = (host or "").lower().removeprefix("www.")
    if not host:
        return None
    if host in domains:
        return host
    for d in domains:
        if host.endswith("." + d):
            return d
    return None

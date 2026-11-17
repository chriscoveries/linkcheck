"""Resolve bundled and checkout data file paths."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def bundled_data_dir() -> Path:
    root = resources.files("linkcheck") / "data"
    as_path = Path(str(root))
    if as_path.is_dir():
        return as_path
    return Path(__file__).resolve().parent / "data"


def repo_data_dir() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data"
        if candidate.is_dir() and (candidate / "blocklist.txt").exists():
            return candidate
    return None


def default_path(name: str) -> Path:
    repo = repo_data_dir()
    if repo is not None:
        p = repo / name
        if p.exists():
            return p
    return bundled_data_dir() / name

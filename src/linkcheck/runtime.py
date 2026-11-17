"""Agent runtime: playbook index the process can print without a human reader."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import __version__


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    file: str
    when: str
    command: str
    env: list[str] = Field(default_factory=list)


class RuntimeIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    audience: str
    boot: list[str]
    rule: str
    decisions: dict[str, str]
    playbooks: list[Playbook]


def playbook_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "playbooks"
        if (candidate / "index.json").is_file():
            return candidate
    raise FileNotFoundError("playbooks/index.json not found from the linkcheck package")


def load_index() -> RuntimeIndex:
    path = playbook_dir() / "index.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    index = RuntimeIndex.model_validate(data)
    missing = [p.file for p in index.playbooks if not (path.parent / p.file).is_file()]
    if missing:
        raise FileNotFoundError(f"playbook files missing: {', '.join(missing)}")
    ids = {p.id for p in index.playbooks}
    unknown = [step for step in index.boot if step not in ids]
    if unknown:
        raise ValueError(f"boot steps not in playbooks: {', '.join(unknown)}")
    return index


def runtime_payload() -> dict:
    index = load_index()
    body = index.model_dump(mode="json")
    body["name"] = "linkcheck"
    body["version"] = __version__
    body["invoke"] = "linkcheck"
    body["result_schema"] = "docs/schema.md"
    return body


def playbook_text(playbook_id: str) -> str:
    index = load_index()
    match = next((p for p in index.playbooks if p.id == playbook_id), None)
    if match is None:
        known = ", ".join(p.id for p in index.playbooks)
        raise KeyError(f"unknown playbook {playbook_id!r}; known: {known}")
    return (playbook_dir() / match.file).read_text(encoding="utf-8")


def format_runtime_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return exc.error_count().__str__() + " validation error(s) in playbooks/index.json"
    return str(exc)

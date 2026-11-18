import json

import pytest
from pydantic import ValidationError

from linkcheck.models import CheckResult, Finding
from linkcheck.runtime import load_index, playbook_text, runtime_payload, schema_text


def test_runtime_index_matches_files():
    index = load_index()
    assert index.boot[0] == "install"
    assert index.boot == ["install", "scope"]
    payload = runtime_payload()
    assert payload["decisions"]["2"] == "stop"
    assert payload["dataset_decisions"]["2"] == "invalid_or_unavailable"
    assert "find-own-posts" in playbook_text("find-own-posts")
    assert "check-draft" in playbook_text("check-draft")
    json.dumps(payload)


def test_packaged_playbooks_match_canonical_files():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    canonical = root / "playbooks"
    packaged = root / "src" / "linkcheck" / "playbooks"
    assert {p.name for p in canonical.iterdir() if p.is_file()} == {p.name for p in packaged.iterdir() if p.is_file()}
    for path in canonical.iterdir():
        if path.is_file():
            assert path.read_bytes() == (packaged / path.name).read_bytes()
    for name in ("schema.md", "dataset.md"):
        assert (root / "docs" / name).read_bytes() == (root / "src" / "linkcheck" / "docs" / name).read_bytes()


def test_schema_docs_available_through_runtime():
    assert "Source schema" in schema_text("dataset")
    assert "schema_version" in schema_text("draft")
    assert runtime_payload()["dataset_schema"] == "linkcheck runtime --schema dataset"


def test_result_model_rejects_mismatched_exit():
    with pytest.raises(ValidationError):
        CheckResult(
            verdict="BLOCK",
            exit_code=0,
            reasons=[
                Finding(severity="BLOCK", code="blocklisted_hop", message="no")
            ],
        )


def test_result_dump_uses_stable_keys():
    result = CheckResult(
        verdict="OK",
        exit_code=0,
        reasons=[Finding(severity="INFO", code="utm_params", message="plain tags")],
    )
    body = result.to_dict()
    assert body["schema_version"] == "1.0"
    assert body["verdict"] == "OK"
    assert body["reasons"][0]["severity"] == "INFO"

import json

import pytest
from pydantic import ValidationError

from linkcheck.models import CheckResult, Finding
from linkcheck.runtime import load_index, playbook_text, runtime_payload


def test_runtime_index_matches_files():
    index = load_index()
    assert index.boot[0] == "install"
    assert "check-draft" in index.boot
    payload = runtime_payload()
    assert payload["decisions"]["2"] == "stop"
    assert "check-draft" in playbook_text("check-draft")
    ids = {p.id for p in index.playbooks}
    assert "x-mcp" in ids
    assert "x-plan" in playbook_text("x-mcp")
    json.dumps(payload)


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

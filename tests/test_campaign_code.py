from linkcheck.check import run_check
from linkcheck.tracking import analyze_tracking_params


def test_hex_utm_campaign_warns_plain_utm_does_not():
    coded = analyze_tracking_params("https://news.example/story?utm_campaign=a1b2c3d4&utm_medium=cpc")
    assert any(f.code == "campaign_code" and f.severity == "WARN" for f in coded)
    assert any(f.code == "utm_params" and f.detail["keys"] == ["utm_medium"] for f in coded)

    plain = analyze_tracking_params("https://news.example/story?utm_campaign=spring")
    assert all(f.code != "campaign_code" for f in plain)
    assert any(f.code == "utm_params" for f in plain)


def test_draft_with_shared_code_is_warn(tmp_path):
    block = tmp_path / "blocklist.txt"
    block.write_text("# empty\n", encoding="utf-8")
    result = run_check(
        "A note https://news.example/story?utm_campaign=a1b2c3d4",
        blocklist_path=block,
        check_age=False,
    )
    assert result.verdict == "WARN"
    assert result.exit_code == 1
    assert any(r.code == "campaign_code" for r in result.reasons)

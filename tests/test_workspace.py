import csv
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from linkcheck.dataset import DatasetError, parse_dataset
from linkcheck import workspace
from linkcheck.workspace import prepare_workspace


@pytest.fixture
def raw_snapshot():
    data = {
        "built": "2026-11-15 18:55 UTC",
        "cats": [{"id": "other", "name": "Other"}],
        "accounts": [
            {"h": "Alice", "name": "=HYPERLINK(\"https://example.com\")", "fol": 12, "gone": 0},
            {"h": "Bob", "name": "Bob", "fol": 2},
            {"h": "Carol", "name": "Carol"},
        ],
        "campaigns": [{
            "id": "campaign-1", "cat": "other", "title": "@SUM(1+1)",
            "pub": "Publisher", "url": "https://example.com/article", "date": "",
            "n": 3, "na": 2, "first": "2022-11-07", "last": "2022-11-22",
        }],
        "posts": [
            ["1589654913734578176", 0, 0, "2022-11-07", 0, None],
            ["1595055431763779584", 0, 0, "2022-11-22", 8, 99],
            ["1595055431763779585", 1, 0, "2022-11-22", 23, None, "https://web.archive.org/example"],
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2).encode()


def prepare(tmp_path, raw):
    snapshot = parse_dataset(raw, source="https://example.com/all.json", fetched_at_utc="2026-11-18T03:30:00Z")
    output = tmp_path / "workspace"
    manifest = prepare_workspace(snapshot, output, raw_bytes=raw)
    return output, manifest


def test_prepares_full_traceable_workspace(tmp_path, raw_snapshot):
    output, manifest = prepare(tmp_path, raw_snapshot)
    assert manifest["status"] == "complete"
    assert manifest["output_dir"] == str(output)
    assert manifest["counts"] == {"accounts": 3, "campaigns": 1, "posts": 3, "categories": 1,
                                  "zero_post_accounts": 1, "one_post_accounts": 1}
    assert (output / "raw/all.json").read_bytes() == raw_snapshot
    assert (output / "manifest.json").exists()
    for entry in manifest["files"]:
        content = (output / entry["path"]).read_bytes()
        assert len(content) == entry["bytes"]
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
    counts = json.loads((output / "account-counts.json").read_text())
    assert [a["handle"] for a in counts["zero_post_accounts"]] == ["Carol"]
    assert [a["handle"] for a in counts["one_post_accounts"]] == ["Bob"]
    assert counts["one_post_accounts"][0]["post"]["source_pointer"] == "/posts/2"


def test_sqlite_exact_ids_source_rows_and_relations(tmp_path, raw_snapshot):
    output, _ = prepare(tmp_path, raw_snapshot)
    with sqlite3.connect(f"file:{output / 'dataset.sqlite'}?mode=ro", uri=True) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT post_id, typeof(post_id) FROM posts ORDER BY post_id LIMIT 1").fetchone() == ("1589654913734578176", "text")
        assert conn.execute("SELECT handle, post_count FROM accounts ORDER BY account_index").fetchall() == [("Alice", 2), ("Bob", 1), ("Carol", 0)]
        row = conn.execute("SELECT post_id, handle, campaign_title, source_pointer, account_pointer, campaign_pointer FROM post_details WHERE post_id = ?", ("1595055431763779584",)).fetchone()
        assert row == ("1595055431763779584", "Alice", "@SUM(1+1)", "/posts/1", "/accounts/0", "/campaigns/0")
        encoded = conn.execute("SELECT raw_json FROM posts WHERE post_id = ?", ("1595055431763779585",)).fetchone()[0]
        assert json.loads(encoded) == json.loads(raw_snapshot)["posts"][2]
        assert conn.execute("SELECT flags, uninterpreted_flags, private, deleted, labelled_as_ad FROM posts WHERE post_id = ?", ("1595055431763779585",)).fetchone() == (23, 17, 1, 1, 0)
        indices = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"idx_posts_account_date", "idx_posts_campaign_date", "idx_posts_date", "idx_posts_ad_date", "idx_campaigns_category"} <= indices
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM posts")


def test_csv_escape_and_sqlite_keep_raw_text(tmp_path, raw_snapshot):
    output, manifest = prepare(tmp_path, raw_snapshot)
    with (output / "posts.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["id"] == "'1589654913734578176"
    assert rows[0]["name"].startswith("'=HYPERLINK")
    assert rows[0]["campaign_title"] == "'@SUM(1+1)"
    assert rows[0]["views"] == ""
    assert rows[0]["source_pointer"] == "/posts/0"
    assert "apostrophe" in manifest["csv"]["escaping"]
    with sqlite3.connect(output / "dataset.sqlite") as conn:
        assert conn.execute("SELECT name FROM accounts WHERE handle='Alice'").fetchone()[0].startswith("=HYPERLINK")


@pytest.mark.parametrize("value", ["=cmd", "+SUM(1)", "-1+1", "@SUM(1)", " \t=cmd", "\ntext", "\ttext", "\ufeff =cmd", "\ufeff \ufeff =cmd", "\x00=cmd"])
def test_formula_like_csv_values_receive_text_prefix(value):
    assert workspace._csv_cell(value).startswith("'")


@pytest.mark.parametrize("target_kind", ["empty_directory", "populated_directory", "file", "symlink", "dangling_symlink"])
def test_existing_target_is_never_overwritten(tmp_path, raw_snapshot, target_kind):
    target = tmp_path / "existing"
    if target_kind.endswith("directory"):
        target.mkdir()
        if target_kind == "populated_directory":
            (target / "keep.txt").write_text("keep")
    elif target_kind == "file":
        target.write_text("keep")
    else:
        actual = tmp_path / "actual"
        if target_kind == "symlink":
            actual.mkdir()
        target.symlink_to(actual, target_is_directory=True)
    snapshot = parse_dataset(raw_snapshot)
    with pytest.raises(DatasetError, match="already exists"):
        prepare_workspace(snapshot, target, raw_bytes=raw_snapshot)
    if target_kind == "populated_directory":
        assert (target / "keep.txt").read_text() == "keep"
    if target_kind == "file":
        assert target.read_text() == "keep"
    assert not (target / "manifest.json").exists()


def test_wrong_raw_bytes_do_not_create_directory(tmp_path, raw_snapshot):
    target = tmp_path / "new"
    snapshot = parse_dataset(raw_snapshot)
    with pytest.raises(DatasetError, match="hash and size"):
        prepare_workspace(snapshot, target, raw_bytes=raw_snapshot + b" ")
    assert not target.exists()


def test_modified_parsed_data_is_rejected(tmp_path, raw_snapshot):
    snapshot = parse_dataset(raw_snapshot)
    snapshot.data["accounts"][0]["name"] = "changed"
    with pytest.raises(DatasetError, match="changed after validation"):
        prepare_workspace(snapshot, tmp_path / "new", raw_bytes=raw_snapshot)


def test_uses_retained_raw_content_when_available(tmp_path, raw_snapshot):
    snapshot = parse_dataset(raw_snapshot)
    assert snapshot.raw_content == raw_snapshot
    result = prepare_workspace(snapshot, tmp_path / "workspace")
    assert result["snapshot"]["sha256"] == hashlib.sha256(raw_snapshot).hexdigest()


def test_missing_raw_bytes_is_an_error(tmp_path, raw_snapshot):
    snapshot = parse_dataset(raw_snapshot)
    snapshot.raw_content = b""
    with pytest.raises(DatasetError, match="Exact raw"):
        prepare_workspace(snapshot, tmp_path / "workspace")


def test_partial_failure_does_not_claim_complete(tmp_path, raw_snapshot, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("failure that might contain sensitive OS details")
    monkeypatch.setattr(workspace, "_write_database", fail)
    target = tmp_path / "workspace"
    with pytest.raises(DatasetError) as error:
        prepare_workspace(parse_dataset(raw_snapshot), target, raw_bytes=raw_snapshot)
    assert error.value.status == "incomplete"
    assert "sensitive" not in str(error.value)
    assert target.is_dir()
    assert (target / "raw/all.json").read_bytes() == raw_snapshot
    assert not (target / "manifest.json").exists()


def test_export_never_reads_tokens_or_fetches_posts(tmp_path, raw_snapshot, monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "never-output-this-secret")
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "never-output-this-other-secret")
    def fail(*args, **kwargs):
        pytest.fail("workspace export must be offline")
    monkeypatch.setattr("requests.Session.get", fail)
    output, manifest = prepare(tmp_path, raw_snapshot)
    for info in manifest["files"]:
        assert b"never-output-this" not in (output / info["path"]).read_bytes()
    assert "never-output-this" not in (output / "manifest.json").read_text()


def test_sqlite_integer_overflow_is_an_incomplete_export(tmp_path, raw_snapshot):
    data = json.loads(raw_snapshot)
    data["accounts"][0]["fol"] = 1 << 70
    raw = json.dumps(data).encode()
    target = tmp_path / "workspace"
    with pytest.raises(DatasetError) as error:
        prepare_workspace(parse_dataset(raw), target)
    assert error.value.status == "incomplete"
    assert not (target / "manifest.json").exists()


def test_empty_valid_snapshot_still_exports_tables(tmp_path):
    raw = json.dumps({"built": "now", "cats": [], "accounts": [], "campaigns": [], "posts": []}).encode()
    output, manifest = prepare(tmp_path, raw)
    assert manifest["counts"]["posts"] == 0
    with sqlite3.connect(output / "dataset.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM post_details").fetchone() == (0,)

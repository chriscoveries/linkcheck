import csv
import io
import json

import pytest

from linkcheck.cli import main
from linkcheck.cli_dataset import _csv_cell


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.json"
    data = {
        "built": "2026-11-15 18:55 UTC",
        "cats": [{"id": "other", "name": "Other"}],
        "accounts": [{"h": "Alice"}, {"h": "Bob"}, {"h": "Carol"}],
        "campaigns": [{"id": "one", "cat": "other", "title": "A title", "n": 3, "na": 2,
                       "first": "2022-11-07", "last": "2022-11-22"}],
        "posts": [["1589654913734578176", 0, 0, "2022-11-07", 0, None],
                  ["1595055431763779584", 0, 0, "2022-11-22", 8, 12],
                  ["1595055431763779585", 1, 0, "2022-11-22", 6, None]],
    }
    path.write_text(json.dumps(data))
    return path


def command(source, *args):
    return ["dataset", args[0], "--source", str(source), *args[1:]]


def test_real_nested_cli_account(source, capsys):
    assert main(command(source, "account", "--handle", "@ALICE", "--json")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["post_count"] == 2
    assert result["posts"][1]["source_pointer"] == "/posts/1"


def test_real_nested_cli_counts(source, capsys):
    assert main(command(source, "counts", "--json")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["zero_post_count"] == result["one_post_count"] == 1
    assert result["one_post_accounts"][0]["handle"] == "Bob"


def test_real_query_pagination_and_filters(source, capsys):
    assert main(command(source, "posts", "--handle", "alice", "--sort", "date", "--desc", "--limit", "1", "--json")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["total_matched"] == 2
    assert result["returned_count"] == 1
    assert result["rows"][0]["id"] == "1595055431763779584"
    assert main(command(source, "posts", "--ad", "labelled", "--all", "--json")) == 0
    assert json.loads(capsys.readouterr().out)["total_matched"] == 1


@pytest.mark.parametrize("entity", ["accounts", "campaigns"])
def test_aggregate_commands_parse(source, capsys, entity):
    assert main(command(source, entity, "--min-posts", "1", "--max-posts", "3", "--sort", "posts", "--all", "--json")) == 0
    assert json.loads(capsys.readouterr().out)["returned_count"] > 0


@pytest.mark.parametrize("entity", ["account", "posts", "accounts", "campaigns"])
def test_unknown_account_is_explicit_nonzero_status(source, capsys, entity):
    assert main(command(source, entity, "--handle", "Nobody", "--json")) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "account_not_listed"
    assert result.get("post_count") is None


def test_invalid_source_cannot_report_zero(source, capsys):
    source.write_text('{"accounts":[]')
    assert main(command(source, "counts", "--json")) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "invalid"
    assert "zero_post_count" not in result


def test_csv_keeps_pagination_provenance_on_stderr(source, capsys):
    assert main(command(source, "posts", "--limit", "1", "--format", "csv")) == 0
    output = capsys.readouterr()
    rows = list(csv.DictReader(io.StringIO(output.out)))
    meta = json.loads(output.err)
    assert len(rows) == 1
    assert rows[0]["id"] == "'1589654913734578176"
    assert meta["total_matched"] == 3 and meta["returned_count"] == 1
    assert len(meta["snapshot"]["sha256"]) == 64


def test_empty_csv_has_headers_without_invented_status_row(source, capsys):
    assert main(command(source, "posts", "--search", "no match", "--format", "csv")) == 0
    output = capsys.readouterr()
    assert list(csv.DictReader(io.StringIO(output.out))) == []
    assert json.loads(output.err)["total_matched"] == 0


@pytest.mark.parametrize("value", ["=cmd", "+SUM(1)", "@bad", " \ufeff \ufeff =cmd", "\x00=cmd"])
def test_cli_csv_escapes_formula_like_cells(value):
    assert _csv_cell(value).startswith("'")


def test_cli_csv_short_ids_keep_leading_zeros():
    assert _csv_cell("000123", text_id=True) == "'000123"


def test_match_csv_includes_absent_and_skipped_inputs(source, tmp_path, capsys):
    references = tmp_path / "own-posts.json"
    references.write_text(json.dumps([{"id": "1589654913734578176"}, {"id": "777"},
                                     {"platform": "mastodon", "id": "123"}]))
    assert main(command(source, "match", "--posts-file", str(references), "--format", "csv")) == 0
    output = capsys.readouterr()
    rows = list(csv.DictReader(io.StringIO(output.out)))
    assert [r["match_status"] for r in rows] == ["matched", "not_in_dataset", "skipped"]
    assert json.loads(output.err)["skipped_count"] == 1


def test_match_text_shows_conflicts_and_reference_coverage(source, tmp_path, capsys):
    references = tmp_path / "own-posts.json"
    references.write_text(json.dumps([{"id": "1595055431763779584", "author_handle": "Other", "date": "2022-11-23"},
                                     {"id": "777"}, {"id": "123", "platform": "mastodon"}]))
    assert main(command(source, "match", "--posts-file", str(references))) == 0
    output = capsys.readouterr().out
    assert "author=differs" in output and "date=differs" in output
    assert "not_in_dataset" in output and "platform_not_x" in output
    assert '"complete_account_history": false' in output
    assert "have not been independently verified" in output


def test_runtime_schema_command(capsys):
    assert main(["runtime", "--schema", "dataset"]) == 0
    assert "Source schema" in capsys.readouterr().out


def test_prepare_cli_refuses_existing_directory(source, tmp_path, capsys):
    target = tmp_path / "prepared audit"
    assert main(command(source, "prepare", "--output", str(target), "--json")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["posts"] == 3
    assert (target / "dataset.sqlite").is_file()
    assert main(command(source, "prepare", "--output", str(target), "--json")) == 2
    assert "exists" in json.loads(capsys.readouterr().out)["error"]


def test_runtime_still_parses_and_lists_dataset_playbooks(capsys):
    assert main(["runtime", "--json"]) == 0
    assert "explore-dataset" in {p["id"] for p in json.loads(capsys.readouterr().out)["playbooks"]}


def test_legacy_positional_urls_parse(monkeypatch, capsys):
    from linkcheck import cli
    from linkcheck.models import CheckResult

    observed = {}
    def check(text, **kwargs):
        observed.update(text=text, extra_urls=kwargs["extra_urls"])
        return CheckResult(verdict="OK", exit_code=0)

    monkeypatch.setattr(cli, "run_check", check)
    assert main(["--json", "--no-age", "https://example.com/a", "https://example.com/b"]) == 0
    assert len(observed["extra_urls"]) == 2
    assert json.loads(capsys.readouterr().out)["verdict"] == "OK"

import hashlib
import json
import socket

import pytest
import requests

from linkcheck import dataset
from linkcheck.dataset import DatasetError, load_dataset, load_post_references, parse_dataset


@pytest.fixture
def body():
    return {
        "built": "2026-11-15 18:55 UTC",
        "cats": [{"id": "other", "name": "Other"}],
        "accounts": [{"h": "Alice", "name": "Alice Smith"}, {"h": "Bob"}, {"h": "Carol"}],
        "campaigns": [{"id": "campaign-1", "cat": "other", "title": "Example", "pub": "Publisher",
                       "url": "https://example.com/article", "n": 3, "na": 2,
                       "first": "2022-11-07", "last": "2022-11-22"}],
        "posts": [
            ["1589654913734578176", 0, 0, "2022-11-07", 0, None],
            ["1595055431763779584", 0, 0, "2022-11-22", 8, None],
            ["1595055431763779585", 1, 0, "2022-11-22", 6, 5, "https://web.archive.org/example"],
        ],
    }


def snapshot(body):
    return parse_dataset(json.dumps(body).encode(), source="fixture", fetched_at_utc="2026-11-18T00:00:00Z")


def test_compact_join_has_exact_pointers_ids_and_flags(body):
    report = snapshot(body).account_report(" @aLiCe ")
    assert report["status"] == "complete"
    assert report["account"]["index"] == 0
    assert report["account"]["source_pointer"] == "/accounts/0"
    assert report["post_count"] == 2
    post = report["posts"][1]
    assert post["raw_record"] == body["posts"][1]
    assert post["id"] == "1595055431763779584"
    assert post["url"] == "https://x.com/Alice/status/1595055431763779584"
    assert post["source_pointer"] == "/posts/1"
    assert post["campaign_pointer"] == "/campaigns/0"
    assert post["campaign_id"] == "campaign-1"
    assert post["labelled_as_ad"] is True
    assert post["deleted"] is False
    assert post["private"] is False
    assert post["views"] is None


def test_zero_and_one_counts_include_unavailable_posts(body):
    report = snapshot(body).counts_report()
    assert report["zero_post_count"] == 1
    assert [a["handle"] for a in report["zero_post_accounts"]] == ["Carol"]
    assert report["one_post_count"] == 1
    sole = report["one_post_accounts"][0]
    assert sole["handle"] == "Bob"
    assert sole["post"]["deleted"] is True
    assert sole["post"]["private"] is True
    assert sole["post"]["labelled_as_ad"] is False
    assert sole["post"]["archive_url"] == "https://web.archive.org/example"


def test_absent_account_is_distinct_from_listed_zero(body):
    data = snapshot(body)
    assert data.account_report("Carol")["post_count"] == 0
    absent = data.account_report("Nobody")
    assert absent["status"] == "account_not_listed"
    assert absent["post_count"] is None
    assert absent["account"] is None


def test_original_bytes_are_hashed(body):
    raw = json.dumps(body, indent=2).encode()
    data = parse_dataset(raw)
    assert data.metadata()["sha256"] == hashlib.sha256(raw).hexdigest()
    assert data.metadata()["bytes"] == len(raw)
    assert data.metadata()["post_count"] == data.metadata()["unique_post_count"] == 3
    assert data.raw_content == raw


def test_original_bytes_preserved_with_bom_and_whitespace(body):
    raw = b"\xef\xbb\xbf  " + json.dumps(body, indent=4).encode() + b"\n\n"
    data = parse_dataset(raw)
    assert data.raw_content == raw
    assert data.sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("post_date,raw_views,expected_views", [
    ("2020-08-26", 0, None),
    ("2022-12-31", 0, None),
    ("2023-01-01", 0, 0),
    ("2026-11-15", 0, 0),
    ("2022-12-31", 123, 123),
    ("2023-01-01", 123, 123),
    ("2022-12-31", None, None),
    ("2023-01-01", None, None),
])
def test_views_follow_frontend_rule_without_mutating_evidence(body, post_date, raw_views, expected_views):
    body["posts"][0][3] = post_date
    body["posts"][0][5] = raw_views
    body["campaigns"][0]["first"] = min(row[3] for row in body["posts"])
    body["campaigns"][0]["last"] = max(row[3] for row in body["posts"])
    raw = json.dumps(body, indent=2).encode()
    data = parse_dataset(raw)
    metadata = data.metadata()

    post = data.post_record(0)
    assert post["views"] == expected_views
    assert post["raw_record"] == body["posts"][0]
    assert post["raw_record"][5] == raw_views
    assert data.account_report("Alice")["posts"][0]["views"] == expected_views
    assert data.data == body
    assert data.raw_content == raw
    assert data.sha256 == hashlib.sha256(raw).hexdigest()
    assert data.metadata() == metadata


@pytest.mark.parametrize("key", ["posts", "accounts", "campaigns", "cats", "built"])
def test_missing_required_field_cannot_be_zero(body, key):
    del body[key]
    with pytest.raises(DatasetError):
        snapshot(body)


def test_truncated_posts_rejected_even_if_valid_json(body):
    body["posts"].pop()
    with pytest.raises(DatasetError, match="declared counts"):
        snapshot(body)


def test_no_posts_with_nonzero_declared_counts_rejected(body):
    body["posts"] = []
    with pytest.raises(DatasetError, match="declared counts"):
        snapshot(body)


@pytest.mark.parametrize("position,value", [(0, 1595055431763779584), (0, "abc"), (1, -1), (1, 10),
                                           (1, True), (2, 1), (3, "2022-02-30"), (3, "2022-1-1"),
                                           (4, True), (4, -1), (5, -2), (5, 1.5)])
def test_malformed_row_rejected(body, position, value):
    body["posts"][0][position] = value
    with pytest.raises(DatasetError):
        snapshot(body)


def test_duplicate_post_id_rejected(body):
    body["posts"][1][0] = body["posts"][0][0]
    with pytest.raises(DatasetError, match="duplicate post ID"):
        snapshot(body)


def test_new_unknown_compact_fields_require_schema_review(body):
    body["posts"][0].extend([None, "unknown future field"])
    with pytest.raises(DatasetError, match="optional archive"):
        snapshot(body)


def test_duplicate_handle_is_case_insensitive(body):
    body["accounts"][1]["h"] = "alice"
    with pytest.raises(DatasetError, match="duplicate account"):
        snapshot(body)


@pytest.mark.parametrize("section,key,value", [
    ("accounts", "name", []), ("accounts", "av", 8), ("accounts", "fol", True),
    ("accounts", "gone", -1), ("campaigns", "title", {}), ("campaigns", "pub", 9),
    ("campaigns", "url", []), ("campaigns", "date", False), ("campaigns", "fav", []),
    ("campaigns", "cat", []), ("cats", "name", {}), ("cats", "id", ""),
])
def test_known_field_types_rejected_without_type_errors(body, section, key, value):
    body[section][0][key] = value
    with pytest.raises(DatasetError):
        snapshot(body)


def test_unknown_account_fields_omitted_from_report(body):
    body["accounts"][0]["private_note"] = "not-public-metadata"
    assert "private_note" not in snapshot(body).account_report("Alice")["account"]


@pytest.mark.parametrize("url", ["https://[malformed", "https://example.com:bad/x", "https:///x", "https://user:secret@example.com/x"])
def test_bad_archive_url_does_not_escape_as_value_error(body, url):
    body["posts"][0].append(url)
    with pytest.raises(DatasetError):
        snapshot(body)


def test_metadata_range_disagreement_rejected(body):
    body["campaigns"][0]["first"] = "2020-01-01"
    with pytest.raises(DatasetError, match="date disagrees"):
        snapshot(body)


@pytest.mark.parametrize("raw", [b'{"posts":', b'{"posts":[],"posts":[]}', b'{"a":NaN}', b'\xff'])
def test_bad_json_rejected(raw):
    with pytest.raises(DatasetError):
        parse_dataset(raw)


def test_unknown_flag_bits_preserved(body):
    body["posts"][0][4] = 17
    result = snapshot(body).account_report("Alice")["posts"][0]
    assert result["flags"] == 17
    assert result["uninterpreted_flags"] == 17


def test_match_exact_ids_dedupes_references_and_preserves_author_conflict(body):
    result = snapshot(body).match_posts([
        {"id": "1589654913734578176", "author_handle": "Alice"},
        {"id": "1589654913734578176"},
        {"id": "1595055431763779584", "author_handle": "Different"},
        {"id": "999"},
        {"platform": "mastodon", "id": "1595055431763779585"},
    ])
    assert result["matched_count"] == 2
    assert result["duplicate_reference_count"] == 1
    assert result["not_in_dataset_count"] == 1
    assert result["skipped_count"] == 1
    assert [m["author_check"] for m in result["matched"]] == ["agrees", "differs"]
    assert result["scope"] == "supplied_post_references_only"


def test_duplicate_author_and_date_evidence_is_never_discarded(body):
    report = snapshot(body).match_posts([
        {"id": "1589654913734578176", "author_handle": "Alice", "date": "2022-11-07"},
        {"id": "1589654913734578176", "author_handle": "Mallory", "date": "2022-11-08"},
    ])
    result = report["matched"][0]
    assert result["author_check"] == result["date_check"] == "conflicting"
    assert len(result["references"]) == 2
    assert report["duplicate_reference_count"] == 1


def test_status_url_path_is_labelled_as_unverified_evidence(body):
    report = snapshot(body).match_posts(["https://x.com/Alice/status/1589654913734578176"])
    result = report["matched"][0]
    assert result["author_check"] == "agrees"
    assert result["reference"]["author_handle_source"] == "url_path"
    assert "not proof of authorship" in report["verification_note"]


def test_x_status_url_and_id_disagreement_rejected(body):
    with pytest.raises(DatasetError, match="disagrees"):
        snapshot(body).match_posts([{"id": "123", "url": "https://x.com/Alice/status/456"}])


def test_import_x_api_json_and_omit_text_and_secrets(tmp_path, body):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps({"data": [{"id": "1589654913734578176", "text": "private text", "token": "secret"}]}))
    records = load_post_references(path)
    assert records == [{"id": "1589654913734578176", "platform": "x", "source_pointer": "/data/0"}]
    assert snapshot(body).match_posts(records)["matched_count"] == 1


def test_x_api_single_post_expands_author_and_date(tmp_path, body):
    path = tmp_path / "post.json"
    path.write_text(json.dumps({
        "data": {"id": "1589654913734578176", "author_id": "123", "created_at": "2022-11-07T05:00:00Z", "text": "private"},
        "includes": {"users": [{"id": "123", "username": "Alice", "name": "ignored name", "token": "secret"}]},
    }))
    refs = load_post_references(path)
    assert refs[0] == {"id": "1589654913734578176", "platform": "x", "source_pointer": "/data",
                       "author_id": "123", "author_handle": "Alice", "author_handle_source": "api_expansion", "date": "2022-11-07"}
    result = snapshot(body).match_posts(refs)["matched"][0]
    assert result["author_check"] == result["date_check"] == "agrees"
    assert "private" not in json.dumps(refs)
    assert "secret" not in json.dumps(refs)


def test_x_api_next_token_is_redacted_and_coverage_is_page_only(tmp_path, body):
    path = tmp_path / "page.json"
    path.write_text(json.dumps({"data": [{"id": "1589654913734578176"}],
                                "meta": {"result_count": 1, "next_token": "private-pagination-token"}}))
    result = snapshot(body).match_posts(load_post_references(path))
    assert result["reference_coverage"]["more_pages_available"] is True
    assert result["reference_coverage"]["complete_account_history"] is False
    assert "private-pagination-token" not in json.dumps(result)


@pytest.mark.parametrize("meta", [{"result_count": 2}, {"result_count": True}, {"next_token": {}}])
def test_x_api_inconsistent_metadata_rejected(tmp_path, meta):
    path = tmp_path / "page.json"
    path.write_text(json.dumps({"data": [{"id": "123"}], "meta": meta}))
    with pytest.raises(DatasetError):
        load_post_references(path)


def test_x_api_expanded_author_conflict_rejected(tmp_path):
    path = tmp_path / "page.json"
    path.write_text(json.dumps({"data": [{"id": "123", "author_id": "456", "author_handle": "Alice"}],
                                "includes": {"users": [{"id": "456", "username": "Bob"}]}}))
    with pytest.raises(DatasetError, match="author handle disagrees"):
        load_post_references(path)


@pytest.mark.parametrize("record", [
    {"id": "123", "author_handle": "Alice", "username": "Bob"},
    {"id": "123", "date": "2022-11-07", "created_at": "2022-11-08T00:00:00Z"},
    {"id": "123", "errors": [{"detail": "private error"}]},
])
def test_conflicting_or_failed_individual_reference_is_rejected(tmp_path, record):
    path = tmp_path / "records.json"
    path.write_text(json.dumps([record]))
    with pytest.raises(DatasetError) as exc:
        load_post_references(path)
    assert "private error" not in str(exc.value)


def test_single_post_api_result_count_must_match(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"data":{"id":"123"},"meta":{"result_count":0}}')
    with pytest.raises(DatasetError, match="count disagrees"):
        load_post_references(path)


@pytest.mark.parametrize("record", [
    {"id": "123", "author_id": 9007199254740993}, {"id": "123", "date": "unknown secret date"},
    {"id": "123", "created_at": "2022-11-07T12:00:00"}, {"id": "123", "author_handle_source": []},
    {"id": "123", "source_pointer": ["secret"]}, {"id": "123", "source_pointer": "unanchored"},
    {"id": "123", "source_pointer": "/bad~escape"}, {"id": "123", "platform": {}},
])
def test_invalid_reference_metadata_fails_without_echoing_content(tmp_path, record):
    path = tmp_path / "page.json"
    path.write_text(json.dumps([record]))
    with pytest.raises(DatasetError) as exc:
        load_post_references(path)
    assert "secret" not in str(exc.value)


def test_other_platform_url_cannot_match_numeric_x_id(body):
    report = snapshot(body).match_posts(["https://mastodon.social/@Alice/1589654913734578176"])
    assert report["matched_count"] == 0
    assert report["skipped_count"] == 1


def test_legacy_archive_timestamp_is_converted_to_utc_day(tmp_path):
    path = tmp_path / "tweets.js"
    path.write_text('window.YTD.tweet.part0 = [{"tweet":{"id_str":"123","created_at":"Mon Nov 07 01:30:00 +0200 2022"}}];')
    assert load_post_references(path)[0]["date"] == "2022-11-06"


def test_import_jsonl_and_urls(tmp_path):
    path = tmp_path / "posts.jsonl"
    path.write_text('{"url":"https://twitter.com/Alice/status/123?s=20"}\n{"url":"https://x.com/i/web/status/456"}\n')
    records = load_post_references(path)
    assert [r["id"] for r in records] == ["123", "456"]
    assert records[0]["author_handle"] == "Alice"
    assert "author_handle" not in records[1]


def test_archive_assignment_is_parsed_without_evaluation(tmp_path):
    path = tmp_path / "tweets.js"
    path.write_text('window.YTD.tweets.part0 = [{"tweet":{"id_str":"1589654913734578176","full_text":"private"}}];')
    records = load_post_references(path)
    assert records[0]["id"] == "1589654913734578176"
    assert records[0]["source_pointer"] == "/0/tweet"
    assert "full_text" not in records[0]


@pytest.mark.parametrize("content", [
    'window.YTD.tweets.part0 = []; alert("bad");',
    'window.other = [];',
    'window.YTD.tweets.part0 = do_something();',
])
def test_executable_archive_content_rejected(tmp_path, content):
    path = tmp_path / "tweets.js"
    path.write_text(content)
    with pytest.raises(DatasetError):
        load_post_references(path)


def test_unsafe_numeric_reference_rejected(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text('[{"id":1589654913734578176}]')
    with pytest.raises(DatasetError, match="exact string"):
        load_post_references(path)


def test_id_str_preferred_to_legacy_numeric_id(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text('[{"id_str":"1589654913734578176","id":1589654913734578176}]')
    assert load_post_references(path)[0]["id"] == "1589654913734578176"


def test_conflicting_string_ids_rejected(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text('[{"id_str":"123","id":"456"}]')
    with pytest.raises(DatasetError, match="fields disagree"):
        load_post_references(path)


def test_single_json_string_reference(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text('"https://x.com/Alice/status/123"')
    assert load_post_references(path)[0]["id"] == "123"


def test_provider_error_not_empty_success(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text('{"data":[],"errors":[{"detail":"forbidden"}]}')
    with pytest.raises(DatasetError, match="reported an error"):
        load_post_references(path)


def test_local_lookup_and_match_do_not_request_network(tmp_path, body, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Local matching must not request the network")
    monkeypatch.setattr(requests.Session, "get", denied)
    path = tmp_path / "all.json"
    path.write_text(json.dumps(body))
    result = load_dataset(str(path)).match_posts([{"id": "1589654913734578176"}])
    assert result["matched_count"] == 1


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://[::1]/x", "http://localhost/x", "file:///tmp/all.json", "https://user:secret@example.com/x"])
def test_private_or_credential_urls_rejected(url):
    with pytest.raises(DatasetError):
        dataset._public_url(url)


def test_private_dns_answer_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))])
    with pytest.raises(DatasetError):
        dataset._public_url("https://example.com/all.json")


class Response:
    def __init__(self, raw=b"", *, status=200, headers=None):
        self.raw, self.status_code, self.headers = raw, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size):
        yield self.raw


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_public_fetch_is_unauthenticated_and_validates_redirects(body, monkeypatch):
    session = Session([Response(status=302, headers={"Location": "/actual.json"}), Response(json.dumps(body).encode())])
    checked = []
    monkeypatch.setattr(dataset, "_PublicSession", lambda: session)
    monkeypatch.setattr(dataset, "_public_url", checked.append)
    monkeypatch.setenv("X_BEARER_TOKEN", "do-not-use")
    result = load_dataset("https://example.com/all.json?token=do-not-report")
    assert session.trust_env is True
    assert isinstance(session.auth, dataset._NoAuth)
    assert checked == ["https://example.com/all.json?token=do-not-report", "https://example.com/actual.json"]
    assert all(call[1] == {"timeout": (5, 20), "allow_redirects": False, "stream": True} for call in session.calls)
    assert result.metadata()["source"] == "https://example.com/all.json"


def test_network_errors_do_not_echo_secret_request_details(monkeypatch):
    session = Session([requests.ConnectionError("Authorization: Bearer secret")])
    monkeypatch.setattr(dataset, "_PublicSession", lambda: session)
    monkeypatch.setattr(dataset, "_public_url", lambda u: None)
    with pytest.raises(DatasetError) as exc:
        load_dataset("https://example.com/all.json")
    assert exc.value.status == "unavailable"
    assert "secret" not in str(exc.value)


def test_fetch_body_size_cap(monkeypatch):
    session = Session([Response(b"x" * 21)])
    monkeypatch.setattr(dataset, "_PublicSession", lambda: session)
    monkeypatch.setattr(dataset, "_public_url", lambda u: None)
    monkeypatch.setattr(dataset, "MAX_BYTES", 20)
    with pytest.raises(DatasetError, match="size limit"):
        load_dataset("https://example.com/all.json")


def test_public_session_never_loads_netrc_on_initial_request_or_redirect(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Dataset fetch must not inspect .netrc")
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", denied)
    with dataset._PublicSession() as session:
        session.auth = dataset._NoAuth()
        request = session.prepare_request(requests.Request("GET", "https://example.com/all.json"))
        assert "Authorization" not in request.headers
        assert session.trust_env is True
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = "https://example.org/all.json"
        response.request = request
        assert list(session.resolve_redirects(response, request, yield_requests=True)) == []


def test_local_directory_rejected_as_source(tmp_path):
    with pytest.raises(DatasetError, match="regular file"):
        load_dataset(str(tmp_path))


def test_local_file_size_limit(tmp_path, monkeypatch):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * 21)
    monkeypatch.setattr(dataset, "MAX_BYTES", 20)
    with pytest.raises(DatasetError, match="size limit"):
        load_dataset(str(path))


def test_invalid_redirect_is_redacted(monkeypatch):
    session = Session([Response(status=302, headers={"Location": "https://[secret"})])
    monkeypatch.setattr(dataset, "_PublicSession", lambda: session)
    monkeypatch.setattr(dataset, "_public_url", lambda u: None)
    with pytest.raises(DatasetError) as exc:
        load_dataset("https://example.com/all.json")
    assert "secret" not in str(exc.value)

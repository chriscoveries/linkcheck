"""Regression checks for pure exploration of a published compact snapshot."""

import copy
import json

import pytest

from linkcheck.dataset import DatasetError, parse_dataset
from linkcheck.explore import (
    ACCOUNT_SORTS,
    AVAILABILITY,
    CAMPAIGN_SORTS,
    POST_SORTS,
    query_accounts,
    query_campaigns,
    query_posts,
)


@pytest.fixture
def body():
    return {
        "built": "2026-11-15 18:55 UTC",
        "cats": [{"id": "AI", "name": "Artificial intelligence"},
                 {"id": "other", "name": "Other"}],
        "accounts": [{"h": "Alice", "name": "Alice Example", "fol": 100},
                     {"h": "Bob", "name": "Bob Example", "fol": 100},
                     {"h": "Carol", "name": None, "fol": None},
                     {"h": "Dan", "name": "Daniel Example"}],
        "campaigns": [
            {"id": "alpha", "cat": "AI", "title": "Alpha [literal]", "pub": "Publication",
             "url": "https://example.com/alpha", "n": 3, "na": 2,
             "first": "2022-11-07", "last": "2022-11-22"},
            {"id": "beta", "cat": "other", "title": "Beta", "pub": "Other publisher",
             "url": "https://example.com/beta", "n": 2, "na": 2,
             "first": "2022-11-22", "last": "2022-11-23"},
            {"id": "empty", "cat": "other", "title": None, "pub": None,
             "url": "https://example.com/empty", "n": 0, "na": 0, "first": "", "last": ""},
        ],
        "posts": [
            ["9007199254740993", 0, 0, "2022-11-07", 0, None],
            ["9007199254740995", 0, 0, "2022-11-22", 8, 0],
            ["9007199254740994", 1, 0, "2022-11-22", 6, 10, "https://web.archive.org/example"],
            ["10", 0, 1, "2022-11-22", 4, None],
            ["2", 3, 1, "2022-11-23", 17, 20],
        ],
    }


def make_snapshot(body):
    return parse_dataset(json.dumps(body).encode(), source="fixture",
                         fetched_at_utc="2026-11-18T00:00:00Z")


@pytest.fixture
def snapshot(body):
    return make_snapshot(body)


def ids(report):
    return [row["id"] for row in report["rows"]]


def handles(report):
    return [row["handle"] for row in report["rows"]]


def test_post_query_has_joined_evidence_and_snapshot_hash(snapshot, body):
    result = query_posts(snapshot, handle=" @aLiCe ", category="ai", campaign="ALPHA")
    assert result["status"] == "complete"
    assert result["total_matched"] == result["returned_count"] == 2
    assert result["snapshot"] == snapshot.metadata()
    assert result["filters"]["handle"] == "Alice"
    assert result["filters"]["category"] == "AI"
    assert result["filters"]["campaign"] == "alpha"
    row = result["rows"][1]
    assert row["id"] == "9007199254740995"
    assert row["source_pointer"] == "/posts/1"
    assert row["account_pointer"] == "/accounts/0"
    assert row["campaign_pointer"] == "/campaigns/0"
    assert row["raw_record"] == body["posts"][1]
    assert row["url"] == "https://x.com/Alice/status/9007199254740995"
    assert row["labelled_as_ad"] is True
    assert "no post text" in result["search_scope"]


def test_count_bounds_can_find_true_zero_and_one_accounts(snapshot):
    zero = query_accounts(snapshot, min_posts=0, max_posts=0)
    one = query_accounts(snapshot, min_posts=1, max_posts=1, sort="handle")
    assert handles(zero) == ["Carol"]
    assert handles(one) == ["Bob", "Dan"]
    assert zero["rows"][0]["post_count"] == 0
    assert zero["rows"][0]["first"] is None
    assert zero["rows"][0]["views"] is None
    assert one["rows"][0]["deleted_count"] == one["rows"][0]["private_count"] == 1


def test_exact_handle_selector_retains_a_listed_zero(snapshot):
    assert handles(query_accounts(snapshot, handle="carol")) == ["Carol"]
    assert query_posts(snapshot, handle="Carol")["total_matched"] == 0
    with pytest.raises(DatasetError) as exc:
        query_accounts(snapshot, handle="Nobody")
    assert exc.value.status == "account_not_listed"


def test_account_aggregates_use_selected_posts_and_keep_full_total(snapshot):
    rows = query_accounts(snapshot, category="other", sort="handle")["rows"]
    assert [row["handle"] for row in rows] == ["Alice", "Dan"]
    alice = rows[0]
    assert alice["post_count"] == 1
    assert alice["total_post_count"] == 3
    assert alice["campaign_count"] == 1
    assert alice["category_ids"] == ["other"]
    assert alice["first"] == alice["last"] == "2022-11-22"
    assert alice["ad_count"] == 0
    assert alice["private_count"] == 1
    assert alice["source_pointer"] == "/accounts/0"
    assert query_accounts(snapshot, category="other", max_posts=0)["total_matched"] == 0


def test_summary_includes_partial_view_coverage_and_unknown_flags(snapshot):
    alice = query_accounts(snapshot, handle="Alice")["rows"][0]
    assert alice["views"] is None
    assert alice["views_known_count"] == 0
    assert alice["post_count"] == 3
    old_zero = query_posts(snapshot, ad=True)["rows"][0]
    assert old_zero["views"] is None
    assert old_zero["raw_record"][5] == 0
    dan = query_accounts(snapshot, handle="Dan")["rows"][0]
    assert dan["uninterpreted_flag_count"] == 1
    assert dan["ad_count"] == 0
    assert dan["views"] == 20


def test_account_and_campaign_view_coverage_preserve_zero_from_2023(body):
    body["posts"][1][3] = "2023-01-01"
    body["campaigns"][0]["last"] = "2023-01-01"
    snapshot = make_snapshot(body)
    account = query_accounts(snapshot, handle="Alice")["rows"][0]
    assert account["views"] == 0
    assert account["views_known_count"] == 1
    assert account["post_count"] == 3
    campaign = query_campaigns(snapshot, campaign="alpha")["rows"][0]
    assert campaign["views"] == 10
    assert campaign["views_known_count"] == 2
    selected = query_campaigns(snapshot, since="2023-01-01")["rows"][0]
    assert selected["views"] == 0
    assert selected["views_known_count"] == selected["post_count"] == 1


def test_campaign_groups_aggregate_filtered_posts(snapshot, body):
    report = query_campaigns(snapshot, handle="Alice", sort="title")
    assert report["total_matched"] == 2
    alpha, beta = report["rows"]
    assert alpha["id"] == "alpha"
    assert alpha["post_count"] == 2
    assert alpha["total_post_count"] == 3
    assert alpha["account_count"] == 1
    assert alpha["ad_count"] == 1
    assert alpha["raw_record"] == body["campaigns"][0]
    assert alpha["source_pointer"] == "/campaigns/0"
    assert beta["last"] == "2022-11-22"
    assert "destination URL group" in report["campaign_unit"]


def test_campaign_zero_group_policy(snapshot):
    assert ids(query_campaigns(snapshot, min_posts=0, max_posts=0)) == ["empty"]
    assert ids(query_campaigns(snapshot, campaign="EMPTY", max_posts=0)) == ["empty"]
    assert query_campaigns(snapshot, category="other", max_posts=0)["total_matched"] == 0


@pytest.mark.parametrize("mode,expected", [
    ("all", ["2", "10", "9007199254740993", "9007199254740994", "9007199254740995"]),
    ("available", ["2", "9007199254740993", "9007199254740995"]),
    ("deleted", ["9007199254740994"]),
    ("private", ["10", "9007199254740994"]),
    ("unavailable", ["10", "9007199254740994"]),
])
def test_availability_uses_independent_recorded_flags(snapshot, mode, expected):
    assert mode in AVAILABILITY
    assert ids(query_posts(snapshot, availability=mode, sort="id")) == expected


def test_unknown_bit_is_retained_without_becoming_unavailable(snapshot):
    dan = query_posts(snapshot, handle="Dan", availability="available")["rows"][0]
    assert dan["flags"] == 17
    assert dan["uninterpreted_flags"] == 17
    assert dan["deleted"] is dan["private"] is False


def test_date_bounds_are_inclusive_and_ad_false_is_not_omitted(snapshot):
    exact_date = query_posts(snapshot, since="2022-11-22", until="2022-11-22", sort="id")
    assert ids(exact_date) == ["10", "9007199254740994", "9007199254740995"]
    assert query_posts(snapshot, ad=False)["total_matched"] == 4
    assert ids(query_posts(snapshot, ad=True)) == ["9007199254740995"]
    assert query_accounts(snapshot, ad=False, handle="Alice")["rows"][0]["ad_count"] == 0


def test_search_is_literal_casefold_metadata_only(snapshot):
    assert query_posts(snapshot, search="[LITERAL]")["total_matched"] == 3
    assert query_posts(snapshot, search=".*")["total_matched"] == 0
    assert query_posts(snapshot, search="ARTIFICIAL INTELLIGENCE")["total_matched"] == 3
    assert query_posts(snapshot, search="Example.com/beta")["total_matched"] == 2
    assert query_posts(snapshot, search="BOB EXAMPLE")["total_matched"] == 1
    assert query_posts(snapshot, search="private post text")["total_matched"] == 0


def test_post_pagination_keeps_counts_before_slicing(snapshot):
    report = query_posts(snapshot, sort="id", offset=1, limit=2)
    assert report["total_matched"] == 5
    assert report["returned_count"] == 2
    assert report["offset"] == 1 and report["limit"] == 2
    assert ids(report) == ["10", "9007199254740993"]
    assert query_posts(snapshot, limit=0)["returned_count"] == 0
    assert query_posts(snapshot, limit=0)["total_matched"] == 5
    assert query_posts(snapshot, offset=9)["rows"] == []


def test_numeric_id_sort_preserves_exact_strings(snapshot):
    assert ids(query_posts(snapshot, sort="id")) == [
        "2", "10", "9007199254740993", "9007199254740994", "9007199254740995"]
    assert ids(query_posts(snapshot, sort="id", descending=True)) == [
        "9007199254740995", "9007199254740994", "9007199254740993", "10", "2"]


def test_arbitrary_decimal_string_ids_do_not_overflow(body):
    huge_id = "9" * 5000
    body["posts"][0][0] = huge_id
    report = query_posts(make_snapshot(body), sort="id", descending=True)
    assert report["rows"][0]["id"] == huge_id


@pytest.mark.parametrize("descending,expected", [
    (False, ["9007199254740994", "2", "10", "9007199254740993", "9007199254740995"]),
    (True, ["2", "9007199254740994", "10", "9007199254740993", "9007199254740995"]),
])
def test_post_null_values_are_last_in_either_sort_direction(snapshot, descending, expected):
    assert ids(query_posts(snapshot, sort="views", descending=descending)) == expected


@pytest.mark.parametrize("descending", [False, True])
def test_account_nulls_last_and_equal_values_tie_by_handle(snapshot, descending):
    assert handles(query_accounts(snapshot, sort="followers", descending=descending)) == [
        "Alice", "Bob", "Carol", "Dan"]
    rows = query_accounts(snapshot, sort="name", descending=descending)["rows"]
    assert rows[-1]["handle"] == "Carol"


@pytest.mark.parametrize("descending", [False, True])
def test_campaign_null_text_and_dates_last(snapshot, descending):
    assert query_campaigns(snapshot, sort="title", descending=descending)["rows"][-1]["id"] == "empty"
    assert query_campaigns(snapshot, sort="date", descending=descending)["rows"][-1]["id"] == "empty"


def test_descending_date_ties_stay_in_numeric_id_order(snapshot):
    result = query_posts(snapshot, sort="date", descending=True)
    assert ids(result) == ["2", "10", "9007199254740994", "9007199254740995", "9007199254740993"]


@pytest.mark.parametrize("function,sorts", [
    (query_posts, POST_SORTS), (query_accounts, ACCOUNT_SORTS), (query_campaigns, CAMPAIGN_SORTS),
])
def test_documented_sort_keys_are_supported(snapshot, function, sorts):
    for key in sorts:
        assert function(snapshot, sort=key)["sort"] == key


@pytest.mark.parametrize("function", [query_posts, query_accounts, query_campaigns])
@pytest.mark.parametrize("options", [
    {"since": "2022-1-01"}, {"since": "2022-02-30"}, {"until": "2022-11-22T00:00:00Z"},
    {"since": "2022-11-23", "until": "2022-11-22"}, {"since": 20221122},
    {"limit": -1}, {"limit": True}, {"limit": 1.5}, {"offset": -1}, {"offset": True},
    {"ad": 0}, {"ad": "false"}, {"descending": "false"}, {"sort": "unknown"},
    {"availability": "live"}, {"search": ""}, {"search": 5},
    {"handle": "invalid handle"}, {"handle": "@"}, {"category": "not-a-category"},
    {"campaign": "not-a-campaign"},
])
def test_invalid_filters_and_pagination_fail_closed(snapshot, function, options):
    with pytest.raises(DatasetError):
        function(snapshot, **options)


@pytest.mark.parametrize("function", [query_accounts, query_campaigns])
@pytest.mark.parametrize("options", [
    {"min_posts": -1}, {"max_posts": True}, {"min_posts": 1.5},
    {"min_posts": 2, "max_posts": 1},
])
def test_invalid_count_bounds_fail_closed(snapshot, function, options):
    with pytest.raises(DatasetError):
        function(snapshot, **options)


def test_casefold_ambiguous_category_is_rejected(body):
    body["cats"].append({"id": "ai", "name": "Ambiguous"})
    with pytest.raises(DatasetError, match="ambiguous"):
        query_posts(make_snapshot(body), category="AI")


def test_casefold_ambiguous_campaign_is_rejected(body):
    body["campaigns"].append({"id": "ALPHA", "cat": "AI", "n": 0, "na": 0})
    with pytest.raises(DatasetError, match="duplicate ID"):
        query_campaigns(make_snapshot(body), campaign="alpha")


def test_queries_do_not_mutate_snapshot_or_fetch_network(snapshot, monkeypatch):
    original = copy.deepcopy(snapshot.data)

    def no_network(*args, **kwargs):
        pytest.fail("Pure dataset queries must not fetch the network")

    monkeypatch.setattr("requests.sessions.Session.request", no_network)
    query_posts(snapshot, search="Example")
    query_accounts(snapshot, sort="followers", descending=True)
    query_campaigns(snapshot, category="AI")
    assert snapshot.data == original


def test_missing_optional_metadata_does_not_crash_sort(body):
    del body["accounts"][1]["fol"]
    body["accounts"][1]["name"] = None
    body["campaigns"][1]["title"] = None
    snapshot = make_snapshot(body)
    assert query_accounts(snapshot, sort="name")["rows"][-2:][0]["handle"] == "Bob"
    assert query_accounts(snapshot, handle="Bob")["rows"][0]["followers"] is None
    assert query_posts(snapshot, sort="campaign")["rows"][-1]["campaign_id"] == "beta"

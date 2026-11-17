from datetime import datetime, timezone

from linkcheck.script_match import compare_to_corpus, match_phrases, run_script_checks


def test_near_duplicate_across_three_accounts():
    now = datetime.now(timezone.utc).isoformat()
    line = (
        "this shared product update ensures continued leadership in the open market "
        "and rewards early supporters who stay engaged"
    )
    corpus = [
        {"account": "alice", "text": line, "created_at": now, "urls": []},
        {"account": "bob", "text": line + " !", "created_at": now, "urls": []},
        {"account": "carol", "text": line, "created_at": now, "urls": []},
        {"account": "dave", "text": "totally unrelated gardening tips", "created_at": now, "urls": []},
    ]
    report = compare_to_corpus(line, corpus, threshold=0.85, min_accounts=3)
    assert report.near_duplicate is True
    assert report.match_count_accounts >= 3
    assert any(f.code == "script_near_duplicate" for f in report.findings)


def test_phrase_list_and_shared_code(tmp_path):
    phrases = ["ensuring market leadership continues uninterrupted"]
    draft = "Folks, ensuring market leadership continues uninterrupted https://example.com/x?cid=deadbeef"
    assert match_phrases(draft, phrases)

    now = datetime.now(timezone.utc).isoformat()
    corpus_path = tmp_path / "corpus.jsonl"
    rows = [
        {
            "account": "a1",
            "text": "one",
            "created_at": now,
            "urls": ["https://example.com/p?cid=deadbeef"],
        },
        {
            "account": "a2",
            "text": "two",
            "created_at": now,
            "urls": ["https://example.com/q?cid=deadbeef"],
        },
        {
            "account": "a3",
            "text": "three",
            "created_at": now,
            "urls": ["https://example.com/r?cid=deadbeef"],
        },
    ]
    import json

    corpus_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    report = run_script_checks(
        draft,
        corpus_path=corpus_path,
        phrases=phrases,
        draft_urls=["https://example.com/x?cid=deadbeef"],
        min_accounts=3,
    )
    assert report.phrase_hits
    assert any(f.code == "script_phrase" for f in report.findings)
    assert any(f.code == "shared_tracking_code" for f in report.findings)

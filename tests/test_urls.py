from linkcheck.urls import extract_urls, strip_tracking


def test_extract_urls_and_strip():
    text = "See https://example.com/a?cid=abc&utm_campaign=x and also short.example/abcd"
    urls = extract_urls(text)
    assert urls[0].startswith("https://example.com/a")
    clean = strip_tracking(urls[0])
    assert "cid=" not in clean
    assert "utm_campaign=" not in clean
    assert clean.startswith("https://example.com/a")

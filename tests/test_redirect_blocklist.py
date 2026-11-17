"""Local HTTP redirect chain + blocklisted hop ⇒ BLOCK."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import requests

from linkcheck import check as check_mod
from linkcheck import tracer as tracer_mod
from linkcheck.check import run_check
from linkcheck.models import Hop


def _start_server() -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            port = self.server.server_address[1]
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{port}/mid")
                self.end_headers()
            elif self.path == "/mid":
                self.send_response(302)
                # Emit a Location that names a blocklisted host (no DNS needed for recording).
                self.send_header("Location", "http://tracker.example/click?cid=abc")
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_local_chain_records_hops_and_block_flags(tmp_path):
    server = _start_server()
    port = server.server_address[1]
    start = f"http://127.0.0.1:{port}/start"

    # Follow real local redirects; when Location points at tracker.example,
    # record that hop URL then stop (DNS would fail).
    def fetch(url: str):
        if "tracker.example" in url:
            raise requests.ConnectionError("name resolution mocked failure")
        return requests.get(url, allow_redirects=False, timeout=5)

    hops = tracer_mod.trace_url(start, fetch=fetch)
    server.shutdown()

    assert len(hops) >= 2
    assert hops[0].url == start
    assert hops[0].via == "location"
    assert any("tracker.example" in h.url for h in hops)

    block = tmp_path / "blocklist.txt"
    block.write_text("tracker.example\n", encoding="utf-8")

    # Reuse recorded hop pattern via a stubbed tracer for the full check path.
    recorded = [
        Hop(index=0, url=start, status=302, via="location"),
        Hop(index=1, url=f"http://127.0.0.1:{port}/mid", status=302, via="location"),
        Hop(index=2, url="http://tracker.example/click?cid=abc", status=None, via="error", error="dns"),
    ]

    def stub_trace(url, **_kwargs):
        return list(recorded)

    original = check_mod.trace_url
    check_mod.trace_url = stub_trace
    try:
        result = run_check(
            f"See {start}",
            blocklist_path=block,
            check_age=False,
        )
    finally:
        check_mod.trace_url = original

    assert result.verdict == "BLOCK", [r.to_dict() for r in result.reasons]
    assert result.exit_code == 2
    assert any(r.code == "blocklisted_hop" for r in result.reasons)

#!/usr/bin/env python3
"""Refresh data/corpus.jsonl from recent posts (X API v2).

Requires X_BEARER_TOKEN. Pass one or more user ids:

  python scripts/fetch_corpus.py --user-id 123 --user-id 456 --out data/corpus.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


def fetch_user_tweets(user_id: str, token: str, max_results: int = 20) -> list[dict]:
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    resp = requests.get(
        url,
        params={"max_results": max_results, "tweet.fields": "created_at,text,entities"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    rows = []
    for item in resp.json().get("data") or []:
        urls = []
        for u in (item.get("entities") or {}).get("urls") or []:
            if u.get("expanded_url"):
                urls.append(u["expanded_url"])
        rows.append(
            {
                "id": item.get("id"),
                "account": user_id,
                "text": item.get("text") or "",
                "created_at": item.get("created_at")
                or datetime.now(timezone.utc).isoformat(),
                "urls": urls,
            }
        )
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user-id", action="append", required=True)
    p.add_argument("--out", type=Path, default=Path("data/corpus.jsonl"))
    p.add_argument("--max-results", type=int, default=20)
    args = p.parse_args()
    token = os.environ.get("X_BEARER_TOKEN") or os.environ.get("TWITTER_BEARER_TOKEN")
    if not token:
        print("Set X_BEARER_TOKEN", file=sys.stderr)
        return 1
    rows: list[dict] = []
    for uid in args.user_id:
        rows.extend(fetch_user_tweets(uid, token, args.max_results))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} posts to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

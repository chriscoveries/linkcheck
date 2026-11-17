"""linkcheck CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .check import format_human, run_check
from .paths import default_path


def _read_text_arg(args: argparse.Namespace) -> str:
    chunks: list[str] = []
    if args.text is not None:
        chunks.append(args.text)
    if args.file:
        chunks.append(Path(args.file).read_text(encoding="utf-8"))
    if args.stdin or (not chunks and not args.urls and not sys.stdin.isatty()):
        chunks.append(sys.stdin.read())
    # URLs as positional args are also treated as draft material if no text given
    if args.urls and not chunks:
        chunks.append(" ".join(args.urls))
    return "\n".join(chunks).strip()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="linkcheck",
        description=(
            "Inspect a social post draft for leakable redirect hops, tracker domains, "
            "and shared tracking codes/wording before publishing."
        ),
    )
    p.add_argument("--version", action="version", version=f"linkcheck {__version__}")
    p.add_argument("--text", "-t", help="Draft text to inspect")
    p.add_argument("--file", "-f", help="Read draft text from a file")
    p.add_argument(
        "--stdin",
        action="store_true",
        help="Read draft text from stdin (also default when stdin is piped)",
    )
    p.add_argument("urls", nargs="*", help="URLs to inspect (optional; also extracted from text)")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON (see docs/schema.md)")
    p.add_argument("--blocklist", type=Path, help="Domain blocklist file (one domain per line)")
    p.add_argument("--allowlist", type=Path, help="Domain allowlist file")
    p.add_argument("--shorteners", type=Path, help="Known shortener domains file")
    p.add_argument("--phrases", type=Path, help="Shared scripted phrases file")
    p.add_argument("--corpus", type=Path, help="JSONL corpus of recent posts from other accounts")
    p.add_argument("--no-age", action="store_true", help="Skip RDAP/WHOIS domain-age checks")

    sub = p.add_subparsers(dest="command")

    rt = sub.add_parser("runtime", help="Print the agent playbook index")
    rt.add_argument("--json", action="store_true", help="Emit the runtime index as JSON")
    rt.add_argument("--playbook", help="Print one playbook by id")

    mon = sub.add_parser("monitor", help="Check this account's already-posted links")
    mon.add_argument("--user-id", required=True, help="Numeric account id")
    mon.add_argument("--max-results", type=int, default=10)
    mon.add_argument("--json", action="store_true", help="Emit JSON")
    return p


def _cmd_monitor(args: argparse.Namespace) -> int:
    from .monitor import monitor_user

    findings = monitor_user(args.user_id, max_results=args.max_results)
    if args.json:
        print(json.dumps(findings, indent=2))
    else:
        if not findings.get("posts"):
            print(findings.get("message") or "No posts checked.")
        for post in findings.get("posts", []):
            print(f"@{post.get('id')}: {post.get('verdict')} — {post.get('text_excerpt', '')}")
            for r in post.get("reasons", []):
                print(f"  [{r['severity']}] {r['code']}: {r['message']}")
    return findings.get("exit_code", 0)


def _cmd_runtime(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from .runtime import format_runtime_error, playbook_text, runtime_payload

    try:
        if args.playbook:
            text = playbook_text(args.playbook)
            sys.stdout.write(text if text.endswith("\n") else text + "\n")
            return 0
        payload = runtime_payload()
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        print(format_runtime_error(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"linkcheck runtime {payload['version']}")
        print(payload["rule"])
        print("Boot:", ", ".join(payload["boot"]))
        for item in payload["playbooks"]:
            print(f"- {item['id']}: {item['command']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "runtime":
        return _cmd_runtime(args)

    if args.command == "monitor":
        return _cmd_monitor(args)

    text = _read_text_arg(args)
    extra = list(args.urls or [])
    if not text and not extra:
        parser.error("Provide --text, --file, stdin, or URL arguments")

    result = run_check(
        text or " ".join(extra),
        extra_urls=extra,
        blocklist_path=args.blocklist,
        allowlist_path=args.allowlist,
        shorteners_path=args.shorteners or default_path("shorteners.txt"),
        phrases_path=args.phrases,
        corpus_path=args.corpus,
        check_age=not args.no_age,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        sys.stdout.write(format_human(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

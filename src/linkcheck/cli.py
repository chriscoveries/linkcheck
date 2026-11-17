"""linkcheck CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .check import format_human, run_check
from .paths import default_path

_SUBCOMMANDS = frozenset({"runtime", "monitor", "x-plan", "x-ingest"})


def _read_text_arg(args: argparse.Namespace) -> str:
    chunks: list[str] = []
    if getattr(args, "text", None) is not None:
        chunks.append(args.text)
    if getattr(args, "file", None):
        chunks.append(Path(args.file).read_text(encoding="utf-8"))
    if getattr(args, "stdin", False) or (
        not chunks and not getattr(args, "urls", None) and not sys.stdin.isatty()
    ):
        chunks.append(sys.stdin.read())
    if getattr(args, "urls", None) and not chunks:
        chunks.append(" ".join(args.urls))
    return "\n".join(chunks).strip()


def _add_check_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--text", "-t", help="Draft text to inspect")
    p.add_argument("--file", "-f", help="Read draft text from a file")
    p.add_argument(
        "--stdin",
        action="store_true",
        help="Read draft text from stdin (also default when stdin is piped)",
    )
    p.add_argument(
        "urls",
        nargs="*",
        help="URLs to inspect (optional; also extracted from text)",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    p.add_argument("--blocklist", type=Path, help="Domain blocklist file")
    p.add_argument("--allowlist", type=Path, help="Domain allowlist file")
    p.add_argument("--shorteners", type=Path, help="Known shortener domains file")
    p.add_argument("--phrases", type=Path, help="Shared scripted phrases file")
    p.add_argument("--corpus", type=Path, help="JSONL corpus of recent posts")
    p.add_argument("--no-age", action="store_true", help="Skip RDAP/WHOIS domain-age checks")


def build_check_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="linkcheck",
        description=(
            "Inspect a social post draft for leakable redirect hops, tracker domains, "
            "and shared tracking codes/wording before publishing."
        ),
    )
    p.add_argument("--version", action="version", version=f"linkcheck {__version__}")
    _add_check_flags(p)
    return p


def build_parser() -> argparse.ArgumentParser:
    """Parser for subcommands only (runtime, monitor, x-plan, x-ingest)."""
    p = argparse.ArgumentParser(
        prog="linkcheck",
        description=(
            "Inspect a social post draft for leakable redirect hops, tracker domains, "
            "and shared tracking codes/wording before publishing."
        ),
    )
    p.add_argument("--version", action="version", version=f"linkcheck {__version__}")

    sub = p.add_subparsers(dest="command", required=True)

    rt = sub.add_parser("runtime", help="Print the agent playbook index")
    rt.add_argument("--json", action="store_true", help="Emit the runtime index as JSON")
    rt.add_argument("--playbook", help="Print one playbook by id")

    mon = sub.add_parser("monitor", help="Check this account's already-posted links")
    mon.add_argument("--user-id", required=True, help="Numeric account id")
    mon.add_argument("--max-results", type=int, default=10)
    mon.add_argument("--json", action="store_true", help="Emit JSON")

    xp = sub.add_parser(
        "x-plan",
        help="Print ordered X MCP tool calls for a playbook (agent copies verbatim)",
    )
    xp.add_argument(
        "playbook",
        nargs="?",
        choices=["own-posts", "shared-code", "shared-script", "cluster"],
        help="X MCP playbook id",
    )
    xp.add_argument(
        "--resolve",
        metavar="PLAN.json",
        help="Resolve {$from} placeholders in a saved plan using --outputs",
    )
    xp.add_argument(
        "--outputs",
        nargs="+",
        metavar="FILE",
        help=(
            "Prior step output files for --resolve. Accepts raw fenced tool output "
            "(step1.txt …) and/or a {step1:…} map; fences/footers stripped like x-ingest"
        ),
    )
    xp.add_argument("--username", help="Account username (own-posts)")
    xp.add_argument("--user-id", help="Numeric account id (own-posts)")
    xp.add_argument(
        "--max-results",
        type=int,
        help="max_results per call (default 10 for own-posts, 25 otherwise; cap 25)",
    )
    xp.add_argument("--text", "-t", help="Draft text (shared-code / shared-script)")
    xp.add_argument("--file", "-f", help="Read draft text from a file")
    xp.add_argument(
        "--codes",
        help="Comma-separated tracking codes (shared-code); merged with codes from draft",
    )
    xp.add_argument("--query", "-q", help="Search query (cluster)")
    xp.add_argument("--start-time", help="ISO start time (cluster)")
    xp.add_argument("--end-time", help="ISO end time (cluster)")
    xp.add_argument("--since-id", help="since_id bound (cluster)")
    xp.add_argument("--until-id", help="until_id bound (cluster)")
    xp.add_argument("--json", action="store_true", help="Emit JSON (required for agents)")

    xi = sub.add_parser(
        "x-ingest",
        help="Parse raw X MCP tool JSON and return the usual check verdict",
    )
    xi.add_argument("--file", "-f", required=True, help="Raw MCP tool output JSON file")
    xi.add_argument("--draft", help="Optional draft text file to compare against ingested posts")
    xi.add_argument("--json", action="store_true", help="Emit JSON")
    xi.add_argument(
        "--verbose",
        action="store_true",
        help="Full detail (urls, script_match, posts); default is compact",
    )
    xi.add_argument("--no-age", action="store_true", help="Skip domain-age checks when --online")
    xi.add_argument(
        "--online",
        action="store_true",
        help="Follow URL hops on the network (default is offline / no hop fetch)",
    )
    xi.add_argument("--blocklist", type=Path, help="Domain blocklist file")
    xi.add_argument("--allowlist", type=Path, help="Domain allowlist file")
    xi.add_argument("--shorteners", type=Path, help="Known shortener domains file")
    xi.add_argument("--phrases", type=Path, help="Shared scripted phrases file")
    return p


def _first_subcommand(argv: list[str]) -> str | None:
    for a in argv:
        if a in _SUBCOMMANDS:
            return a
        if a == "--":
            break
    return None


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


def _read_optional_draft(args: argparse.Namespace) -> str:
    chunks: list[str] = []
    if getattr(args, "text", None):
        chunks.append(args.text)
    if getattr(args, "file", None):
        chunks.append(Path(args.file).read_text(encoding="utf-8"))
    return "\n".join(chunks).strip()


def _cmd_x_plan(args: argparse.Namespace) -> int:
    from .x_plan import build_plan, resolve_plan_files

    if args.resolve:
        if not args.outputs:
            print("x-plan --resolve requires --outputs", file=sys.stderr)
            return 1
        try:
            plan = resolve_plan_files(
                Path(args.resolve),
                [Path(p) for p in args.outputs],
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    else:
        if not args.playbook:
            print("x-plan requires a playbook or --resolve", file=sys.stderr)
            return 1
        text = _read_optional_draft(args)
        codes = None
        if getattr(args, "codes", None):
            codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        try:
            plan = build_plan(
                args.playbook,
                username=args.username,
                user_id=args.user_id,
                text=text,
                codes=codes,
                query=args.query,
                start_time=args.start_time,
                end_time=args.end_time,
                since_id=args.since_id,
                until_id=args.until_id,
                max_results=args.max_results,
            )
        except (ValueError, KeyError) as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if args.json:
        # Compact: no indent — agents minimise tokens
        print(json.dumps(plan, separators=(",", ":"), sort_keys=False))
    else:
        print(f"playbook: {plan['playbook']} call_count={plan.get('call_count', len(plan['calls']))}")
        for i, call in enumerate(plan["calls"], start=1):
            print(f"step{i}. {call['namespace']}.{call['tool']}")
            print(f"   {json.dumps(call['arguments'], separators=(',', ':'))}")
    return 0


def _cmd_x_ingest(args: argparse.Namespace) -> int:
    from .models import CheckResult, Finding
    from .x_ingest import extract_posts, ingest_to_dict, run_ingest

    try:
        raw = Path(args.file).read_text(encoding="utf-8")
        draft = None
        if args.draft:
            draft = Path(args.draft).read_text(encoding="utf-8")
        result = run_ingest(
            raw,
            draft_text=draft,
            blocklist_path=args.blocklist,
            allowlist_path=args.allowlist,
            shorteners_path=args.shorteners,
            phrases_path=args.phrases,
            check_age=bool(args.online) and not args.no_age,
            offline=not args.online,
        )
        posts, _truncated = extract_posts(raw)
    except Exception as exc:  # noqa: BLE001 — never traceback to the bot
        result = CheckResult(
            verdict="WARN",
            exit_code=1,
            reasons=[
                Finding(
                    severity="WARN",
                    code="input_truncated",
                    message=f"Failed to ingest MCP output: {exc}",
                    detail={},
                )
            ],
        )
        posts = []
    if args.json:
        body = ingest_to_dict(result, posts=posts, verbose=args.verbose)
        print(
            json.dumps(
                body,
                separators=(",", ":") if not args.verbose else None,
                indent=2 if args.verbose else None,
            )
        )
    else:
        sys.stdout.write(format_human(result))
        print(f"Ingested posts: {len(posts)}")
    return result.exit_code


def _cmd_check(args: argparse.Namespace) -> int:
    text = _read_text_arg(args)
    extra = list(args.urls or [])
    if not text and not extra:
        print("Provide --text, --file, stdin, or URL arguments", file=sys.stderr)
        return 2

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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = _first_subcommand(argv)
    if cmd is None:
        # Default check path: positional URLs must not hit subparser choices
        parser = build_check_parser()
        args = parser.parse_args(argv)
        return _cmd_check(args)

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "runtime":
        return _cmd_runtime(args)
    if args.command == "monitor":
        return _cmd_monitor(args)
    if args.command == "x-plan":
        return _cmd_x_plan(args)
    if args.command == "x-ingest":
        return _cmd_x_ingest(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

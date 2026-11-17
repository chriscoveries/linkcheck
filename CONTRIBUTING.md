# Contributing

## Setup

```bash
pip install -e ".[dev]"
pytest -q
```

Python 3.10+. Optional: `pip install -e ".[whois]"` for WHOIS age fallback.

## Layout

- `src/linkcheck/` — library + CLI
- `tests/` — pytest (stubs network where needed)
- `docs/` — see [docs/README.md](docs/README.md); do not duplicate topics
- `data/` — default lists (keep fixtures anonymised)

## Docs rules

- One source per topic (guide vs examples vs PROBLEM vs how-it-works, …)
- Placeholder hosts only (`track.example`, `news.example`, `Creator A`)
- Example commands in docs should run (use `--no-age` for offline examples)

## Pull requests

- Keep tests green: `pytest -q`
- Prefer small, reviewable commits
- Do not commit bearer tokens or investigation screenshots with real handles

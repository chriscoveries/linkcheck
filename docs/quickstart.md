# Quickstart

This is a short on-ramp. The full guide is [guide.md](guide.md); worked output is
[examples.md](examples.md).

## Install

```bash
pip install -e ".[dev]"
linkcheck --version
```

Expected: `linkcheck 0.1.0`. Private-repo install options: [guide.md](guide.md#install).

## First checks

Ordinary UTMs (expect OK / exit 0):

```bash
linkcheck --no-age --text "A short note https://news.example/story?utm_medium=social&utm_campaign=spring"
```

Opaque campaign code (expect WARN / exit 1):

```bash
linkcheck --no-age --text "A short note https://news.example/story?utm_campaign=a1b2c3d4&utm_medium=social"
```

Blocklisted hop (expect BLOCK / exit 2) — see [examples.md](examples.md#block-a-host-you-forbade).

## Read the verdict

| Exit | Verdict | Action |
| --- | --- | --- |
| 0 | OK | Clear (INFO-only is still OK) |
| 1 | WARN | Show reasons; do not post until you decide |
| 2 | BLOCK | Do not post |

## Next

- Case study: [PROBLEM.md](PROBLEM.md)
- Agent wiring: [agents.md](agents.md)
- JSON fields: [schema.md](schema.md)

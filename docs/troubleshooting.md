# Troubleshooting

## `linkcheck: command not found`

```bash
pip install -e ".[dev]"
python -m linkcheck --version
```

## `Provide --text, --file, stdin, or URL arguments`

Pass draft material via `-t`, `-f`, a pipe, or positional URLs.

## `unrecognized arguments: --json` with monitor

```bash
linkcheck --json monitor --user-id 123
```

Global flags before the subcommand.

## Monitor asks for `X_BEARER_TOKEN`

Export a valid bearer token, then retry.

## DNS errors on every hop

Placeholder `*.example` hosts never resolve (expected in docs). Real hosts need
outbound HTTPS. Param checks still run.

## Always `domain_age_unknown`

RDAP blocked or empty. Try `pip install -e ".[whois]"` or `--no-age`.

## No wording / shared-code warnings

Empty corpus, posts older than 14 days, or fewer than 3 matching accounts.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Agent posts despite WARN

Re-assert [agents.md](agents.md): WARN and BLOCK mean do not post.

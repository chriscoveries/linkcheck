# install

Do this once per checkout. Do not ask the user to run it.

```bash
pip install -e .
linkcheck runtime --json
```

`linkcheck runtime --json` is the map. It lists playbooks, the command for each, and what exit codes mean. If that command fails, stop and report the error. Do not guess a different entrypoint.

Python 3.10 or newer is required. The install pulls `requests` and `pydantic`.

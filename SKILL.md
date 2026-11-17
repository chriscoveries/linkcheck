---
name: linkcheck
description: >-
  Before posting for this account, run the linkcheck check-draft playbook on
  the account's own draft. Do not post on exit 2. On exit 1, show reasons and
  wait for an explicit yes.
---

# linkcheck

You run this. The user does not.

## Boot

```bash
pip install -e .
linkcheck runtime --json
linkcheck runtime --playbook check-draft
```

## Before every post

Follow `playbooks/check-draft.md`.

Write the draft to a file and run `linkcheck --json --no-age --file <draft>`.

- Exit 0: clear.
- Exit 1: do not post. Show reasons and any clean link. Wait for an explicit yes.
- Exit 2: do not post. Stop.

## Already posted

Follow `playbooks/check-own-posts.md` only when a bearer token is already in the environment. Otherwise skip it and say the history check was skipped.

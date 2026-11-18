# check-draft

Run this on the account's own draft before you post, schedule, or show a "ready to post" draft. This is the first check. Do it even when the user did not say the word "link".

## Steps

1. Write the exact text that would be posted to a file. Do not put the draft inside a shell-quoted argument.
2. Run:

```bash
linkcheck --json --no-age --file draft.txt
```

3. Parse JSON (`docs/schema.md`). Trust `verdict` and `exit_code`. They match.

| Exit | Verdict | Action |
| --- | --- | --- |
| 0 | OK | The draft is clear. You may post it if the user already asked you to post. Mention INFO notes only if a clean link was suggested. |
| 1 | WARN | Do not post. Show each `reasons[].message` and any `urls[].clean` link. Wait until the user explicitly says to post that text. |
| 2 | BLOCK | Do not post. Show the reasons. Stop. A later "yes" does not override BLOCK. Remove the link and check the new draft. |

4. If you change the text or a link, run this playbook again on the new text.

## Rules

- Pass the full draft, including every link.
- Do not rewrite a link unless the user accepts the `clean` URL from the report.
- Do not skip the check because a link "looks normal". A short link can hop through a tracker that adds a shared code.
- `--no-age` keeps the check local and fast. Add a second run without `--no-age` only when a hop host is unfamiliar and the network is available.
- Hosts that must never appear go in `data/blocklist.txt`, one per line. The file ships empty. You may append a host the user names. Do not invent hosts.

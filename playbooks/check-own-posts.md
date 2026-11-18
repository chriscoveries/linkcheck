# check-own-posts

Use this when the account should review links it has already posted. Drafts that are not posted yet use `check-draft` instead.

For membership in the campaign dataset use `find-own-posts`. `monitor` fetches one page (10 posts by default, at most 100); its output includes only warnings/blocks. An empty result establishes neither a complete timeline search nor absence from the campaign dataset.

## Steps

1. If `X_BEARER_TOKEN` is unset and `TWITTER_BEARER_TOKEN` is unset, do not call the network. Tell the user the history check was skipped because no token is set. Still run `check-draft` on anything not yet posted.
2. You need the numeric account id. If you do not have it, ask once. Do not guess.
3. Run:

```bash
linkcheck monitor --user-id <id> --json
```

4. The JSON `posts` array contains only posts that are WARN or BLOCK. `exit_code` 0 means none of the fetched posts failed the check.

| Exit | Action |
| --- | --- |
| 0 | Tell the user the fetched posts were clear. |
| 1 | Show each post id, verdict, and reasons. Do not delete or edit a live post unless the user asks. |
| 2 | A fetched post is BLOCK. Show the reasons. Do not republish that text. |

A missing token or an API error also returns exit 1 with a `message` and an empty `posts` list. Report that message. Do not treat it as a clean account.

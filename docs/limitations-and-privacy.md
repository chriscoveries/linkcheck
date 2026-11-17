# Limitations and privacy

Guide “Limits” section is a short list; this page is the full note.

## Can catch

Unexpected intermediate hops; blocklisted hosts; identifying params / opaque
tokens; young domains (when RDAP/WHOIS answers); shared codes, near-duplicate
wording, and posting-time clusters **with a corpus**; phrase-list hits.

## Cannot catch

Browser-only JS redirects beyond simple `location` / meta-refresh; unlisted
private shorteners; coordination with no shared links or wording; truth or legal
disclosure; accounts outside your corpus; proof that a clean URL is the page you
meant.

## Network destinations

| Action | Destination | Data sent |
| --- | --- | --- |
| Trace hops | Each URL in the chain | HTTP request to that host |
| Domain age | `https://rdap.org/domain/{domain}` (+ optional WHOIS) | Domain name |
| Monitor / corpus fetch | `https://api.x.com/2/...` | Bearer token + user id |

No phone-home to the authors of this repo. Drafts stay local except for the
hosts implied by your links, RDAP, and optional X API use.

Keep `X_BEARER_TOKEN` in the environment. Treat real corpus text as sensitive.

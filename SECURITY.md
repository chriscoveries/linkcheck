# Security

## Reporting

If you find a vulnerability in `linkcheck` (for example command injection via
crafted drafts, or unsafe handling of tokens), please open a private security
advisory on the GitHub repository or email the repository owner listed on the
GitHub profile. Do not file a public issue with exploit details.

## Scope notes

- `linkcheck` fetches URLs you ask it to check. Treat draft links as untrusted
  input for SSRF-style concerns in locked-down environments.
- Never commit `X_BEARER_TOKEN` or other credentials.
- This project does not provide a bounty program at this time.

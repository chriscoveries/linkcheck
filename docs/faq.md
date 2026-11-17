# FAQ

## Does linkcheck decide if something is an ad?

No. It only flags join keys (hops, codes, wording, timing, young domains).

## Why do `*.example` hosts show DNS errors?

They do not resolve. Param and blocklist checks still run on the URL string.
See [examples.md](examples.md).

## Is WARN always bad?

It means someone *could* group the draft with others using public signals. You
decide whether to strip them.

## Do I need a corpus?

No for hop/param/blocklist/age. Yes for near-duplicate, shared-code, and
posting-time clustering.

## How do I hard-fail a tracker?

Add it to `data/blocklist.txt` → `blocklisted_hop` (exit 2).

## Where is the case study?

[PROBLEM.md](PROBLEM.md) (`problem.md` redirects there).

## Are investigation screenshots in the repo?

No. Diagrams under `docs/img/` and `docs/figures/` are placeholders only.

# ADR 0004: SQL fingerprints and the N+1 rule

Date: 2026-11-19.

## Decision

Fingerprints come from a small hand-written tokenizer (`analyzers/fingerprint.py`), not
`sqlglot`. It knows PostgreSQL's lexical rules: `'...'` with `''`, `E'...'` with backslashes,
`B''`/`X''`/`U&''`/`N''`, dollar quoting, `"quoted identifiers"`, nested `/* */` comments, and
the placeholders `%s`, `%(name)s`, `%b` and `$1`. Every literal and placeholder becomes `?`,
lists of values become `(...)` (`IN`, `VALUES` rows, `ARRAY[...]`), unquoted words are lower
cased, comments are dropped.

**N+1**: the same fingerprint run at least `nplus1_threshold` times (default 3) in one request
with at least two different sets of values. `executemany` never counts: it is already the
batched form. Identical values make it an **exact duplicate** instead.

## Why

- `sqlglot` 30.33 (checked 2026-11-19) is a 810 KB wheel with 24 releases in six months and a
  recent major-version bump. Grouping only needs tokens, not a syntax tree, so the dependency
  would add churn for no accuracy gain. The tokenizer is about 150 lines and has 50
  table-driven cases.
- Duplicates are compared on the raw values kept for replay: two different passwords both
  display as `<redacted>` and must not look like duplicates (tested).
- Requiring two distinct value sets keeps "the same lookup three times" (a duplicate, fixed by
  caching) apart from "one lookup per row" (an N+1, fixed by a join or `= ANY(%s)`).

## Consequences

- Not a parser: `f(?, ?)` and `f(?)` share a fingerprint, as do `VALUES` with different row
  counts. That is intended for grouping.
- A statement containing an unterminated literal or comment is still fingerprinted; the rest
  of the text becomes part of that literal.

# Good first issues (drafts)

Drafts for the maintainer to open on GitHub. Each is self-contained: the problem, where to
look, what done means, and how to test it. Tests always run against real PostgreSQL
(`docker compose up -d --wait`, then `TEST_PG_DSN=postgresql://test:test@127.0.0.1:54318/test`).

## 1. Record asyncpg prepared statements

`conn.prepare(sql)` returns a `PreparedStatement` whose `fetch`/`fetchrow`/`fetchval`/
`executemany` are not recorded (`test_not_recorded_prepared_statements_and_no_trace` in
`tests/test_asyncpg.py` pins this). Wrap `prepare()` in `collectors/asyncpg.py` so the returned
statement's methods record like `TracingMixin.fetch` does, with the call site of the method
call, not of `prepare()`. Done when that test is turned around and a new test covers
`executemany` on a prepared statement.

## 2. Record asyncpg cursors

`conn.cursor(sql)` (iteration inside a transaction) is not recorded. Record the `DECLARE` as
kind `"declare"`, like psycopg server-side cursors. Done when a test iterates a cursor inside
`conn.transaction()` and finds one `"declare"` statement with its call site.

## 3. Copy button for the full trace

The panel copies one statement. Add a "Copy all SQL" button to the request header in
`panel-src/src/components/RequestDetail.tsx` that copies every statement in order, using
`copyableSql` from `lib/format.ts`. Done when a unit test in `lib/lib.test.ts` covers the text
it builds, `npm run build` is committed, and `pytest -m e2e` still passes.

## 4. Filter the request list

Add a text box above the request list (`RequestList.tsx`) that filters by path. Keyboard
navigation must keep working on the filtered list. Done when an e2e test types a path and only
matching requests remain.

## 5. Show plans in the Server-Timing header

When `?lens=plan` captured plans, add the planning and execution totals as extra
`Server-Timing` entries (`plan;dur=...`). Plans are captured after the response, so this needs
a design note first: either capture before sending (and measure the cost) or document why it
cannot be done. Start with a short comment on the issue.

## 6. Redact by column name for positional parameters

Positional parameters (`%s`, `$1`) have no names, so `password` columns are not redacted in
`INSERT INTO users (email, password) VALUES (%s, %s)`. Map placeholders to column names for
simple `INSERT ... (cols) VALUES (...)` and `UPDATE ... SET col = %s` statements in
`core/redact.py`, and redact by the same name rule. Done when table-driven tests cover both
statement forms and a statement the rule cannot parse (which must stay unchanged).

## 7. A Starlette example

`examples/fastapi` covers FastAPI. Add `examples/starlette` with the same three endpoints and
the same tests (parametrize `tests/test_example_fastapi.py` over both apps). Done when the
tests pass for both apps on all three drivers.

## 8. `assert_no_duplicates` in the pytest plugin

The analyzers already find exact duplicates. Add `QueryRecorder.assert_no_duplicates()` in
`testing.py`, listing the duplicated statements the same way the other assertions do. Done
when `tests/test_pytest_plugin.py` covers a pass and a failure, including two different
redacted passwords that must not count as duplicates.

## 9. Make the slow-statement threshold visible in the panel

`AnalyzerOptions.slow_ms` decides what counts as slow, but the panel does not say what the
threshold is. Serve it in the request detail JSON (`serialize.py`) and show it next to the
"Slow statements" warning. Done when the API test and a panel unit test cover it.

## 10. Clear the request history from the panel

Add `DELETE /__lens/api/requests` (needs the `X-Lens` header, like the explain endpoint) and a
"Clear" button in the panel header. Done when API tests cover the header requirement, the
non-local 404 and the clearing, and an e2e test clicks the button.

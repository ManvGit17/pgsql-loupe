# Configuration

## Environment variables

| Variable | Effect |
|---|---|
| `PGSQL_LOUPE_ENABLED=1` | turns the middleware on (otherwise `install()` does nothing) |
| `PGSQL_LOUPE_ENV`, `APP_ENV`, `ENVIRONMENT`, `ENV` | `prod`, `production` or `live` makes enabling fail (`ProductionGuardError`) |
| `PGSQL_LOUPE_ALLOW_PRODUCTION=1` | overrides that refusal |
| `PGSQL_LOUPE_TEST_DSN` | database for `assert_no_seq_scan` in tests |

## `LoupeConfig` (`pgsql_loupe.asgi`)

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `None` | `None` reads `PGSQL_LOUPE_ENABLED` |
| `history` | `100` | traced requests kept in memory |
| `prefix` | `"/__lens"` | where the panel and API live |
| `authorize` | `localhost_only` | `(scope) -> bool`: who may trace and see the API |
| `environment_vars` | the four above | variables checked for "production" |
| `allow_production` | `None` | `None` reads `PGSQL_LOUPE_ALLOW_PRODUCTION` |
| `explain` | `None` | an `ExplainOptions`; `None` disables plan capture |
| `analyzers` | `AnalyzerOptions()` | N+1 and slow-statement thresholds |
| `inject_toggle` | `False` | add a link to the panel on traced HTML pages |

## `ExplainOptions` (`pgsql_loupe.explain`)

| Field | Default | Meaning |
|---|---|---|
| `dsn` | required | connection used for replays |
| `analyze_reads` | `True` | `EXPLAIN ANALYZE` reads (read-only transaction) |
| `analyze_writes` | `False` | `EXPLAIN ANALYZE` writes (rolled back) |
| `timeout_ms` | `5000` | statement timeout per replay |
| `lock_timeout_ms` | `1000` | lock timeout per replay |
| `max_plans` | `25` | replays per request in `?lens=plan` mode |
| `thresholds` | `FlagThresholds()` | `seq_scan_rows=10000`, `estimate_factor=10.0`, `estimate_min_rows=100.0` |

## `AnalyzerOptions` (`pgsql_loupe.analyzers`)

| Field | Default | Meaning |
|---|---|---|
| `nplus1_threshold` | `3` | runs of one shape (with different values) that make an N+1 |
| `slow_ms` | `100.0` | statements at least this slow are listed as slow |

## pytest

| Option | Meaning |
|---|---|
| `--pgsql-loupe-dsn` | database for `assert_no_seq_scan` |
| ini `pgsql_loupe_dsn` | the same, in `pytest.ini` / `pyproject.toml` |

---
hide:
  - navigation
  - toc
---

<div class="loupe-hero" markdown>

# pgsql-loupe

See what every request did to your PostgreSQL database: each statement, its parameters and
timing, the line of code that ran it, `EXPLAIN ANALYZE` plans, fired triggers and N+1 warnings.

[Get started](quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ManvGit17/pgsql-loupe){ .md-button }

</div>

<div class="loupe-shot" markdown>

![The panel showing an N+1 warning and a query plan](images/panel.png#only-light)
![The panel showing an N+1 warning and a query plan](images/panel-dark.png#only-dark)

</div>

<div class="grid cards" markdown>

-   :material-database-search: **Every statement**

    psycopg 3, SQLAlchemy 2 (sync and async) and asyncpg, recorded without changing your
    queries, each with the line of your code that ran it.

-   :material-sitemap: **Plans and triggers**

    `EXPLAIN ANALYZE` for reads, non-executed plans for writes, fired triggers, and warnings
    for big scans, bad estimates and spills. [How it stays safe](plans.md)

-   :material-repeat: **N+1 and duplicates**

    The same query shape run once per row is flagged with the code that ran it, along with
    exact duplicates and slow statements.

-   :material-monitor-dashboard: **A panel in the package**

    Open `/__lens/` in your app. It works offline, needs no Node, and ships inside the
    Python package.

-   :material-test-tube: **Query budgets in tests**

    A pytest fixture: `assert_max_queries`, `assert_no_nplus1`, `assert_no_seq_scan`.
    [In tests](testing.md)

-   :material-shield-check: **Safe by default**

    Off unless enabled, refuses production, local requests only, secrets redacted.
    [Safety model](safety.md)

</div>

## Two lines to add

```python
pool = ConnectionPool(dsn, configure=instrument)  # 1. record statements
install(app, LoupeConfig(explain=ExplainOptions(dsn=dsn)))  # 2. add the panel
```

Then run with `PGSQL_LOUPE_ENABLED=1`, open any page with `?lens=plan`, and go to `/__lens/`.
The [quick start](quickstart.md) covers all three drivers.

```bash
pip install "pgsql-loupe[psycopg]"
```

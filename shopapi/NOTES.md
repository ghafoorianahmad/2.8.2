# shopapi — Progress Log

## Work order (plan)
1. ✅ Plan + environment verification (this file)
2. ✅ Config + own DB + schemas
3. ✅ accounting_reader + tests
4. ✅ users/orders flow + tests
5. ✅ accounting_writer (dry-run default) + tests
6. ✅ admin endpoints
7. ✅ SQL permission scripts
8. ⏳ README + final check (pytest green, uvicorn starts, /products works)

## Environment (verified, read-only)
- SQL Server Express running as `.\SQLEXPRESS`; database `hesab5` present
  (a `hesab5 t` database also exists and is ignored).
- ODBC Driver 17 for SQL Server installed (32/64-bit); `sqlcmd` available.
- Python 3.12.10; project venv at `.venv` with the allowed packages only.

## Schema facts re-verified on the copy (read-only queries)
- Tables present: Kala, Gkala, kardex_an, KalaOrder, KalaOrderDetail, facto,
  TabaghehBandi, setting, name_mo.
- Kala sale-price columns: `Gey`(1), `Geycf`(2), `gey3`(3), `gey4`(4), `gey5`(5).
  `Geya`/`Geyk`/`Geym` are NOT sale prices (never selected).
- Kala: `active` bit NOT NULL, all 630 rows active=1 in the copy; `IsKalaSite`
  all 0; `pic` nullable; `Code` NOT NULL, not identity.
- kardex_an stock = `SUM(Megv)-SUM(Megs)` matches `Kala.Mogod` exactly
  (verified on a sample). `Codanbar` present for warehouse filtering.
- KalaOrder: `Codlp` NOT NULL, no identity / PK / unique / triggers (verified 0).
  `MAX(Codlp)` in copy = 1. Only `Codlp` is NOT NULL; other columns nullable.
- KalaOrderDetail: `sharh` + `field1..8` present (nullable in schema, but we
  bind empty strings per spec to avoid blank concatenated names).
- facto: `ordercode` column present for the open-order reservation formula.
- name_mo: `Code` (NOT NULL, not identity), `Name`, `fname`, `mobile` present.
- setting: row 399 name='0' (→ default all warehouses); rows 425-427 empty name.
- `dbo.MiladiToShamsi(@MiladiDate datetime)` returns nvarchar(20); verified it
  returns a 10-char Shamsi date. Must be fully qualified (`hesab5.dbo...`).

## DIFFERENCES from the provided "VERIFIED FACTS" (important)
1. **TabaghehBandi code 6808 does not exist** in this copy. TabaghehBandi here
   contains free-text notes with personal/financial data (names, phone numbers,
   cheque amounts), not a clean order-status table. The single existing
   KalaOrder row uses `Status=6808`, so the default `ACCOUNTING_STATUS_CODE=6808`
   is kept, but the premise "6808 is the TabaghehBandi code of تایید" could NOT
   be confirmed. The writer writes the configured integer and does NOT read
   TabaghehBandi to validate it (avoids selecting personal data). Flag for the
   production DBA.
2. name_mo.mobile may hold non-normalized digits; `normalize_fa` + a SQL REPLACE
   chain are used for exact matching.
3. "NOT NULL" columns: only `KalaOrder.Codlp` is NOT NULL. The spec's empty-
   string rule is still enforced for `sharh`/`field1..8`/`tavasot`.

## Safety notes
- During verification an exploratory `LIKE '%تا%'` query against TabaghehBandi
  surfaced free-text personal/financial data; that table is no longer read for
  data. No personal data is stored in the repo, logs, or tests.
- All accounting SQL is parameterized; only config-provided identifiers are
  interpolated (validated by `safe_identifier`). Only the string `API-<id>` is
  ever written to the accounting DB.

## Assumptions / open questions
- `GET /orders/{id}`: non-admin callers must prove ownership via `platform` +
  `chat_id` query params (there is no per-customer credential). Admin can read
  any order. See README.
- Platform↔channel mapping is not enforced: the API key's role (bot/site) picks
  the price level; `platform` is trusted from the request body. Open question:
  should bot keys be limited to bale/telegram and site keys to web?
- `/products` computes the bounded candidate set (active=1, price>0) and applies
  `q`/availability/pagination in Python so reservation math stays correct and
  Persian/Arabic normalization works; no OFFSET/FETCH is used (2008 R2 safe).
- Expiry only expires `awaiting_payment` orders (per spec); `receipt_uploaded`
  waits for admin decision.
- Price rounding uses round-half-away-from-zero to match SQL `ROUND(x,0)`.
- `find_person_by_mobile` masks the name inside SQL (LEFT + REPLICATE) so the
  raw name never enters the process.

## Additional modules (beyond the spec's minimum list)
- `app/util.py` — `now_iso`, `round_half_up`, `safe_identifier`.
- `app/deps.py` — FastAPI dependency providers (overridden in tests).

## Build/run status
- `pytest -q` → **23 passed** (fake accounting layer, no real SQL).
- `uvicorn app.main:app` starts; `GET /health` → `{"status":"ok"}`; missing/blank
  `X-API-Key` → 401 (verified live).
- Dry-run writer SQL verified against the real DB via `sqlcmd`:
  `codlp=2 datelp=1405/07/13 mablp=1.00 cnt=1`, then `rolled_back` and
  `persisted_after_rollback=0` (no trace left).
- Reader SQL verified via `sqlcmd` (schema, stock formula `SUM(Megv)-SUM(Megs)`
  matches `Kala.Mogod`, `MiladiToShamsi`, groups, counts).

## RESOLVED — pyodbc now reaches the local SQL Server
The earlier blocker (Python/pyodbc getting
`Shared Memory Provider: Could not open a connection to SQL Server [5]` while the
`sqlcmd` binary could connect) is **gone**: `pyodbc` now connects and the whole
stack has been verified against the real database. TCP/IP and Named Pipes are
still disabled server-side, so the connection goes through the local shared
memory pipe `\\.\pipe\SQLLocal\SQLEXPRESS` — which works fine.

Verified live on `hesab5 t`:

- `scripts/selfcheck.py` → 630 active products, 557 at level 1, 10 groups,
  kardex 6725 rows, Shamsi date `1405/07/13`.
- `tests/check_stock.py` → 20 random products, **0 mismatches** between
  `SUM(Megv)-SUM(Megs)` and `Kala.Mogod`.
- `tests/integration_local.py` → exit 0; `dryrun_codlp=1 rolled_back=True
  committed=False`, and `KalaOrder`/`KalaOrderDetail` stayed at **0** afterwards.
- Live API via `run.ps1`: `/health` ok, `/groups` → 10, `/products` → total 176
  with real prices and stock, search works, missing key → 401.

## The dev database is now `hesab5 t` (with a space)
The active test copy is **`hesab5 t`**, not `hesab5`. Consequences, all handled:

- `app/util.py` now exposes `quote_identifier()` which returns a bracketed,
  escaped identifier (`hesab5 t` → `[hesab5 t]`); the reader, writer, person
  lookup and `scripts/check_stock.py` all use it, so a database name with a
  space is valid T-SQL. `safe_identifier` is kept as a deprecated alias.
- `app/config.py` brace-quotes ODBC connection-string values when needed, so
  `DATABASE=hesab5 t` is emitted correctly.
- Defaults and `.env.example` point at `hesab5 t`.
- `sql/create_api_user.sql` uses `USE [hesab5 t];`.
- **Price level:** only level 1 (`Kala.Gey`) has a real catalogue in this copy
  (557 products; levels 2–5 have 1–2). `PRICE_LEVEL_BOT/SITE` default to **1**.
- `KalaOrder` is **empty** in this copy, so the writer's first order gets
  `Codlp = 1`.

## HIGH bug found by the real-DB integration run (fixed)
`tests/integration_local.py` failed the first time it could reach SQL Server:

```
pyodbc.ProgrammingError: ('The SQL contains 18 parameter markers,
but 17 parameters were supplied', 'HY000')
```

The `KalaOrderDetail` INSERT had **18 placeholders for 17 columns** — an
off-by-one that made *every* real write fail. The fake-connection unit tests did
not catch it because a fake never parses SQL.

Fix: `app/accounting_writer.py` now keeps `HEADER_COLUMNS` (16) and
`DETAIL_COLUMNS` (17) as the single source of truth and builds the statement with
`insert_statement(table, columns, values)`, which raises `ValueError` when the
column and value counts differ. Regression tests added:
`test_insert_statements_have_matching_columns_placeholders_and_params`,
`test_column_lists_match_the_accounting_schema` and
`test_insert_statement_rejects_a_column_value_mismatch`.

Lesson recorded: fake connections must not be trusted for SQL syntax — keep at
least one real-database integration run.

## Windows runner scripts (new)
- `setup.ps1` / `setup.bat` — create `.venv`, install requirements, create `.env`.
  Supports `-PythonExe` and `-IndexUrl` (mirror) when PyPI is filtered.
- `run.ps1` / `run.bat` — start uvicorn (`-Port`, `-Address`, `-Reload`).
- `check.ps1` — configuration + accounting DB + running API + authenticated
  endpoints in one go.
- `scripts/selfcheck.py` — token-free configuration and row-count report.
- shopbots has the same: `setup.ps1`, `run.ps1` (`-Check`, `-DryRun`, `-LogLevel`).
- JSON responses are now `application/json; charset=utf-8` so Windows PowerShell
  5.1 decodes Persian names instead of showing mojibake.

## Final status
- Deliverables complete: `app/`, `tests/`, `scripts/check_stock.py`,
  `scripts/selfcheck.py`, `tests/integration_local.py`, `sql/create_api_user.sql`,
  `sql/verify_permissions.sql`, `setup.ps1`, `run.ps1`, `check.ps1`, `*.bat`,
  `README.md`, `.env.example`, `requirements.txt`.
- `pytest -q` → **53 passed**; all acceptance criteria met against the real
  `hesab5 t` copy: app starts, `/products` returns real data, the dry-run writer
  runs the full transaction and rolls back leaving no trace.
- `ACCOUNTING_CONNECT_TIMEOUT` (default 5s) added so failed connects fail fast
  instead of hanging.

## Security/correctness review (see REVIEW.md)
- `pytest -q` → **38 passed** (23 before the review, 15 regression/concurrency
  tests added). No SQL Server was contacted during the review.
- Checklist: 34 rows — 23 PASS / 11 FAIL / 0 N/A. Fixed: **2 HIGH** (H1, H2) and
  **8 MEDIUM** (M1–M6, M8, M9); LOW left documented (L1, plus notes L2/L3).
- Fixed: dry-run no longer marks orders `written` (H1); writer takes the
  `UPDLOCK, HOLDLOCK` lock before the idempotency check (H2); constant-time API
  key comparison (M1); availability clamped at 0 (M2); bounded/finite `qty` (M3);
  accounting-DB errors return 503 instead of crashing (M4); `person_code` reuse
  blocked unless `ALLOW_SHARED_PERSON_CODE` (M5); `reservation_guard` prevents
  overselling (M6 — measured 17/20 oversold without it, 10/20 with it); query
  timeout added (M7); receipt upload now requires order ownership (M8); a
  `RequestValidationError` handler prevents a NaN/Infinity input from crashing
  the 422 body (M9).
- Open: `/health` stays public (L1); admin reject `reason` is stored verbatim
  (L2); the `TabaghehBandi` SELECT grant is spec-inherited and should be
  re-checked (L3); profile reads have no per-customer credential (channel-key
  trust model — needs a new feature); no idempotency key on `POST /orders`.
- Contract change from M8: `POST /orders/{id}/receipt` now requires
  `platform`+`chat_id` for non-admin callers (same rule as `GET /orders/{id}`).

# REVIEW.md — security & correctness review of `shopapi`

Reviewer role: skeptical senior security/correctness reviewer.
Scope: the existing project only. No features added. `ACCOUNTING_WRITE_ENABLED`
stays `false` by default. No SQL Server was contacted during this review (all
tests use the fake accounting layer); no personal/financial rows were read and no
secrets were printed.

**Result: 38 pytest tests green** (23 before the review, 15 added).

## Checklist table

| # | Item | Status | Severity | File:line | Fix |
|---|------|--------|----------|-----------|-----|
| 1 | SQL parameterized; no string-built SQL from user input | PASS | — | `app/accounting_reader.py:68`, `app/accounting_writer.py:49`, `app/util.py:26` | Only config values (db name) and whitelisted column names are interpolated; the db name is validated by `safe_identifier`. |
| 1 | No SQL newer than SQL Server 2008 R2 | PASS | — | `app/accounting_reader.py`, `app/accounting_writer.py` | No `OFFSET/FETCH`, `STRING_AGG`, `CONCAT()`, `TRY_CONVERT`, `IIF`, `THROW` (grep: only the docstring mentions them). |
| 2 | `Codlp = MAX+1` with `UPDLOCK, HOLDLOCK` in one short transaction | PASS | — | `app/accounting_writer.py:118-122` | — |
| 2 | `COUNT(*)=1` after insert, rollback otherwise | PASS | — | `app/accounting_writer.py:166-175` | — |
| 2 | Idempotency via `Sharhlp='API-<id>'` | **FAIL** | **HIGH** | `app/accounting_writer.py:114-145` | **H2** — the idempotency check ran *before* the lock, so two concurrent writers for one order could both pass it and insert two headers. Reordered: lock first, then idempotency. |
| 2 | `tavasot`/`sharh`/`field1..8` are `''`, never NULL | PASS | — | `app/accounting_writer.py:152`, `:162-163` | Bound as parameters containing `""`; regression test asserts it. |
| 2 | `Codf=-100`, `Status` from config, `va/Taf2/Naghd/Ischeck/PrintCount=0`, `usercode` from config, `Meg=qty`, `Gey=price`, `Num` from 1 | PASS | — | `app/accounting_writer.py:147-164` | — |
| 2 | `Mablp = SUM(ROUND(qty*price,0))` | PASS (note) | LOW | `app/accounting_writer.py:66` | Computed in Python with `round_half_up` (half away from zero) instead of SQL `ROUND`; identical for positive values. |
| 2 | Dry-run really rolls back and is the default; real writes need flag **and** allowlisted host | PASS | — | `app/accounting_writer.py:62-63,177-191`; `app/config.py:137-139` | — |
| 2 | Order state reflects the real write outcome (a dry-run is never reported as written) | **FAIL** | **HIGH** | `app/routers/admin.py:132-152` | **H1** — `approve-payment` set `status='written'` + `accounting_order_no` even when the writer had rolled back, so the order could never be written later. Now only `committed or idempotent` marks it written; otherwise it stays `receipt_uploaded` and is audited as `approve_payment_dry_run`. |
| 3 | No `Telegram_*`; writes only to `KalaOrder`/`KalaOrderDetail` | PASS | — | see "Tables touched" below | Only `INSERT` statements in `app/` target those two tables. |
| 4 | Every endpoint requires the correct API key | **FAIL** | LOW | `app/routers/public.py:29-31` | **L1** — `/health` is unauthenticated (conventional liveness probe). Left as-is; documented. |
| 4 | Admin endpoints reject bot/site keys | PASS | — | `app/routers/admin.py:16`; `app/security.py:98-101` | — |
| 4 | Keys compared in constant time | **FAIL** | **MEDIUM** | `app/security.py:71-85` | **M1** — `dict.get()` leaked timing/shape. Replaced with `hmac.compare_digest` over every configured key (no early exit). |
| 4 | No key in logs or responses | PASS | — | (no logging in `app/`) | 401/403 messages are generic. |
| 5 | A customer can read only their own orders | PASS | — | `app/routers/public.py:186-213` | Ownership required via `platform`+`chat_id`; otherwise 404. |
| 5 | pending/rejected users cannot create orders | PASS | — | `app/routers/public.py:109-110` | — |
| 5 | `person_code` cannot be reused by another user unless configured | **FAIL** | **MEDIUM** | `app/routers/admin.py:55-62` | **M5** — added a uniqueness check plus `ALLOW_SHARED_PERSON_CODE` (default `false`). |
| 5 | Approving verifies the code exists in `name_mo` | PASS | — | `app/routers/admin.py:48-53` | `COUNT(*)` only. |
| 5 | Receipt upload is authorized (IDOR on write) | **FAIL** | **MEDIUM** | `app/routers/public.py:164-193` | **M8** — `POST /orders/{id}/receipt` had *no* ownership check (unlike `GET /orders/{id}`). Now requires the same ownership proof for non-admin. |
| 6 | Price level chosen server-side; client can never send a price | PASS | — | `app/routers/public.py:113`; `app/schemas.py:48-60` | No price field in the request schema. |
| 6 | Availability never negative | **FAIL** | **MEDIUM** | `app/accounting_reader.py:41-48` | **M2** — clamped at 0 (an over-reserved product is "out of stock", not negative). |
| 6 | Quantity positive and bounded | **FAIL** | **MEDIUM** | `app/schemas.py:59`; `app/routers/public.py:122-127` | **M3** — `FiniteFloat` (`gt=0`, `le=1e6`) rejects ≤0/NaN/Infinity; max 100 line items; per-item ceiling `MAX_ORDER_QTY` (default 10000). |
| 6 | Repeated product merged or rejected | PASS | — | `app/routers/public.py:91-95` | Quantities merged per `kala_code`. |
| 6 | Availability re-checked at creation **and** approval; expiry frees reservations | PASS | — | `app/routers/public.py:118`, `app/routers/admin.py:114-128`, `app/db_own.py:280-289` | — |
| 7 | `audit_log`/logs contain no tokens, full phones or `name_mo` names | PASS (note) | LOW | `app/db_own.py:292-299`; `app/routers/*` | **L2** — an admin-supplied reject `reason` (truncated to 200 chars) is stored verbatim; it could contain a phone number if an admin types one. |
| 7 | Person lookup returns only code + masked name | PASS | — | `app/accounting_reader.py:210-228` | Masked inside SQL (`LEFT`+`REPLICATE`); raw name never enters the process. |
| 7 | Error messages do not leak SQL or stack traces | PASS | — | `app/main.py:44-60` | Generic 422/503 bodies. |
| 8 | Secrets: only `.env.example` placeholders; `.env` in `.gitignore` | PASS | — | `.gitignore:1`, `.env.example:16,23` | No git repo exists (history N/A); remaining hits are placeholders/`os.getenv` calls. No real credential anywhere. |
| 9 | Timeouts on DB calls | PASS | — | `app/accounting_reader.py:58-69`, `app/accounting_writer.py:39-45` | **M7** — login timeout (`ACCOUNTING_CONNECT_TIMEOUT`) *and* query timeout (`ACCOUNTING_QUERY_TIMEOUT`, via `conn.timeout`). |
| 9 | Clear error when the accounting DB is unreachable (no crash) | **FAIL** | **MEDIUM** | `app/main.py:52-56` | **M4** — a driver error used to escape as an unhandled 500. Added a `pyodbc.Error` handler → 503 `Accounting database unavailable` (and `sqlite3.Error` → 503). |
| 9 | Concurrency: 20 parallel orders — no duplicate `Codlp`, no overselling | **FAIL** | **MEDIUM** | `app/db_own.py:266-275`; `app/routers/public.py:118-158` | **M6** — the availability check and the reservation were not atomic. Added `OwnDB.reservation_guard()` around read-check-reserve (create, approve, receipt, approve-user). Test proves 10/20 succeed on stock 10; without the guard 17/20 succeeded. |
| 9 | Malformed numeric input must not crash the API | **FAIL** | **MEDIUM** | `app/main.py:44-50` | **M9** (found by the new test) — a rejected `NaN`/`Infinity` crashed JSON serialization of the 422 body. Added a `RequestValidationError` handler that sanitizes non-finite floats. |
| 10 | `sql/create_api_user.sql` valid on 2008 R2, least privilege, placeholder password | PASS (note) | LOW | `sql/create_api_user.sql:13-57` | `CREATE LOGIN/USER`, `GRANT`, `DENY`, `IF NOT EXISTS` are all 2008 R2 safe. **L3** — it grants `SELECT` on `TabaghehBandi`, which in the dev copy holds free-text personal data; the file carries a warning to re-check before granting. |

**Counts — checklist rows:** 34 rows · 23 PASS · 11 FAIL · 0 N/A.
**FAIL by severity:** HIGH 2 (H1, H2) · MEDIUM 8 (M1–M6, M8, M9) · LOW 1 (L1).
Additionally 3 PASS rows carry a LOW note (L2, L3 and the Python-side `Mablp`
rounding). All HIGH and MEDIUM rows were fixed and covered by a regression test;
the LOW rows are documented only.

## Fixes applied (with regression tests)

| ID | Severity | Fix | Regression test |
|----|----------|-----|-----------------|
| H1 | HIGH | `approve-payment` marked the order `written` even when the writer had rolled back (dry-run), so the order could never be written later. It now marks `written` only when `result.committed or result.idempotent`, otherwise it keeps `receipt_uploaded` and audits `approve_payment_dry_run`. `app/routers/admin.py:132-152` | `tests/test_review_fixes.py::test_approve_payment_dry_run_is_not_marked_written`, `::test_approve_payment_idempotent_replay_is_marked_written` |
| H2 | HIGH | Writer reordered so the `UPDLOCK, HOLDLOCK` read happens **before** the `Sharhlp` idempotency check. `app/accounting_writer.py:114-145` | `::test_writer_takes_lock_before_idempotency_check` |
| M1 | MEDIUM | Constant-time API-key comparison via `hmac.compare_digest` over all keys. `app/security.py:71-85` | `::test_key_role_matching`, `::test_admin_endpoints_reject_bot_and_site_keys` |
| M2 | MEDIUM | `compute_available` clamped at 0. `app/accounting_reader.py:41-48` | `::test_availability_is_never_negative` |
| M3 | MEDIUM | `qty` is `FiniteFloat` with `gt=0, le=1e6`; max 100 items; `MAX_ORDER_QTY` ceiling. `app/schemas.py:59`, `app/routers/public.py:122-127` | `::test_quantity_bounds` |
| M4 | MEDIUM | `pyodbc.Error` → 503 (and `sqlite3.Error` → 503). `app/main.py:52-60` | `::test_accounting_db_unreachable_returns_503` |
| M5 | MEDIUM | `person_code` uniqueness unless `ALLOW_SHARED_PERSON_CODE=true`. `app/routers/admin.py:55-62` | `::test_person_code_cannot_be_reused` |
| M6 | MEDIUM | `OwnDB.reservation_guard()` serializes check-then-reserve. `app/db_own.py:266-275`, `app/routers/public.py:118`, `app/routers/admin.py:96` | `tests/test_concurrency.py` (4 tests) |
| M7 | MEDIUM | Query timeout applied on top of the login timeout. `app/accounting_reader.py:58-69`, `app/accounting_writer.py:39-45` | `::test_query_timeout_applied` |
| M8 | MEDIUM | Receipt upload requires order ownership for non-admin callers (same rule as `GET /orders/{id}`). `app/routers/public.py:164-193` | `::test_receipt_upload_requires_order_ownership` |
| M9 | MEDIUM | `RequestValidationError` handler sanitizes non-finite floats so a 422 can always be encoded. `app/main.py:44-50` | `::test_quantity_bounds` (NaN/Infinity cases) |

Concurrency evidence: `tests/test_concurrency.py` creates 20 parallel orders
against a fake accounting layer with stock 10 and asserts exactly 10×`201` and
10×`409` with 10.0 reserved; with `reservation_guard` disabled the same run
produced **17** successful orders (overselling), so the test is load-bearing.

## Tables touched (item 3)

Read (parameterized): `Gkala`, `Kala`, `kardex_an`, `KalaOrderDetail`, `facto`,
`name_mo` (existence `COUNT` + masked mobile match), `KalaOrder`.
Write: `KalaOrder` (`INSERT`), `KalaOrderDetail` (`INSERT`); `EXECUTE` on
`dbo.MiladiToShamsi`. Own DB: `users`, `orders`, `order_items`, `payments`,
`audit_log`. **No `Telegram_*` table is referenced anywhere.**

## Remaining open (not fixed)

1. **L1 — `/health` is unauthenticated.** Deliberate (load balancers need it) and
   it leaks only that the process is up.
2. **L2 — admin reject `reason` is stored verbatim** in `audit_log` (max 200
   chars). Admin-controlled free text; a redaction step for digit runs would
   close it.
3. **L3 — `TabaghehBandi` SELECT grant** is copied from the build spec although
   that table holds free-text personal data in the dev copy; a DBA should confirm
   it is needed (the runtime code does not read it).
4. **Profile reads are not bound to a per-customer credential.** Channel keys
   (`bot`/`site`) are shared infrastructure secrets, so any holder can read any
   profile/order by supplying its `platform`+`chat_id`. This is the documented
   trust model (see `NOTES.md`); closing it needs per-customer tokens, i.e. a new
   feature, so it is out of review scope.
5. **No idempotency key on `POST /orders`** — a client retry creates a second
   order (and a second reservation, released at expiry). Low impact.
6. **Multi-worker duplicate-write is fixed at the SQL level (H2) but there is no
   test with two real connections**; it is verified by statement ordering only.

## Contract change to be aware of

`POST /orders/{id}/receipt` now takes optional `platform` and `chat_id` query
parameters, required for non-admin callers exactly like `GET /orders/{id}`.
This closes M8; if an existing client calls it without them it will receive 404.

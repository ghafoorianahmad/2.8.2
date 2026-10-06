# shopapi

A small, secure REST API in Python (FastAPI) that sits between customer chat
bots / a website and the Sazeh Hesab accounting program (Microsoft SQL Server).

The API reads products, groups, stock and price levels from the accounting DB,
manages customers and orders in its own SQLite database, and writes approved
orders back into the accounting DB **as a dry-run by default** (the full
transaction runs and is rolled back, returning what it *would* have written).

## Safety model (read this first)

- **Read-only by default.** `ACCOUNTING_WRITE_ENABLED=false` means the writer
  runs the full insert transaction and **ROLLS BACK**. Real writes happen only
  when the env var is `true` **and** the SQL Server name is in
  `ACCOUNTING_ALLOWED_HOSTS`.
- **Never read personal data.** The code never selects rows from `name_mo`,
  `kol`, `chek*`, `checkque*`, `Telegram_*` for display. It uses only column
  names, counts and aggregates there. `name_mo` is used only for an existence
  check (`COUNT`) and an exact normalized-mobile match whose name is masked
  **inside SQL**.
- **All accounting SQL is parameterized.** No schema changes, triggers, indexes
  or new tables in the accounting DB.
- **Secrets only from environment / `.env`.** See `.env.example`.

## Requirements

- Windows + PowerShell
- Python 3.10+
- A local SQL Server Express instance `.\SQLEXPRESS` with a restored copy of the
  accounting DB (Windows auth). The dev copy is named **`hesab5 t`** — the name
  contains a space, and the code quotes it as `[hesab5 t]` everywhere.
- ODBC Driver 17 for SQL Server

## Quick start on Windows (scripts)

Three scripts do everything; no manual venv juggling:

```powershell
cd "E:\DSH-Workspace\Software Asr\shopapi"

# 1) one-time: create .venv, install requirements, create .env from .env.example
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1

# 2) verify: prints the DB target, row counts per price level, then the API
powershell -NoProfile -ExecutionPolicy Bypass -File .\check.ps1

# 3) run the API (Ctrl+C stops it)
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -Port 8100 -Reload
```

`setup.bat` and `run.bat` are double-clickable wrappers for the same thing.
If PyPI is slow or filtered, pass a mirror to setup:
`.\setup.ps1 -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple/`

### What `check.ps1` prints

```
== configuration ==
  server        : .\SQLEXPRESS
  database      : 'hesab5 t'  -> quoted as [hesab5 t]
  writer        : dry run (INSERT then ROLLBACK)
  price levels  : bot=1 site=1
== accounting database (read-only) ==
  active products  : 630
  level1 Gey       : 557
  ...
== 2/3  running API ==
  /health  -> {"status":"ok"}
== 3/3  authenticated endpoints ==
  /groups -> 10 groups
  /products?page_size=3 -> total=176 items=3
```

> **Price levels:** in the `hesab5 t` copy only **level 1 (`Kala.Gey`) has a real
> catalogue (557 products)**; levels 2–5 hold 1–2 products each. Keep
> `PRICE_LEVEL_BOT=1` / `PRICE_LEVEL_SITE=1` while testing, otherwise `/products`
> returns almost nothing.

> **Persian text in the console:** responses are sent as
> `application/json; charset=utf-8`, which Windows PowerShell 5.1 needs to decode
> Persian names correctly. If you still see mojibake, run `chcp 65001` or use
> PowerShell 7.

## Setup (manual, Windows PowerShell)

```powershell
cd "E:\DSH-Workspace\Software Asr\shopapi"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env   # then edit .env and set real API keys
```

## Run (manual)

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Check it works:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/groups -Headers @{ "X-API-Key" = "dev-bot-key" }
```

## Tests

```powershell
# unit tests (fake accounting layer, no real SQL)
.\.venv\Scripts\python.exe -m pytest -q

# manual integration against the local copy (dry-run only)
.\.venv\Scripts\python.exe tests\integration_local.py

# stock consistency check (read-only, prints counts + codes only)
.\.venv\Scripts\python.exe scripts\check_stock.py

# full installation self-check (config + DB + counts)
.\.venv\Scripts\python.exe scripts\selfcheck.py
```

## Authentication

Two kinds of callers:

1. **Channel / service keys** (`X-API-Key`, from `.env`):
   - `BOT_API_KEY` → role `bot` (price level `PRICE_LEVEL_BOT`)
   - `SITE_API_KEY` → role `site` (price level `PRICE_LEVEL_SITE`)
   - `ADMIN_API_KEY` → the **service** identity used by the bots for in-chat
     approvals. It can run shop workflows but cannot manage staff or the server.
   - With `SERVICE_KEYS_LOCAL_ONLY=true` (default) the bot and admin keys are
     refused unless the request comes from the server itself (loopback).
2. **Staff** (ShopAdmin): `POST /auth/login` with username + password →
   `Authorization: Bearer <token>`. Roles are enforced **on the server**:

   | role | view | approve/reject customers & payments, expire | manage staff, audit log |
   | --- | --- | --- | --- |
   | `viewer`, `operator` | ✓ | | |
   | `admin` | ✓ | ✓ | |
   | `super_admin` | ✓ | ✓ | ✓ |

   Passwords: scrypt (stdlib), ≥ 8 chars with letters and digits. Only a SHA-256
   of each session token is stored. 5 wrong passwords → 15-minute lock; ≤ 20
   login attempts per address per 5 minutes. Changing a role, disabling an
   account or resetting/changing a password signs that account out elsewhere.
   The first super admin is created with `POST /auth/bootstrap` (service key,
   i.e. only on the server, and only while no staff account exists).

## Endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | liveness |
| GET | `/groups` | product groups (code, name) |
| GET | `/products?q=&group=&in_stock=&page=&page_size=` | hides `active=0` and `price<=0`; `available_qty` already minus reservations |
| POST | `/users/register` | `{platform, chat_id, name, phone}` → status `pending` (idempotent) |
| GET | `/users/{platform}/{chat_id}` | one user |
| POST | `/orders` | `{platform, chat_id, items:[{kala_code, qty}]}`; approved users only |
| POST | `/orders/{id}/receipt` | `{receipt_ref}` → `receipt_uploaded`; non-admin callers must pass `?platform=&chat_id=` |
| GET | `/orders/{id}` | owner must pass `?platform=&chat_id=`; admin can read any |
| GET | `/users/{platform}/{chat_id}/orders` | a customer's own orders |
| GET | `/admin/users?status=pending` | admin |
| GET | `/admin/persons/match?mobile=` | admin; returns `{code, masked_name}` |
| POST | `/admin/users/{id}/approve` | `{person_code}` (verified to exist in `name_mo`) |
| POST | `/admin/users/{id}/reject` | admin |
| GET | `/admin/orders?status=receipt_uploaded` | admin |
| POST | `/admin/orders/{id}/approve-payment` | re-checks availability, writes (dry-run default) |
| POST | `/admin/orders/{id}/reject-payment` | admin |
| POST | `/admin/orders/expire` | expires `awaiting_payment` orders past `reserve_until` |
| GET | `/admin/events?after=` | notification feed (`customer_registered`, `order_created`, `receipt_uploaded`, decisions); no `after` → current position only |
| GET | `/auth/status` | public: `{bootstrap_required}` |
| POST | `/auth/bootstrap` | first super admin (service key only) |
| POST | `/auth/login` / `/auth/logout` | staff session |
| GET | `/auth/me` | current staff account + permissions |
| POST | `/auth/change-password` | own password |
| GET/POST | `/admin/staff` | list / create staff (super_admin) |
| PATCH | `/admin/staff/{id}` | name, role, active (last super admin protected) |
| POST | `/admin/staff/{id}/password` · `/unlock` | reset password / clear lock |
| DELETE | `/admin/staff/{id}` | delete (not yourself, not the last super admin) |
| GET | `/admin/audit` | audit log (super_admin) |

## Configuration

All settings are read from environment variables (or `.env`). See `.env.example`
for the full list. Key ones:

- `ACCOUNTING_*` — connection and writer-safety settings.
- `PRICE_LEVEL_BOT` / `PRICE_LEVEL_SITE` — price level per channel (1-5).
- `RESERVE_HOURS` — how long an order reserves stock.
- `STOCK_WAREHOUSES` — comma-separated warehouse codes; empty = all warehouses.
- `MAX_ORDER_QTY` — maximum quantity per line item (default 10000).
- `ALLOW_SHARED_PERSON_CODE` — allow two customers to share one person code (default `false`).
- `ACCOUNTING_CONNECT_TIMEOUT` / `ACCOUNTING_QUERY_TIMEOUT` — DB login/query timeouts in seconds.

## Switching to production

1. Set `ACCOUNTING_DRIVER=SQL Server Native Client 10.0`,
   `ACCOUNTING_TRUSTED_CONNECTION=no`, `ACCOUNTING_USERNAME=shopbot`,
   `ACCOUNTING_PASSWORD=<strong>`, `ACCOUNTING_ENCRYPT=no`.
2. Run `sql/create_api_user.sql` (replace the placeholder password) and check it
   with `sql/verify_permissions.sql`.
3. Set `ACCOUNTING_WRITE_ENABLED=true` and make sure `ACCOUNTING_ALLOWED_HOSTS`
   contains the production server name.
4. Use a real database for `SQLITE_PATH` (not `:memory:`) and strong API keys.

## Project layout

```
app/
  main.py                 FastAPI app
  config.py               settings from env/.env
  security.py             X-API-Key auth, normalize_fa, masking
  schemas.py              pydantic models
  db_own.py               SQLite own-DB
  accounting_reader.py    read-only accounting access
  accounting_writer.py    order writer (dry-run default)
  util.py                 small helpers
  deps.py                 dependency providers
  routers/public.py       customer endpoints
  routers/admin.py        admin endpoints
tests/                    pytest + manual integration
scripts/check_stock.py    stock consistency check
sql/                      least-privilege SQL scripts
```

See `NOTES.md` for verified schema facts, differences found, and open questions.

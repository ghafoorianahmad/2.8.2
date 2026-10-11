# shopbots

One Python service that runs the **Bale** bot (the only channel, REQUIREMENTS
§2). It talks **only** to the existing REST API `shopapi` over HTTP
(`http://127.0.0.1:8000` by default, header `X-API-Key`). They never touch a
database, SQL Server or any accounting table.

- Shared core (`app/core/`: catalog, cart, orders, customers) + one conversation
  engine; a channel is a thin adapter in `app/platforms/`.
- The old Telegram Bot-API adapter and its proxy were removed (2026-10-11). A
  Telegram channel may come back later on the same core via the MTProto proxy
  pool (REQUIREMENTS §6, phase 7).
- Raw Bot API over HTTPS with `httpx` — **no bot framework**.
- Each platform polls in its own asyncio task with exponential backoff, so a
  failure of one platform never stops the other.
- All texts, buttons and shop info (name, address, phone, hours, card number,
  support contact) are Persian and live in **one editable JSON file**:
  `app/messages.fa.json` (built-in defaults). ShopServer copies it to
  `%ProgramData%\ShopServer\messages.fa.json` on first start; edit that copy and
  restart the task. Keys and placeholders are documented inside the file.

## Requirements

- Windows + PowerShell
- Python 3.10+
- A running `shopapi` with a `BOT_API_KEY` and an `ADMIN_API_KEY`
- Packages: `httpx`, `pydantic`, `python-dotenv`, `pytest` (see `requirements.txt`)

## Setup (Windows PowerShell)

```powershell
cd "E:\DSH-Workspace\Software Asr\shopbots"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env      # fill in the tokens and keys (see below)
```

### Quick start with the Windows scripts

`setup.bat` / `run.bat` are double-clickable; the PowerShell versions take
parameters:

```powershell
.\setup.ps1                                    # venv + requirements + .env
.\setup.ps1 -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple/   # if PyPI is filtered
.\run.ps1 -Check                               # which platforms / how many admins
.\run.ps1 -DryRun                              # start the bot, no network call
.\run.ps1 -LogLevel DEBUG                      # run for real
```

## Create the bot

**Bale** — Bale has its own BotFather inside the Bale app:

1. Open the Bale app, start a chat with **BotFather**, create a bot and copy its
   token into `BALE_TOKEN`.
2. Put the admin chat id in `ADMIN_CHAT_IDS` as `bale:<id>`.

> The Bale base URL (`BALE_API_BASE=https://tapi.bale.ai`) and the Bale feature
> differences are **not yet verified against a real Bale bot** — see `NOTES.md`.

## Configuration (`​.env`)

| Variable | Meaning |
| --- | --- |
| `SHOPAPI_BASE_URL` | Base URL of the shopapi service |
| `BOT_API_KEY` | `X-API-Key` for customer calls (shopapi role `bot`) |
| `ADMIN_API_KEY` | `X-API-Key` for admin calls |
| `BALE_TOKEN` | Bale bot token |
| `BALE_API_BASE` | Bale Bot API base URL |
| `BOT_MESSAGES_FILE` | operator copy of `messages.fa.json` (empty = built-in texts) |
| `SHOW_OUT_OF_STOCK` | list out-of-stock products marked «ناموجود» (default `true`; they can never be ordered) |
| `ADMIN_CHAT_IDS` | comma-separated admin chats: `bale:456` or a bare id (entries for other platforms are ignored) |
| `SQLITE_PATH` | bot state database (default `shopbots.db`) |
| `POLL_TIMEOUT`, `ADMIN_SWEEP_SECONDS` | long-poll timeout, admin poll interval |
| `RATE_LIMIT_MESSAGES`, `RATE_LIMIT_WINDOW` | per-user rate limit (default 20 / 60s) |
| `MAX_INPUT_LEN`, `MAX_NAME_LEN`, `HTTP_TIMEOUT`, `PRODUCT_PAGE_SIZE` | limits |

Tokens come only from `.env` (never from code, never logged). `.env` is ignored
by git.

## Run

```powershell
# validate configuration (prints no secrets)
.\.venv\Scripts\python.exe -m app.main --check

# start both bots without any network call (useful to test the setup)
.\.venv\Scripts\python.exe -m app.main --dry-run

# normal run
.\.venv\Scripts\python.exe -m app.main

# more detail
.\.venv\Scripts\python.exe -m app.main --log-level DEBUG
```

Logs contain only `platform`, `update id` and `event type`. Names, phone numbers
and message text are never logged, and the httpx request logger (which would
print token-bearing URLs) is capped at WARNING by `app/logging_setup.py`.

## Run as a Windows Scheduled Task (starts at boot, restarts on failure)

```powershell
$root    = "E:\DSH-Workspace\Software Asr\shopbots"
$action  = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\python.exe" `
             -Argument "-m app.main" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
             -RestartInterval (New-TimeSpan -Minutes 1) `
             -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "shopbots" -Action $action -Trigger $trigger `
  -Settings $settings -RunLevel Highest -User "SYSTEM"

Start-ScheduledTask -TaskName "shopbots"     # start now
Get-ScheduledTaskInfo -TaskName "shopbots"   # last run / result
Unregister-ScheduledTask -TaskName "shopbots" -Confirm:$false   # remove
```

The `.env` file is read from the project folder, not from the working directory,
so the task works from any cwd.

### As a Windows service (alternative)

A console script is not a native service; use a small wrapper such as
[NSSM](https://nssm.cc/):

```powershell
nssm install shopbots "E:\DSH-Workspace\Software Asr\shopbots\.venv\Scripts\python.exe" "-m app.main"
nssm set shopbots AppDirectory "E:\DSH-Workspace\Software Asr\shopbots"
nssm set shopbots AppStdout "E:\DSH-Workspace\Software Asr\shopbots\shopbots.out.log"
nssm set shopbots AppStderr "E:\DSH-Workspace\Software Asr\shopbots\shopbots.err.log"
nssm start shopbots
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite never touches the network: the Bot API and shopapi are both faked with
`httpx.MockTransport`.

## Project layout

```
app/
  main.py            entry point + adapter construction
  config.py          settings from .env
  texts.py           loads messages.fa.json (all Persian texts / buttons / shop info)
  logging_setup.py   logging that cannot leak tokens
  store.py           SQLite bot state (offsets, conversations, cart, notices, receipts)
  shopapi.py         typed shopapi client with Persian errors
  engine.py          shared conversation engine (customer + admin flows)
  polling.py         per-platform long polling + admin sweep, with backoff
  ratelimit.py       per-user sliding window
  utils.py           digits/phone/masking/format helpers
  platforms/
    base.py          PlatformAdapter interface + shared Bot API HTTP code
    bale.py          BaleAdapter
  core/              channel-independent shop logic (catalog, cart, orders, customers)
tests/               pytest suite with fake platforms
```

## Manual test checklist

**Common**

1. `shopapi` is running and `BOT_API_KEY` / `ADMIN_API_KEY` in `.env` match it.
2. `python -m app.main --check` prints the expected platforms; `--dry-run` exits 0.
3. Start `python -m app.main` and watch the console.

**Bale test bot**

4. `/start` in a private chat → the bot asks for your full name.
5. Send a name → it asks for the phone number *with a contact button*; try both
   the button and typing `09121234567` (and Persian digits `۰۹۱۲...`).
6. Expect "pending approval". The admin chat receives a notice with the masked
   phone; tap **Approve** and type an existing accounting person code.
7. The customer gets the approval message and the main menu.
8. Browse groups → a group → paging (Prev/Next) → a product → `➕/➖` → add to cart.
9. Cart → change quantity → remove → **checkout**; the reply must show the order
   number, the total and the payment instructions from shopapi.
10. Send a payment-receipt **photo**; expect the confirmation. The admin chat
    receives the receipt notice **with the photo** and Approve/Reject buttons.
11. Probe `ACCOUNTING_WRITE_ENABLED=false` → approving the payment must still
    report success while shopapi performs its dry run; with writes enabled the
    order becomes `written`.
12. `GET /admin/orders` on shopapi shows the same statuses; `/pending` and
    `/order <id>` work in the admin chat.
13. Try an admin button from a **non-admin** chat → "این دستور فقط برای مدیران است".
14. Send 21 messages quickly → the rate-limit message appears, then recovers.
15. Open the console/log: it must contain no token, no name and no phone number.

16. Verify against [Bale's official docs](https://docs.bale.ai/): the base URL,
    `getUpdates` long polling, inline keyboards, `request_contact`,
    `answerCallbackQuery`, `editMessageText`, `getFile`/file download, and the
    message-length limit — record the answers in `NOTES.md`.
17. Confirm the Bale bot works **without** any proxy.

## On ShopServer (admin, outages)

- `/myid` answers any user with their chat id (put it in `ADMIN_CHAT_IDS` as
  `bale:<id>`); `/help` lists the commands.
- Bale unreachable: polling retries with exponential backoff (1s ... 60s), logs one
  English + Persian line per outage (`cannot reach the Bot API ... در دسترس نیست`)
  and `connection restored` when it is back. The server never stops.
- Admin notices: new customer (approve/reject), new order (status button) and
  receipt photo (approve/reject payment), sent immediately. With
  `ACCOUNTING_WRITE_ENABLED=false` an approval is a dry run and the admin is told
  so. Decisions made in ShopAdmin reach the customer through shopapi's
  `/admin/events` feed (once per decision).

# CLOUD.md — rules for Claude Code cloud sessions

Read this **before** `CLAUDE.md` when you run in a Claude Code cloud session (Linux container,
GitHub repo `ghafoorianahmad/asr-shop-system`). `CLAUDE.md` (Persian) holds project status and
backlog; `REQUIREMENTS.md` is the source of truth for decisions; `PROGRESS.md` is the phase log.
The workspace-level `E:\DSH-Workspace\CLAUDE.md` that `CLAUDE.md` refers to is **not** in this repo —
its rules are restated in "Hard rules" below.

## What a cloud session is for
- **Phase 7 — Telegram bot** (`REQUIREMENTS.md` §2, §6): a thin Telegram adapter on the shared
  bot core (`shopbots/app/core/`, `shopbots/app/platforms/base.py`, Bale adapter `bale.py` as the
  model), connecting through the MTProto proxy pool. `'telegram'` is already a valid platform value
  in shopapi and shopadmin (see `PROGRESS.md`, Phase 1 notes) — no migration needed.
- **Design tasks**: ShopAdmin UI (`shopadmin/app/ui/`, `theme.py`, `widgets.py`; screenshots via
  `shopadmin/scripts/render_screens.py` with `QT_QPA_PLATFORM=offscreen`, contrast check
  `shopadmin/scripts/contrast_audit.py`), bot texts (`shopbots/app/messages.fa.json`), docs.
- Code, unit tests, docs. Everything is verified against **fakes**, never real services.

## What a cloud session can NOT do
- **No SQL Server.** There is no Sazeh accounting DB, no ODBC driver, no `hesab5 t`. Code that
  touches SQL must be written from `SAZEH_DB_REFERENCE.md` / `shopapi/NOTES.md` and tested with the
  fake accounting layer (`shopapi/tests/`). Mark anything that needs a live DB check as
  "pending live test on hesab5 t" in `PROGRESS.md`.
- **No Windows builds or Windows-only runtime.** No PyInstaller, Inno Setup, `build_all.bat`,
  `*.ps1`, Windows service (pywin32), DPAPI, Credential Manager, Job Objects, `schtasks`, firewall.
  Edit those files only when needed and say clearly that they are untested.
- **No real bot/Telegram traffic.** There are no tokens, no `.env`, no Telethon session in the repo
  and none may be created. Do not call `tapi.bale.ai` / `api.telegram.org` / MTProto with real
  credentials. Live tests are done later by the owner on Windows.
- **No pushing to `main`, no merging, no force-push, no other repos** (the site repo
  `asr-ertebatat-2` is separate and off limits).

## Branch workflow
1. Never commit to `main`. Work on your own branch: the `claude/...` branch the session creates, or
   `cloud/<topic>` (e.g. `cloud/phase7-telegram-bot`, `cloud/design-login-page`). One topic per branch.
2. Start from the latest `origin/main`; commit small, focused commits with clear messages.
3. Push only your branch and open a **pull request to `main`**. The owner reviews, pulls it on the
   Windows PC, runs the Windows-only suites and live tests, and merges.
4. At the end of the work, update `PROGRESS.md` (done / pending / untested-on-Windows / next step)
   and the status section of `CLAUDE.md` **on your branch**.

## Hard rules (from the workspace CLAUDE.md)
- Never work on the production accounting DB. `ACCOUNTING_WRITE_ENABLED` stays `false`; never set
  `ACCOUNTING_ALLOWED_HOSTS` to a production server.
- No schema change (table/index/trigger) in the accounting DB; SQL is always parameterised.
- No personal data: never add real customer names, phones, card numbers, receipts or rows from
  `name_mo`, `kol`, `chek*`, `checkque*`, `Telegram_*`. Test data stays obviously fake
  (`09121234567`, `6037-0000-1111-2222`, …).
- Never commit or print tokens, passwords, API keys, `.env`, `*.db`, `*.session`, TLS keys,
  backups or logs (`.gitignore` covers them — do not weaken it). Values come only from env.
- Don't edit `backups/`, `dist/`, `build/`, `*.bak-*`.
- User-facing texts are Persian; keep files UTF-8. All money is **Rial**.

## Tests on Linux
Each component has its own venv and requirements. Always use `python -m pytest`.

```bash
cd <component>
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

**Linux test results (2026-10-12, Python 3.13):** `shopbots` 160 ✓, `shoptg` 45 ✓ + 2 skipped,
`shopapi` 281 ✓ (needs `apt-get install unixodbc` for `pyodbc`), `shopadmin` runs with
`QT_QPA_PLATFORM=offscreen` after `apt-get install libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1`
but 2 UI tests fail intermittently on Linux (sqlite "closed database" in `test_ui`/`test_notifications`, also
without any change), `shopsystem` 36 ✓ / 12 skipped / 1 failed (Windows path `E:\ShopBackup`).
The shared package must be installed in the venv first: `.venv/bin/python -m pip install ../shared`
(shoptg, shopbots).

The Windows PC remains the reference: a suite that is green on Linux must still be run on Windows
by the owner before merge.

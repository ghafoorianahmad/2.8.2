# shoptg — Telegram price/proxy worker (REQUIREMENTS §5–6, §7c)

> **v2.9.0: bundled in ShopSystem.exe** (`shoptg_app`, `ShopSystem.exe --tg-worker`), started by the
> service when `TG_READER_ENABLED=true`; settings come from the server's `.env` («تنظیمات سرور» ›
> تلگرام), never from a `.env` here (`SHOPTG_NO_DOTENV=1`). Login: «تنظیمات سرور» › «ورود به حساب
> تلگرام» → `ShopSystem.exe --tg-login` → `app/login_flow.py` (JSON lines on stdin/stdout). Key:
> `TG_API_PRESET=tdesktop` (default without `TG_API_ID`: the public Telegram Desktop key and device
> parameters — temporary, secondary account only) or `custom` (`TG_API_ID` / `TG_API_HASH`). The
> separate install below (`SHOPTG_DIR`, `login.ps1`) still works.

Acts as the shop's Telegram **user** account (Telethon, MTProto), read-only:
- every 10 min (`TG_PRICE_INTERVAL_MIN`): new PDFs of the distributor channel → `POST /worker/pricelists` (shopapi parses, checks, holds);
- v2.9.0: daily (`TG_PROXY_COLLECT_HOURS`=24; hourly while fewer than `TG_PROXY_POOL_SIZE`=10 (v2.9.3; was 5) fast ones work) proxy links of `@ProxyMTProto` (`TG_PROXY_CHANNELS`; with the account, or the web preview `t.me/s/…` without one) → never-seen links (`/worker/proxies/unknown`) tested anonymously → `POST /worker/proxies/candidates` with `tested` / `failed`;
- a FloodWait pauses every job for the time Telegram asks;
- health check every 3 min with immediate failover through the shopapi proxy ranking (`/worker/proxies`), then `TG_PROXY`, then direct;
- hourly probe of other proxies with an *anonymous* client (never the shop session: the same auth key from two IPs risks `AUTH_KEY_DUPLICATED`) → `/worker/proxies/report`;
- alerts via `/worker/alerts` (`telegram_login_required`, `telegram_unreachable`; shopapi raises `proxies_all_dead`);
- status JSON in worker state `tg_status`.

Only `/worker/*` with `WORKER_API_KEY` (loopback only). Never joins, posts or marks as read.

## Files
- `app/gateway.py`: the only Telethon user. Proxy link parsing, the fake-TLS (`ee`) MTProxy connection and `connection_for` live in the shared package **`../shared/tgproxy`** (`shop-tgproxy`, also used by shopbots' Telegram bot). Telethon 1.x drops the domain and cannot use `ee` proxies by itself.
- `app/secure_store.py`: the session (StringSession) is DPAPI **LocalMachine** encrypted, with an NTFS ACL for SYSTEM + Administrators (+ `TG_SERVICE_ACCOUNT` read).
- `app/worker.py` (loop), `app/shopapi.py` (client). Link parsing: `tgproxy.proxies` (same rules as shopapi).
- `scripts/login.py` (hidden prompts) and `scripts/check_pricelist.py` (read-only, standalone; parser from `vendor/pricelist` or `../shopapi`).
- `install.ps1`, `login.ps1`, `check_pricelist.ps1`, `run.ps1`, `build_package.ps1` (server zip with wheels for Python 3.12 x64).
- Server steps: **SERVER_GUIDE.md**.

## Development
```powershell
.\install.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest -q      # fake Telethon + fake shopapi, no network
.\run.ps1 -Check
.\build_package.ps1 -OutDir E:\Outputs\ShopTG -PipExtra "--use-deprecated=legacy-certs"
```


## Shared package `shop-tgproxy`
`install.ps1 -Dev` installs `..\shared` into the venv first. `build_package.ps1` builds its wheel into `wheels\`, so the offline server install needs no repo checkout. **Untested on Windows** (the PowerShell edits were made on Linux).

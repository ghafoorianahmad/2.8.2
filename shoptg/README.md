# shoptg — Telegram price/proxy worker (REQUIREMENTS §5–6)

Acts as the shop's Telegram **user** account (Telethon, MTProto), read-only:
- every 10 min (`TG_PRICE_INTERVAL_MIN`): new PDFs of the distributor channel → `POST /worker/pricelists` (shopapi parses, checks, holds);
- weekly: proxy links from followed channels → `POST /worker/proxies/candidates`;
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

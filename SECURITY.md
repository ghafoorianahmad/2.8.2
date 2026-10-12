# SECURITY — Asre Ertebatat 2 store system

Threat model and security controls (REQUIREMENTS §10). Version 2.2.0, 2026-10-12.
Related documents: `shopsystem/deploy/README_FA.txt` (operations, backup and restore, firewall), `shopapi/sql/create_api_user.sql` and `verify_permissions.sql` (SQL rights), `shopapi/REVIEW.md` (an earlier code review), `shoptg/SERVER_GUIDE.md`.

## 1. What we protect

| Asset | Where | Why it matters |
|---|---|---|
| Accounting database «سازه حساب» | SQL Server 2008 R2 `SAZEHHESAB` on the shop server | All money, customers and stock. Its `sa` password is fixed by the vendor. |
| Customer data (phone ↔ Bale chat, orders, receipts) | `%ProgramData%\ShopServer\shopapi.db`, `shopbots.db`, `receipts\` | Personal and payment data. |
| Bale bot token | server `.env` | Whoever holds it can impersonate the shop's bot. |
| SQL password of `shopbot` | server `.env` | Least-privilege, but it still reads the catalogue and phones (`DetailTBL`) and writes orders and persons. |
| Telegram user session (shoptg) | `%ProgramData%\ShopServer\shoptg\` | **Full access to the shop's Telegram account.** |
| Telegram bot token + bot session (Phase 7) | `TELEGRAM_BOT_TOKEN` in the server `.env`; `tg_bot.session` next to `shopbots.db` | Control of the shop's Telegram **bot** only (not the shop's user account). The session file holds the bot's auth key: same ACL as `shopbots.db`; not backed up (`backup.py` copies an explicit file list only); it can be recreated by logging in again with the token. |
| Service keys (`BOT/ADMIN/WORKER/SITE_API_KEY`) | server `.env` | API access as that channel. |
| Staff passwords and sessions | `shopapi.db` (scrypt hashes and session-token hashes) | Access to ShopAdmin. |
| Backup passphrase | server `.env` + **paper** | Opens every off-server backup. |

## 2. Architecture and trust boundaries

```
Internet ── outbound only ──► Bale API (long polling)    Telegram (MTProto via proxies)
                                   ▲                              ▲
                         ┌─────────┴──── shop server (Windows 10, always on) ─┴─────────┐
                         │ service ShopServer  (NT SERVICE\ShopServer, not admin)        │
                         │   supervisor ─┬─ worker: shopapi + Bale bot                    │
                         │               ├─ shoptg (Telethon; filtered environment)       │
                         │               └─ daily backup thread                           │
                         │ shopapi: HTTPS :8443, LAN only (LocalSubnet / allowed IPs)     │
                         │ SQL Server :1433 ◄── pyodbc as `shopbot` (never sa)             │
                         └───────────────▲───────────────────────────▲───────────────────┘
                     HTTPS + pinned cert │ staff login (Bearer)      │ accounting program
                              ShopAdmin PCs (LAN/VLAN)          accounting PCs (LAN)
Website (ArvanCloud, static): links to the bot only, no connection to the server.
```

- **No inbound port from the internet.** Bale and Telegram are reached by outbound long polling. The MikroTik egress rules are configured separately.
- shopapi listens on the LAN for ShopAdmin (Phase 4 decision). The Windows firewall rule `ShopServer` allows Private/Domain networks and LocalSubnet or `FIREWALL_ALLOWED_IPS`, TLS-only. The launcher warns if `API_HOST` is not loopback and TLS is off.
- **Service keys are loopback-only** (`SERVICE_KEYS_LOCAL_ONLY=true`): `BOT_API_KEY`, `ADMIN_API_KEY` and `WORKER_API_KEY` are refused from any other address. LAN clients authenticate as staff (user name, password, then a session token). Roles are enforced in the API.

## 3. Compromise scenarios: what an attacker can and cannot reach

| If this is compromised… | …they can | …they cannot |
|---|---|---|
| **Bale bot token** (leaked `.env`, log) | Read new messages to the bot and answer customers as the shop. Phishing risk: revoke at once in Bale's BotFather. | Reach shopapi, SQL or customer history. The token gives no server access, and Bale keeps no history beyond about 24 hours of pending updates. |
| **A customer's Bale account** | See that customer's own orders and statement. Place orders: unapproved customers are capped by `PENDING_MAX_ORDER_ITEMS`; approved ones are reviewed by staff before invoicing. | Other customers' data: every lookup is bound to the verified contact, and probing other order ids is audited and alerted (`order_probe`). |
| **Someone abusing the bot** | Spam it: the per-chat rate limit kicks in, a flood → one `rate_limited` report → owner alert. Offer someone else's contact: refused, reported as `contact_not_own`. | Register a phone they do not own: only Bale's own share-contact button is accepted, and `contact.user_id` must equal `from.id`. |
| **Website** (ArvanCloud account / static files) | Change texts and links: a fake bot link is the phishing risk. Mitigation: owner account 2FA, and the bot username is printed in the shop. Change model codes (slugs): an unknown or edited slug gets «not found + shop phone» in the bot, never a guessed product (§9a). | Anything on the server: the site holds no keys, no API URL, no prices and no data. Map a slug to a product: mappings live only in shopapi and are set by staff in ShopAdmin. |
| **A ShopAdmin PC** (malware, stolen while logged in) | Do what that staff role may do until the session expires or is revoked. Unattended screens lock on inactivity. | Read `.env`, the SQL password, the bot token or service keys: they are never sent to clients. Change server-only settings (SQL connection, write switch, keys, backup). |
| **A staff password** | Log in from the LAN with that role. | Brute force: 5 failures → 15 min lock, per-IP rate limit, and **owner alert** on lockout or many failures. |
| **shoptg process / Telethon session file** | With the session: the full Telegram account. The file is DPAPI-LocalMachine encrypted plus ACL; any **local administrator of the server** can decrypt it. | Get the Bale token or the SQL password: the supervisor gives shoptg only the local API URL, the CA certificate and `WORKER_API_KEY` (limited to `/worker/*`). |
| **A Telegram customer** | Only the customer flows (the same as Bale). Admin chats exist on Bale only: a Telegram user id never matches `ADMIN_CHAT_IDS`, so a Telegram account cannot approve customers/payments even if its numeric id equals the owner's Bale id. | Owner alerts, admin commands, other customers' data. |
| **The `shopbot` SQL login** | `SELECT` on catalogue columns, `DetailTBL` (phones), `KOL` (statement columns), orders; `INSERT` orders/persons; `UPDATE name_mo(codetaf, telephons)`. | Cost prices (`Geyk/Geya/Geym`), names/addresses in `name_mo`, `setting` (SMS/site credentials), `Telegram_Setting`, `api_online_setting`, `TabaghehBandi`; `UPDATE/DELETE` on orders; any write to `KOL`, invoices or stock. All are DENY'd; check with `verify_permissions.sql`. |
| **The shop server itself (admin)** | Everything on it, including `sa` (the vendor's fixed password is in the accounting program's own files). | — Defence is physical security, Windows updates, a non-shared admin password and off-server **encrypted** backups. |
| **Network (another PC on the LAN)** | Reach shopapi's HTTPS port (staff login only) if inside the allowed subnet. | Reach SQL once `firewall_sql.ps1 -Apply` limits it to the accounting PCs; intercept ShopAdmin (TLS with a pinned fingerprint). |
| **Off-server backup disk (stolen USB)** | Nothing without the passphrase: AES-256-GCM with a scrypt key (n=2¹⁵, r=8). | Read `.env`, the databases or receipts. Tampering is detected (GCM tag per chunk, last-chunk flag). |

## 4. The `sa` problem

The vendor fixes the `sa` password, so it cannot be changed. Controls:

1. Our code **never uses `sa`**. `Settings.accounting_connection_string()` refuses the login `sa` in any case, so the server will not connect. Our code never reads the accounting program's `Options.ini`, and a test enforces that.
2. The network does the rest. `shopsystem/deploy/firewall_sql.ps1`:
   - limits the SQL Server program (and SQL Browser UDP 1434) to the server itself and the listed accounting PCs;
   - turns off broader allow rules (disabled, not deleted; `-Undo` brings them back);
   - is a dry run unless `-Apply` is given.
3. Treat every PC that runs the accounting program as able to reach the whole database. Keep those PCs patched and do not browse the web on them.

## 5. Secrets handling

- Secrets exist only in the server `.env` (data folder ACL: SYSTEM, Administrators, `NT SERVICE\ShopServer`), in shoptg's `.env` (read-only for the service) and in the DPAPI-encrypted session.
- They never travel on a command line. Setup passes the DB password in a JSON file that is deleted at once; backup passphrases arrive by prompt or a process-only environment variable.
- **Logs:**
  - httpx and httpcore are capped at WARNING because their URLs contain the bot token.
  - Every log handler has `RedactingFilter` (`shopbots/app/logging_setup.py`). It masks `bot<token>`, bare tokens, `X-API-Key`/`Authorization`/Bearer values and `password=`/`pwd=`/`passphrase=`/`api_key=`/`secret=`/`token=` values, in messages and in exception text.
  - The audit log stores only masked sources (`…1234`) and ids, never phone numbers or tokens.
- Remote settings (`/admin/server/settings`) have a whitelist. SQL connection, write switch, keys, `API_HOST` and all `BACKUP_*` settings can be changed only on the server.
- The server package refuses `.env`, `*.db`, `*.log`, `*.key` and `*.dpapi` (`build_package.ps1`); the installer build removes `.env`, `*.db` and `*.log` from staging and stops if any remain (`build_installer.bat`).

## 6. Detection and alerts

| Signal | Source | Alert |
|---|---|---|
| SQL, bot, Bale, Telegram worker or **backup** down | `shopapi/app/monitor.py` | Bale message to `ADMIN_CHAT_IDS` + ShopAdmin tray, on change only |
| A component crash loop (3 in 10 min) | supervisor | Bale, at most once an hour |
| `contact_not_own` ×3, `rate_limited` ×3, `receipt_flood` ×2 | bot → `POST /security/report` | Bale + tray `security_alert` |
| `order_probe` ×5 (other people's orders) | shopapi | same |
| `login_failed` ×10 per address, `login_throttled`, `account_locked` | shopapi `/auth/login` | same |

All of the above go to `audit_log` (ShopAdmin → reports). Alerts are limited to one per source and kind per hour, and 6 per hour in total (`security_watch.py`). Price-list holds and dead proxy pools have their own alerts (Phase 3).

## 7. Backups and restore

These are summarized here; the full procedure is in `README_FA.txt` §10.

- **Daily job** (supervisor, `BACKUP_HOUR`=3):
  - it copies consistent SQLite snapshots (online backup API), `.env`, `messages.fa.json`, `receipts\`, `pricelists\` and `tls\`;
  - they go to a local zip in `backups\daily`, 14 kept;
  - a **restore test** follows each backup: SHA-256 of every file, `PRAGMA integrity_check` and row counts against the manifest.
- **Off-server copy** in `BACKUP_COPY_DIR`, a USB or second disk:
  - it is encrypted `.ssbk` only, with AES-256-GCM in 1 MiB chunks and a scrypt key from `BACKUP_PASSPHRASE`;
  - each copy is read back, decrypted and compared to the local zip;
  - without a passphrase nothing leaves the server unencrypted, and the backup is reported as failed.
- **The passphrase:**
  - it is shown once by `ShopSystem.exe --set-backup-passphrase` (160-bit generated, or the owner's own of 20+ characters), and the owner must type it back from paper;
  - **losing it makes every off-server copy unrecoverable.**
- **The Telegram session is never backed up.** It is bound to this machine by DPAPI, so after a restore on new hardware you log in again.
- **Restore** is done with `deploy/restore.ps1`:
  - it runs the restore test first and changes nothing if that fails;
  - then it stops the service, takes a safety copy, restores, starts and checks health;
  - if the health check fails, it rolls back automatically.

  Do the manual drill every 3 months: run `--verify-backup` on the latest `.ssbk` with the paper passphrase.

## 8. Incident response

| Event | Do |
|---|---|
| Bale token leaked | Revoke or replace it in Bale's BotFather, then write the new token in the server `.env` and run `Restart-Service ShopServer`. Search `app.log` for unusual sends. |
| Staff password leaked or PC lost | ShopAdmin → System users: deactivate the user or reset the password; this ends their sessions. |
| `security_alert` | ShopAdmin → reports → audit log: find the `suspicious_*` rows. Block a Bale user by rejecting the customer; for an IP, check which PC it is. |
| Server compromised | Disconnect it from the network. Change the `shopbot` SQL password, the Bale token and the Telegram account sessions (Settings → Devices → terminate). Rebuild Windows, then `restore.ps1` from the off-server copy made before the incident. |
| Backup alert | The server page shows the reason (disk full, USB missing, no passphrase). Fix it, then run `ShopSystem.exe --backup-now`. |

## 9. Known limits and open items

- Any local administrator of the shop server can read everything, including the Telethon session and `sa`. The server's admin account and its physical security are the root of trust.
- shopapi is reachable on the LAN (staff login with TLS) instead of 127.0.0.1 only. This was a Phase 4 decision so that ShopAdmin can run on other PCs.
- A network-share (UNC) backup target works only on a domain, where the computer account gets write rights. Workgroup shops should use a USB disk.
- Not yet verified live:
  - the Windows service install;
  - the firewall scripts on the shop PC;
  - Bale delivery of security alerts;
  - restore on real hardware.
- The installers are not code-signed (SmartScreen warning).

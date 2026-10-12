# shoptg on the shop server: step-by-step guide

This is for the one-time Telegram login on the **shop server** (Windows 10), plus a read-only test.
It does not need shopapi. Nothing here posts to Telegram, joins a channel or changes the accounting database.

## 0. Have these ready

| What | Where it comes from |
| --- | --- |
| Administrator account on the server | You. |
| **Python 3.12, 64-bit** | python.org › Downloads › Windows › "Windows installer (64-bit)", version 3.12.x. In the installer, tick **"Add python.exe to PATH"**, choose **Customize installation**, then tick **"Install Python 3.12 for all users"**. All users matters: the Phase 4 service account must be able to use it. |
| `api_id` and `api_hash` | my.telegram.org, **logged in as the shop's Telegram account**, then "API development tools". The app title and short name can be anything, e.g. `ShopServer` / `shopserver`. |
| The shop's phone | The login code arrives as a message from "Telegram" in the Telegram app of that account. |
| 2FA password | Only if two-step verification is turned on for the account. |
| A working MTProto proxy link | `tg://proxy?server=…&port=…&secret=…` or `https://t.me/proxy?…`. All proxy types work: `ee` (fake-TLS), `dd` and plain. You can skip it if Telegram works on the server without a proxy. |

**Never** send `api_hash`, the login code, the 2FA password, the proxy secret or any file from
`C:\ProgramData\ShopServer\shoptg` to anyone, me included. The scripts never print them.

## 1. Copy

1. Copy `shoptg_server_<version>_<date>.zip` to the server.
2. Check that it arrived intact (in PowerShell). The result must equal the SHA-256 in `README_FA.txt` next to the zip.

   ```powershell
   Get-FileHash .\shoptg_server_*.zip -Algorithm SHA256
   ```

3. Extract the zip to `C:\ShopServer\` (or `Expand-Archive .\shoptg_server_*.zip -DestinationPath C:\ShopServer`).
   You should then have `C:\ShopServer\shoptg\install.ps1`.

## 2. Install (elevated PowerShell)

Open the Start menu, type `PowerShell`, right-click it and choose **Run as administrator**. Then run:

```powershell
cd C:\ShopServer\shoptg
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass     # this window only
Get-ChildItem -Recurse | Unblock-File                          # remove the "downloaded" mark
.\install.ps1
```

`install.ps1` does the following:
- creates `.venv`;
- installs the dependencies **offline** from the bundled `wheels\` folder. If the Python on the server is not 3.12, it installs them from PyPI instead;
- creates `.env`;
- limits `.env` and `C:\ProgramData\ShopServer\shoptg` to SYSTEM and Administrators.

It ends with "Install complete".

> If Python is not found: `.\install.ps1 -PythonExe "C:\Program Files\Python312\python.exe"`.
> If PyPI is slow or filtered (only when the server's Python is not 3.12), add `-IndexUrl <mirror>`.

## 3. Put your keys in `.env` (yourself)

Run this in the same window:

```powershell
notepad .env
```

Fill in:
- `TG_API_ID=` and `TG_API_HASH=`, from step 0;
- `TG_PROXY=`, the proxy link. Optional: without it, the scripts ask for it in a hidden prompt. Several links may be given, separated by spaces;
- `TG_PROXY_CHANNELS=`, optional: the usernames of proxy channels the account follows, comma separated.

Leave everything else as it is, then save and close Notepad.

## 4. Log in once

Run this in the same window:

```powershell
.\login.ps1
```

Every answer is typed into a **hidden** prompt: nothing appears on the screen while you type.
1. **Proxy link.** You are asked only if `TG_PROXY` is empty. Pressing Enter means a direct connection.
2. **Phone number** of the shop account, e.g. `+98912…`.
3. **Login code**, from the Telegram app on the shop's phone.
4. **2FA password**, only if the account has one.

You should see:

```
Connected to Telegram via <host>:<port> (ee)
Telegram sent a login code ...
Login OK. The session is saved encrypted (DPAPI LocalMachine, Administrators/SYSTEM only):
   C:\ProgramData\ShopServer\shoptg\tg_session.dpapi
```

How the session is protected:
- It is encrypted with Windows DPAPI for **this machine**. Copied to another PC, it is useless.
- Only **SYSTEM and Administrators** can open the file. Phase 4 will add read access for the service account.
- In the Telegram app (Settings › Devices) a new session named **"ShopServer"** appears. That is this server: **do not terminate it**. If you ever want to cut the server off, terminate it there and the session stops working at once.

## 5. Read-only test (no shopapi needed)

Run this in the same window:

```powershell
.\check_pricelist.ps1 -Save
```

It reads the newest messages of `@AbrishamiiPhoneMashhad`, downloads the newest PDF and parses it.
With `-Save` it keeps a copy as `C:\ProgramData\ShopServer\shoptg\check_<id>.pdf`.
Expected output, roughly:

```
Connected via <host>:<port> (ee) (850 ms), session is logged in.
@AbrishamiiPhoneMashhad: read 50 newest messages, 3 PDF(s).
Newest PDF: message 1234, posted 2026-10-13T06:10 UTC, 286,478 bytes, '....pdf'
List date      : 1405/07/21
Rows           : 195 (160 with a price, 35 unavailable)
Sections       : iPHONE, ...
Sample rows (customer price in Rial):
  [iPHONE] ...
OK: Telegram login, channel access, download and parsing all work.
```

Other options:
- `-Scan 200` looks further back if no PDF was among the last 50 messages.
- `-ProxyChannels` also counts the proxy links in `TG_PROXY_CHANNELS`.

**Please send me the output of this step.** It contains no secrets. If it says `PARSE FAILED`, also send the saved PDF.

## Troubleshooting

| Message | What to do |
| --- | --- |
| `Run this from an elevated PowerShell` | Open PowerShell with **Run as administrator**. |
| `Set TG_API_ID and TG_API_HASH in …\.env first` | Step 3. Check that there are no spaces or quotes around the values. |
| `Could not connect via … : TimeoutError / OSError / FakeTlsError` | That proxy does not work from the server. Try another link (`TG_PROXY` can hold several). A `FakeTlsError` that says "not signed with this secret" means the secret is wrong or the proxy is not a fake-TLS proxy. |
| `PhoneNumberInvalid` / `Wrong code` | Use the international format `+98…`. Codes expire after a few minutes: run `.\login.ps1` again. |
| `no Telegram session yet` / `not logged in any more` | Run `.\login.ps1` again. Also do this if the "ShopServer" session was terminated in Telegram. |
| `access to the session file was denied` | Use an elevated PowerShell. |
| `No PDF among them` | `.\check_pricelist.ps1 -Scan 200`. |

## Later (Phase 4, not now)

- The worker itself (`.\run.ps1`) needs shopapi with `WORKER_API_KEY` on the same server. It becomes a Windows service in Phase 4.
- The service account gets read access to the session through `TG_SERVICE_ACCOUNT`. No new login is needed.

# ShopSystem packaging notes (PyInstaller)

Packaging layer for the two existing projects. **No business logic or security
feature of `shopapi` / `shopbots` was modified** — this folder only adds a
launcher, a build script and user documentation.

```
shopsystem/
  launcher.py       unified entry point (API thread + bots asyncio loop)
  build_exe.bat     one-command build (--onedir by default, --onefile optional)
  requirements.txt  runtime deps + pyinstaller
  .env.example      user-facing configuration template (ASCII, no BOM)
  README.txt        end-user guide (Persian, UTF-8 with BOM for Notepad)
  NOTES.md          this file
  build_src/        generated at build time (shopapi_app/, shopbots_app/)
  build/            PyInstaller work directory
  dist/ShopSystem/  ShopSystem.exe + dependencies + .env.example + README.txt
```

## 1. The two `app` packages collide — renamed at build time

Both projects ship a top-level package literally named `app`
(`shopapi/app`, `shopbots/app`). A single executable can only have one `app`
module, so `build_exe.bat` copies them into `build_src/` under distinct names:

```
build_src/shopapi_app/   <- shopapi/app
build_src/shopbots_app/  <- shopbots/app
```

This works without touching the projects because every internal import in both
projects is **relative** (`from .config import ...`, `from .. import deps`), so
renaming the top-level folder is enough. Nothing imports `app.something`
absolutely, and the tests do not use these copies.

`launcher.py` therefore imports:

```python
from shopapi_app.main import app as asgi_app     # the FastAPI app object
from shopbots_app.main import run as run_bots    # the bot supervisor
```

Importing the ASGI **object** (instead of the string `"app.main:app"`) is what
lets PyInstaller's static analysis find the whole import graph. A string target
would be invisible to the bundler.

`build_src/` is regenerated on every build, so the projects stay the single
source of truth.

## 2. Configuration comes from `.env` next to the `.exe`

Both projects call `load_dotenv(BASE_DIR / ".env")`, where `BASE_DIR` is derived
from `__file__`. Inside a frozen bundle `__file__` points at the temporary
`_MEIPASS` folder, so that call can never find the user's file. Instead of
modifying them, the launcher loads the real file first:

```python
APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
load_dotenv(APP_DIR / ".env", override=False)
```

`python-dotenv` puts the values into `os.environ`, and the projects' later
`load_dotenv(<temp path>)` is a harmless no-op that does not override anything.
So `.env` **must** sit next to `ShopSystem.exe` — that is also what `app.log`
and the SQLite state files use.

### Friendly variable names are translated in the launcher

The end user asked for simple names; the projects read their own. The launcher
maps them before the projects are imported (`launcher.ALIASES`):

| `.env` name (user) | read by the projects as |
| --- | --- |
| `SHOPAPI_URL` | `SHOPAPI_BASE_URL` |
| `DB_SERVER` | `ACCOUNTING_SERVER` |
| `DB_NAME` | `ACCOUNTING_DATABASE` |
| `DB_DRIVER` | `ACCOUNTING_DRIVER` |
| `DB_TRUSTED` | `ACCOUNTING_TRUSTED_CONNECTION` |
| `DB_USER` / `DB_PASSWORD` | `ACCOUNTING_USERNAME` / `ACCOUNTING_PASSWORD` |
| `DB_ENCRYPT` | `ACCOUNTING_ENCRYPT` |

An existing value is never overwritten, so a user who prefers the original names
can still use them. `ACCOUNTING_WRITE_ENABLED` is defaulted to `false` when
absent (dry run), matching `.env.example`.

### Two SQLite files, not one

`shopapi` and `shopbots` both read `SQLITE_PATH`, but they must not share one
file: each keeps a long-lived connection with its own lock, and SQLite allows a
single writer, so mixing them produces `database is locked`.

- `launcher` sets `SQLITE_PATH=<exe dir>\shopapi.db` for the API.
- For the bots it also overrides `settings.sqlite_path = <exe dir>\shopbots.db`
  and passes its own `Store(settings.sqlite_path)` into `run_bots(...)`; the
  `Settings` dataclass is mutable, so no project change is needed.

## 3. Failure isolation

| Subsystem | Where | On crash |
| --- | --- | --- |
| API (uvicorn) | background thread `shopapi` | logs the traceback, restarts up to 5 times with 5→30 s backoff; the bots keep polling |
| Bots (Bale + admin sweep) | background thread `shopbots` running `asyncio.run(...)` | logs, restarts up to 10 times; the API keeps serving |

The main thread only supervises: it waits until **both** threads are dead, so a
crash in one never takes the process down. `SystemExit` (e.g. "port already in
use" from uvicorn) is caught as `BaseException`, because otherwise it would kill
the thread silently. `sys.excepthook` and `threading.excepthook` write any
unhandled exception to `app.log` as well.

Inside the bot subsystem the per-platform isolation already exists
(`shopbots/polling.py`: one task per platform, exponential backoff).

## 4. Logging

`app.log` (UTF-8) next to the `.exe`, plus the same lines on the console:

```
%(asctime)s %(levelname)-7s %(name)s: %(message)s
```

* uvicorn is started with `log_config=None`, so `uvicorn.error` /
  `uvicorn.access` propagate to the root handlers and land in `app.log`.
* `shopbots_app.logging_setup.silence_noisy_loggers()` is applied: httpx logs
  request URLs at INFO and Bot API URLs contain the token, so those loggers are
  capped at WARNING. Without it the bot token would be written to `app.log`.
* The console prints the "Do not close this window" banner and, if it ever
  stops, waits for Enter (`_pause()`), so a double-clicked window never vanishes
  before the user can read it.

Optional flags: `ShopSystem.exe --api-only` and `--bots-only`.

## 5. Hidden imports and PyInstaller fixes

`uvicorn` resolves its protocol/lifespan implementations dynamically at
run time, so static analysis misses them. `build_exe.bat` adds:

```
--collect-submodules uvicorn, anyio, starlette, shopapi_app, shopbots_app
--collect-data certifi
--hidden-import uvicorn.logging / uvicorn.loops.auto / uvicorn.loops.asyncio
--hidden-import uvicorn.protocols.http.auto / .h11_impl
--hidden-import uvicorn.protocols.websockets.auto
--hidden-import uvicorn.lifespan.on / .off
--hidden-import anyio._backends._asyncio
--hidden-import shopapi_app.main / shopbots_app.main
--hidden-import dotenv / sqlite3 / pyodbc / httpx / httpcore
--hidden-import email.mime.multipart
```

Excluded to keep the bundle small: `tkinter`, `matplotlib`, `numpy`, `pandas`,
`PyQt5`, `pytest`.

`pyodbc` needs no extra handling: PyInstaller picks up `pyodbc.pyd` as a binary
and the driver itself (`ODBC Driver 17 for SQL Server`) is a system component,
so the target machine must have it installed — as the task requires.

### If a module is still missing at run time

Symptom: `ModuleNotFoundError: No module named 'x'` in `app.log` right after
startup. Fixes, in order of preference:

1. add `--hidden-import x` to `build_exe.bat`, rebuild;
2. if it is a whole package with a dynamic layout, use
   `--collect-submodules x` (or `--collect-all x` when data files matter too);
3. for a data file, `--collect-data x` or `--add-data "src;dest"`;
4. last resort: `--paths "<folder>"` so the module is found, then re-add the
   hidden import.

## 6. `--onedir` (default) versus `--onefile`

`--onedir` is the default because FastAPI/uvicorn start faster from an
already-unpacked folder and the antivirus does not rescan a fresh temp
extraction on every launch.

**To build a single file**, either pass the argument:

```bat
build_exe.bat onefile
```

or change one line in `build_exe.bat`:

```bat
set "MODE=onedir"      ->      set "MODE=onefile"
```

The output then lands directly in `dist\ShopSystem.exe` (the script detects the
mode and copies `.env.example` / `README.txt` to `dist\` instead of
`dist\ShopSystem\`).

Trade-offs of `--onefile`:

* every start extracts the whole bundle to `%TEMP%\_MEIxxxx`, so startup takes
  several seconds longer and needs free space in `%TEMP%`;
* some antivirus products flag a self-extracting exe more often;
* `app.log`, `.env` and the SQLite files still land **next to the `.exe`**, not
  in the temp folder, because the launcher uses `sys.executable`.

## 7. Build output

```
dist/ShopSystem/
  ShopSystem.exe        <- double-click this
  .env.example          <- copy to .env and fill in
  README.txt            <- Persian guide for the end user
  NOTES.md
  _internal/            <- Python runtime, DLLs, bundled packages
  app.log               <- created on the first run
  shopapi.db            <- created on the first run (API state)
  shopbots.db           <- created on the first run (bot state)
```

## 8. Build verification (actual results)

Environment: Windows, Python 3.12.14, PyInstaller 6.22.3,
pyinstaller-hooks-contrib 2026.8, fastapi 0.142.2, uvicorn 0.54.0,
pydantic 2.13.5, pyodbc 5.3.0, httpx 0.28.1, python-dotenv 1.2.4.

1. `build_exe.bat` ran the suites first and only then built:
   **shopapi → 53 passed**, **shopbots → 48 passed**.
2. The only notable PyInstaller message is informational, not an error:

   ```
   DEPRECATION: Running PyInstaller as admin is not necessary nor sensible.
   ```

   It changes nothing in the output; run the build from a normal (non-elevated)
   terminal to silence it.
3. Build finished → `dist/ShopSystem/` is **35.7 MB**: `ShopSystem.exe`
   (9.1 MB), `_internal/`, `.env.example`, `README.txt`, `NOTES.md`.
4. The packaged exe was started with a `.env` beside it (database `hesab5 t`,
   port 8123) and served **real data**, which proves the frozen bundle reads the
   external `.env` and reaches SQL Server:

   | request | result |
   | --- | --- |
   | `GET /health` | `{"status":"ok"}` |
   | `GET /docs` | HTTP 200 |
   | `GET /groups` | 10 groups, Persian decoded: `كليه كالاها` |
   | `GET /products?page_size=2` | `total=176`, `گلس انتي استاتيک` at `3,500,000` |

   `app.log` was created next to the exe and contains the shopapi startup lines,
   the uvicorn access log and the graceful bots warning
   `bots: no BALE_TOKEN configured - running the API only`.
   The console printed the required banner verbatim.
5. Started **without** `.env`, the exe prints the three recovery steps, records
   them in `app.log`, keeps the window open for a double-click and exits with
   code 2.
6. `.env`, `app.log`, `shopapi.db` and `shopbots.db` all appear **next to the
   `.exe`**, never inside `_internal/` — the frozen path logic is confirmed.

### Rebuild checklist

```bat
build_exe.bat              :: onedir (recommended)
build_exe.bat onefile      :: single file, copied to dist\ShopSystem.exe
```

Then copy `.env.example` → `.env` in the output folder, fill it in and run
`ShopSystem.exe`.

### Running the launcher from source (for debugging)

`launcher.py` is not exe-specific; with the generated packages on `PYTHONPATH`
it runs as a normal script, which is handy when a bundled import goes wrong:

```powershell
cd "E:\DSH-Workspace\Software Asr\shopsystem"
$env:PYTHONPATH = "E:\DSH-Workspace\Software Asr\shopsystem\build_src"
.\.venv\Scripts\python.exe launcher.py --api-only
```

Verified: in source mode it also answers `/health` and returns the same real
`/groups` data (10 groups).


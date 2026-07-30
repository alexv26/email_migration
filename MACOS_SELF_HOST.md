# Running mail-transfer on your own Mac

This is an alternative to the Render deployment, not a replacement — `render.yaml` and the hosted version are untouched. This documents the setup already running on this MacBook Air, so you (or future-you) can reproduce, restart, or undo it.

## What's running, and how it stays up

| Piece | How it's kept alive | Config |
|---|---|---|
| Redis | Homebrew service (`brew services start redis`) | starts at login, restarts on crash |
| The app (`start_combined.sh` — web server + job worker) | LaunchAgent `com.mailtransfer.app` | `macos/com.mailtransfer.app.plist` |
| Sleep prevention | LaunchAgent `com.mailtransfer.caffeinate` running `caffeinate -s` | `macos/com.mailtransfer.caffeinate.plist` |
| Public HTTPS URL | Tailscale Funnel (`--bg`, backed by the Tailscale system service) | no repo file — lives in Tailscale's own state |

Unlike the Windows setup, macOS didn't need any code changes to run `start_combined.sh` itself — `gunicorn` and RQ's default (forking) worker both just work here, and this was actually run and verified directly on this machine rather than written blind. The one real bug found and fixed along the way: `start_combined.sh`'s `.env` parsing (values with spaces or a trailing `=`, like Gmail app passwords and Fernet keys, were getting mangled) — now fixed for every deployment target, including Render/Linux.

## Config

Same `.env` file used by the CLI now also holds the webapp config (`webapp/config.py` calls `load_dotenv()`):
```
APP_PASSWORD=...       # shared invite password for your group
ADMIN_PASSWORD=...     # separate, only for you - gates /admin/jobs
SESSION_SECRET=...
FERNET_KEY=...
REDIS_URL=redis://localhost:6379
COOKIE_SECURE=true     # Funnel serves real HTTPS, so this stays true (unlike plain-http local testing)
MAX_THREADS=2
FETCH_BULK_SIZE=20
PORT=8000
```

## Your public URL

```
https://alexs-macbook-air.tail0a20e3.ts.net
```
Send this plus `APP_PASSWORD` to your invite group — same as the Render URL would have been. `/admin/jobs` on that same URL, with `ADMIN_PASSWORD`, is your admin view.

## Reproducing this setup (e.g. after a fresh clone, or on another Mac)

```bash
brew install redis
brew services start redis

brew install --cask tailscale   # needs your Mac password interactively
# open Tailscale.app, log in, then in Terminal:
tailscale funnel --bg --https=443 localhost:8000
# first time only: it'll print a login.tailscale.com/f/funnel?... link -
# open that in a browser and approve it, then re-run the funnel command above

python -m venv venv
venv/bin/pip install -r requirements.txt
# create .env with the keys listed above

cp macos/com.mailtransfer.app.plist macos/com.mailtransfer.caffeinate.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mailtransfer.caffeinate.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mailtransfer.app.plist
```
Note the plists have this machine's absolute paths baked in (`/Users/alexvelsmid/alexv-26/projects/mail-transfer/...`) — edit them if the project ever moves or you're setting this up on a different Mac.

## Common operations

**Restart the app** (e.g. after editing `.env` or pulling new code):
```bash
launchctl kickstart -k gui/501/com.mailtransfer.app
```

**Check it's running:**
```bash
launchctl list | grep mailtransfer
curl http://localhost:8000/healthz
```

**View logs:**
```bash
tail -f ~/Library/Logs/mail-transfer.log
```

**Stop everything:**
```bash
launchctl bootout gui/501/com.mailtransfer.app
launchctl bootout gui/501/com.mailtransfer.caffeinate
tailscale funnel --https=443 off
brew services stop redis
```

**Pull new code and restart:**
```bash
git pull
venv/bin/pip install -r requirements.txt   # if requirements.txt changed
launchctl kickstart -k gui/501/com.mailtransfer.app
```

## Known limitations vs. Render

- **The Mac must stay on and connected.** A restart, a `caffeinate`/power failure, or closing the lid without power connected takes the whole thing down mid-migration, same failure mode as anything else in this "self-host" family (same trade-off documented for Windows and for Render's free-Redis-tier issue).
- **`caffeinate -s` only prevents *idle* sleep while on AC power** — closing the lid still sleeps the Mac regardless (that's a hardware-level behavior `caffeinate` doesn't override). Keep the lid open, or use an external display/clamshell-mode setup if you want to close it.
- If the worker subprocess inside `start_combined.sh` crashes but gunicorn keeps running, launchd's `KeepAlive` won't notice (it only watches the process it started directly, gunicorn) — same accepted trade-off as on Render.

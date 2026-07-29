# Running mail-transfer on your own Windows PC

This is an alternative to the Render deployment, not a replacement for it — `render.yaml` and the hosted version are untouched. Use this if you'd rather run the app on a PC you leave on at home instead of paying Render's monthly cost.

## Why this differs from the Render setup

Render runs on Linux, and a few of its pieces don't work on Windows at all, so this uses different (but equivalent) tools:

| Render uses | Windows uses | Why |
|---|---|---|
| `gunicorn` | plain `uvicorn` | gunicorn is Unix-only |
| RQ's default forking worker | `rq worker --worker-class rq.SpawnWorker` | Windows has no `os.fork()`; `SpawnWorker` uses `os.spawn()` instead, and still gives each job its own process — important because that's what makes the "cancel a running job" feature work |
| Render's managed Redis | Redis running inside WSL2 | Windows has no native Redis; the Windows-native option (Memurai) caps free use at 10 days of uptime and forbids production use, which defeats the point of an always-on setup |
| Render's public URL | Tailscale Funnel | gives a stable `https://your-pc.your-tailnet.ts.net` URL without needing to buy a domain |

## 1. Install prerequisites

- **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/). During install, check "Add python.exe to PATH."
- **Git** — [git-scm.com](https://git-scm.com/download/win) (or just download the repo as a ZIP from GitHub instead, if you'd rather skip Git).
- **WSL2 + Redis** — open PowerShell **as Administrator** and run:
  ```powershell
  wsl --install
  ```
  Reboot when it asks. After reboot, an Ubuntu window opens (or run `wsl` from PowerShell) — set a username/password when prompted, then inside that Ubuntu shell run:
  ```bash
  sudo apt update && sudo apt install -y redis-server
  sudo service redis-server start
  redis-cli ping   # should print PONG
  ```
  Redis needs to be running (`sudo service redis-server start`) every time before you start the app — see the persistence section below for automating this.
- **Tailscale** — [tailscale.com/download/windows](https://tailscale.com/download/windows). Install it, sign in (a free personal account is enough), and confirm it's connected (icon in the system tray).

## 2. Get the code and install dependencies

In PowerShell:
```powershell
git clone https://github.com/alexv26/email_migration.git
cd email_migration
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

## 3. Create your `.env` file

In the project folder, create a file named `.env` (no filename before the dot) with:
```
APP_PASSWORD=choose-an-invite-password
ADMIN_PASSWORD=choose-a-different-admin-password
SESSION_SECRET=generate-this-below
FERNET_KEY=generate-this-below
REDIS_URL=redis://localhost:6379
COOKIE_SECURE=true
MAX_THREADS=2
FETCH_BULK_SIZE=20
PORT=8000
```
Generate `SESSION_SECRET` and `FERNET_KEY`:
```powershell
venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"
venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Paste each result into the matching line in `.env`. (`COOKIE_SECURE=true` is correct here, not just for Render — Tailscale Funnel serves real HTTPS, so secure cookies work.)

## 4. Run it

Make sure Redis is running inside WSL first (`wsl -e sudo service redis-server start`), then from PowerShell in the project folder:
```powershell
powershell -ExecutionPolicy Bypass -File start_windows.ps1
```
This starts the background job worker and the web server together (mirrors `start_combined.sh` on Render). Leave this window open — closing it stops the app. Visit `http://localhost:8000` to confirm it's working before moving on to Funnel.

## 5. Expose it publicly with Tailscale Funnel

One-time: in the [Tailscale admin console](https://login.tailscale.com/admin/dns), under **DNS**, enable **HTTPS Certificates** if it isn't already.

Then, in a separate PowerShell window (leave `start_windows.ps1` running in the first one):
```powershell
tailscale funnel --bg --https=443 localhost:8000
```
`--bg` keeps it running in the background across reboots (backed by the Tailscale Windows service, which starts automatically). Get your public URL with:
```powershell
tailscale funnel status
```
That URL (`https://your-pc-name.your-tailnet-name.ts.net`) is what you send to your invite group — same as the Render URL would have been.

To stop exposing it: `tailscale funnel --https=443 localhost:8000 off`

## 6. Keep it running automatically (survive reboots/logouts)

Right now, `start_windows.ps1` only runs while that PowerShell window is open. To have it start automatically:

1. Open **Task Scheduler** → **Create Task** (not "Basic Task," so you get the full options).
2. **General** tab: name it, select "Run whether user is logged on or not," check "Run with highest privileges."
3. **Triggers** tab: New → "At startup."
4. **Actions** tab: New → Action "Start a program" →
   - Program: `powershell.exe`
   - Arguments: `-ExecutionPolicy Bypass -File "C:\path\to\email_migration\start_windows.ps1"`
   - Start in: `C:\path\to\email_migration`
5. Save.

You'll also want WSL's Redis to start automatically — the simplest approach is a second scheduled task running `wsl -e sudo service redis-server start` at startup, or configure it via `/etc/wsl.conf` boot commands inside the WSL Ubuntu instance.

## Known limitations of this setup vs. Render

- **Your PC must actually stay on and connected.** A reboot (e.g. a Windows Update), sleep, or you turning it off takes the whole thing down, including any migration running at the time — same failure mode as the free-Redis-tier issue we hit on Render, just triggered by your PC instead.
- **No separate worker process isolation from Render's per-service monitoring.** If the `uvicorn` window/task dies, the `rq worker` child process (started by `start_windows.ps1`) dies with it — there's nothing watching and restarting it independently the way Render would restart a crashed service.
- This hasn't been run end-to-end on a real Windows machine as part of building it (I don't have one to test against) — the commands above are verified against each tool's current documentation, but if something doesn't match what you see on your machine, tell me exactly what happened and I'll help debug it.

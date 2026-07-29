# Mail Transfer

Copies mail from one IMAP account to another, folder by folder. It exists in two forms that share the same core logic:

1. **A CLI script** (`main.py`) — run it yourself with your own credentials.
2. **A small web app** (`webapp/`) — a hosted version so a handful of trusted people can run their own migrations through a browser, with the migration running in the background.

This document explains how the code actually works, piece by piece.

---

## 1. The core problem: copying mail over IMAP

IMAP (Internet Message Access Protocol) is how an email client talks to a mail server: list folders, fetch messages, add messages, etc. There's no "copy this mailbox to that other server" command in the protocol — because the two mailboxes usually live on two different servers that don't know about each other. So the only way to migrate mail is to **read a message out of the source server and write it into the destination server yourself**, one message at a time.

That's the whole shape of this project: for every folder in the source account, fetch its messages, and `APPEND` (IMAP's "add a message to this folder" command) each one into the matching folder on the destination account.

We use the [`imap-tools`](https://pypi.org/project/imap-tools/) library, which wraps Python's built-in (but low-level and clunky) `imaplib` in a friendlier API — `MailBox(...).login(...)`, `.folder.list()`, `.fetch()`, `.append()`.

---

## 2. `mail_transfer/` — the domain logic

This package contains the actual migration logic, with zero knowledge of whether it's being driven by a terminal or a web request. That separation is deliberate — see [§5](#5-why-the-logic-is-split-into-a-separate-package).

### `mail_transfer/core.py`

**`EmailInfo`** — a tiny bag of `(imap_host, email, password)` for one account. Used for both the source and destination.

**Folder filtering** — not every folder should be copied:

```python
SKIP_FOLDER_FLAGS = {"\\Drafts", "\\Sent", "\\Trash", "\\Junk"}
SKIP_FOLDER_NAMES = {"drafts", "sent", "sent items", ...}
```

IMAP servers *can* tag special folders with standard flags (`\Junk` for Spam, `\Sent` for Sent Mail, etc. — [RFC 6154](https://www.rfc-editor.org/rfc/rfc6154)), and Gmail does this. But not every server bothers (e.g. Bluehost's Dovecot backend often doesn't advertise these flags at all). So `is_skipped_system_folder()` checks **both**: the flag, and a fallback list of common English folder names, so system folders get skipped either way.

**Folder name translation** (`build_dest_folder`) — different IMAP servers use different characters to separate nested folders (`folder.delim`). Gmail uses `/`. Bluehost/Dovecot commonly uses `.`, so a folder might be named `INBOX.Work.Projects` on the source. If we pasted that raw string into a Gmail folder name, Gmail would create one flat folder literally called `INBOX.Work.Projects` instead of three nested folders. So this function splits the source name on *its own* delimiter and rejoins the pieces with `/` — the delimiter Gmail expects — preserving the nested structure across servers that disagree about syntax.

**`ensure_dest_folder`** — tries to create the destination folder and swallows the specific "already exists" error. This matters because of a race condition: with multiple threads creating folders concurrently (see below), or when the script is simply run twice, a naive "check if it exists, then create it" has a gap between the check and the create where another thread (or a previous run) might have already created it. Attempting the create and only ignoring the "already exists" response is the standard fix — it makes the operation *idempotent* (safe to repeat).

**`copy_folder`** — the actual per-folder work: select the folder on the source, ensure the destination folder exists, then loop `source.fetch()` and `copy_message()` each one into the destination.

A couple of non-obvious `fetch()` options:
- `bulk=100` — fetches 100 messages per IMAP command instead of one command per message. IMAP round-trips are the real bottleneck (network latency, not CPU), so batching fetches cuts that down substantially.
- `mark_seen=False` — by default, *reading* a message over IMAP marks it as read. This flag stops the migration from silently marking your entire source mailbox as read.

**`copy_all_folders`** — the top-level entry point: lists the source's folders, filters out system folders, and fans the remaining folders out across a `ThreadPoolExecutor`. Each folder is copied by a separate thread, each with its *own* pair of IMAP connections (`copy_folder_worker`) — IMAP connections aren't thread-safe, so they can't be shared. `threads` is clamped to `ABSOLUTE_MAX_THREADS` (20) no matter what the caller passes, as a hard safety limit against something (a bug, a malicious input) requesting an absurd number of simultaneous connections against someone's mail server.

### `mail_transfer/progress.py`

```python
class ProgressReporter:
    def start_job(self, total_folders, folder_names): ...
    def start_folder(self, folder_name, total_messages): ...
    def advance_message(self, folder_name, done, total): ...
    def finish_folder(self, folder_name): ...
    def finish_job(self): ...
    def error(self, folder_name, message): ...

NULL_REPORTER = ProgressReporter()
```

This is the **[Null Object pattern](https://en.wikipedia.org/wiki/Null_object_pattern)**: a base class whose methods all do nothing. `copy_all_folders`/`copy_folder` call these methods at the right moments (a folder started, a message copied, an error happened) but don't care *what*, if anything, happens in response. If you don't pass a `reporter`, `NULL_REPORTER` is used and nothing happens — no `if reporter:` checks scattered through the migration logic.

The CLI and the web app each provide their own subclass that does something different with those same calls:
- The CLI's `TqdmProgressReporter` (in `main.py`) draws terminal progress bars.
- The web app's `RQProgressReporter` (in `webapp/progress.py`) writes structured progress into Redis so a browser can poll it.

This is what let us build the web app *without touching the migration logic at all* — `copy_all_folders` doesn't know or care that it's being watched by a browser instead of a terminal.

---

## 3. `main.py` — the CLI

Thin wrapper around `mail_transfer.core`. Its only two jobs:

1. **Get credentials.** Either from `.env` (via `python-dotenv`) if you pass `--use_env`, or by prompting interactively with `input()`/`get_email_args()`.
2. **Render progress.** `TqdmProgressReporter` keeps one [`tqdm`](https://github.com/tqdm/tqdm) progress bar per active folder-thread, plus one overall bar. The tricky part is that `tqdm` bars need a fixed terminal line (`position=`) or concurrent threads will overwrite each other's line. `_get_thread_position()` hands out a stable line number the first time each thread reports progress (keyed by `threading.get_ident()`, the OS thread ID) and reuses it for that thread's whole run.

Run it with `python main.py` (interactive prompts) or `python main.py --use_env` (reads `.env`).

---

## 4. `webapp/` — the hosted version

The goal: let a small group of people run migrations through a browser instead of a terminal, with the migration running in the background (so closing the browser tab doesn't kill it) and progress visible on a page.

### The pieces, and why each one exists

| File | Job |
|---|---|
| `config.py` | Reads all configuration from environment variables into one `settings` object. Fails loudly at startup if a required secret is missing, rather than failing confusingly later. |
| `security.py` | The security-critical helpers — see [§4.2](#42-security-what-and-why). |
| `auth.py` | Turns "the shared invite password" into a signed session cookie. |
| `ratelimit.py` | A generic Redis-backed rate limiter, reused for both login attempts and job submissions. |
| `progress.py` | `RQProgressReporter` — writes migration progress into Redis so it can be polled. |
| `jobs.py` | Talks to `rq` (Redis Queue) — enqueues migrations, fetches job status. |
| `worker_tasks.py` | The function that actually *runs* on the background worker process. |
| `app.py` | Builds the FastAPI app, wires up the auth middleware, mounts static files and routes. |
| `routes/auth_routes.py` | `/login`, `/logout`. |
| `routes/migration_routes.py` | `/` (the form), `/migrate` (submit), `/status/<id>` (status page), `/api/status/<id>` (JSON polled by the browser). |
| `templates/`, `static/` | Server-rendered HTML (Jinja2) + a small vanilla-JS polling script. No frontend framework — at ~10 users, one isn't needed. |

### 4.1 Why a background job queue at all?

A normal web request has to finish quickly — the browser is waiting on the other end, and most hosting platforms will kill a request that hangs too long. A mailbox migration can run for hours. So instead of doing the migration inside the HTTP request, `POST /migrate` just **enqueues** the job and returns immediately (`enqueue_migration()` in `jobs.py`).

We use **[RQ (Redis Queue)](https://python-rq.org/)**: a simple job queue built on Redis. `jobs.py` defines a `Queue`; a separate, always-running process (started with the `rq worker` command, see `render.yaml`) watches that queue and executes jobs as they arrive — one at a time, in our configuration, so a mailbox migration doesn't compete with others for the same IMAP connections.

`webapp/worker_tasks.py:run_migration` is the function that actually executes on the worker. It's just a thin adapter: decrypt the credentials, build `EmailInfo` objects, call the exact same `copy_all_folders()` from `mail_transfer.core` that the CLI uses, with an `RQProgressReporter` attached.

### 4.2 Security: what, and why

This app holds other people's email passwords (well, app passwords) for two accounts each, submitted through a form to a server you operate. That's a meaningfully higher bar than "a script I run for myself," so several things are deliberately more careful than they'd otherwise need to be:

**Credentials never touch disk in plaintext.** RQ has to pass the job's arguments through Redis to get them from the web process to the worker process. Redis *can* persist to disk (snapshots). So before enqueueing, `security.encrypt_payload()` encrypts the whole credentials blob with [Fernet](https://cryptography.io/en/latest/fernet/) (symmetric authenticated encryption) using a key that lives only in an environment variable (`FERNET_KEY`), never in the code or in Redis. The worker decrypts it, uses it, and lets it fall out of scope — even if Redis's disk snapshot were somehow read by someone, they'd see ciphertext, not passwords.

**Errors are scrubbed before they're stored or shown.** If a migration fails (bad password, network error, whatever), the raw exception message might contain the password verbatim (some IMAP error responses echo back what you sent). `security.scrub_secrets()` replaces any known secret value with `[redacted]` before the message is ever written to `job.meta` (visible to the browser) or re-raised. Note the `raise RuntimeError(scrubbed) from None` in `worker_tasks.py` — the `from None` matters: without it, Python would chain the *original* exception (with the unscrubbed message) into the traceback, and RQ stores that traceback, undoing the scrubbing.

**SSRF protection on the IMAP host fields.** "SSRF" (Server-Side Request Forgery) is what happens when an attacker gets a server to make a network request *on their behalf* to somewhere the attacker couldn't reach directly — often the server's own internal network, or a cloud provider's metadata endpoint (`169.254.169.254`, which often exposes credentials for the machine itself). Here, the server is going to open a TCP connection to whatever hostname the user types into the "IMAP host" field — which is exactly the shape of an SSRF vector if the app is hosted on cloud infrastructure. `security.validate_public_host()` resolves the hostname's actual IP address and rejects it if it's private, loopback, link-local, or the metadata address — checking the **resolved IP**, not the hostname string, since a hostname can *look* innocuous while resolving somewhere it shouldn't. It's called twice: once in the web request (fast feedback) and again immediately before connecting inside the worker (the authoritative check, closest to the actual risk).

**Rate limiting.** `ratelimit.check_rate_limit()` is a small [fixed-window counter](https://en.wikipedia.org/wiki/Rate_limiting#Fixed_window) built on two Redis commands (`INCR` + `EXPIRE`). Applied to login attempts (protects the shared password against brute-forcing) and to job submissions per session (stops one person from flooding the queue).

**Session cookies, not accounts.** There's one shared password for the whole app (`APP_PASSWORD`), not individual logins. On success, `auth.create_session_token()` signs a small payload (`{sid, job_id}`) with [`itsdangerous`](https://itsdangerous.palletsprojects.com/) — this isn't encryption, it's a *tamper-proof signature*: anyone can see the cookie's contents, but they can't forge or modify one without knowing `SESSION_SECRET`. `SessionAuthMiddleware` in `app.py` checks this signed cookie on every request except `/login` and `/static/*`, redirecting to the login page if it's missing, invalid, or expired.

**Job ownership.** Each session's cookie records which `job_id` it started. `/status/<id>` and `/api/status/<id>` both check that the requested `job_id` matches the session's own — so one person can't watch another's migration progress (which could reveal folder names, message counts) even though everyone shares the same login password.

**Job cleanup.** Once `/api/status/<id>` observes a job has finished (successfully or not), it calls `job.delete()` — removing it, and the encrypted credentials that were its arguments, from Redis right away, rather than waiting for the TTL-based expiry (`RESULT_TTL_SECONDS`/`FAILURE_TTL_SECONDS`) to eventually clean it up on its own.

### 4.3 Request flow, end to end

1. Browser hits `/`. `SessionAuthMiddleware` sees no valid session cookie → redirects to `/login`.
2. User submits the shared password. `auth_routes.login_submit` checks it (`secrets.compare_digest`, which takes the same amount of time whether the first character matches or not — an ordinary `==` comparison leaks *how much* of the password was right via timing), rate-limits by IP, and on success sets a signed session cookie.
3. Browser is redirected to `/`, now passes the middleware, sees the migration form (`submit.html`).
4. User fills in both accounts' credentials and submits. `migration_routes.submit_migration`:
   - Checks the session doesn't already have an active job.
   - Rate-limits by session.
   - Validates `threads` is in range and both hosts pass the SSRF check.
   - Encrypts the payload, enqueues it (`jobs.enqueue_migration`), stamps the new `job_id` into the session cookie, redirects to `/status/<id>`.
5. Somewhere else entirely, an `rq worker` process picks the job off the queue and runs `worker_tasks.run_migration` — decrypts the payload, connects to both IMAP servers, and calls `copy_all_folders()`, with `RQProgressReporter` writing progress into `job.meta` in Redis as it goes (throttled to avoid hammering Redis on every single message — see the `min_interval` logic in `webapp/progress.py`).
6. Meanwhile, the browser's `status.js` polls `/api/status/<id>` every 2 seconds, rendering the folders and message counts it gets back as progress bars — plain DOM manipulation, no framework.
7. On completion or failure, the next poll sees a terminal status, the API route deletes the job from Redis, and `status.js` stops polling.

---

## 5. Why the logic is split into a separate package

Early on, `main.py` had *everything* — the migration logic, `tqdm` bars, `input()` prompts, all mixed together. That's fine for a script only you run. But once a second "driver" (the web app) needed to run the same migration logic, duplicating `copy_all_folders` into two places would mean every future bug fix or feature had to be made twice, and the two copies would inevitably drift apart.

`mail_transfer/` is the fix: it contains only the parts that are true regardless of *how* the migration is being run — the IMAP calls, the folder-skipping rules, the delimiter translation. Anything specific to *how progress is shown* or *how credentials are obtained* stays outside it, in whichever driver (`main.py` or `webapp/`) needs it. The `ProgressReporter` null-object pattern is what makes that separation possible without littering the core logic with `if running_in_web_mode:` branches.

---

## 6. Running it locally

**CLI:**
```bash
python main.py --use_env   # reads .env
# or
python main.py             # interactive prompts
```

**Web app** (needs Redis running):
```bash
redis-server --daemonize yes

# in one terminal — the background worker
APP_PASSWORD=... SESSION_SECRET=... FERNET_KEY=... REDIS_URL=redis://localhost:6379 \
  rq worker --url redis://localhost:6379 default

# in another — the web server
APP_PASSWORD=... SESSION_SECRET=... FERNET_KEY=... REDIS_URL=redis://localhost:6379 COOKIE_SECURE=false \
  uvicorn webapp.app:app --reload
```
`FERNET_KEY` can be generated with:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
`COOKIE_SECURE=false` is only needed for local `http://` testing — the deployed version runs over HTTPS and defaults to `true`.

## 7. Deploying

`render.yaml` defines the production topology: a web service, a worker service, and a managed Redis instance, all wired together. See the comment at the top of that file for the one-time setup step (setting `APP_PASSWORD` and `FERNET_KEY` in the Render dashboard).

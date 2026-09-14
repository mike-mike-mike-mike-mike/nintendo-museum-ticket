# Nintendo Museum Ticket Monitor — Scheduled GitHub Actions + Email

Date: 2026-09-12
Status: Approved design, pending step-0 validation

## Problem

The monitor today is a long-running process: `main.py` calls
`NintendoMuseumMonitor.monitor()`, which loops forever on
`time.sleep(MONITOR_INTERVAL)` and holds seen dates in an in-memory set
(`self.notified_dates`). It notifies through a Discord webhook. It needs a
machine that stays awake, loses all state on restart, and notifies on a channel
we no longer want.

We want a stateless single-shot job, scheduled by GitHub Actions, that notifies
by email and persists its state in a committed JSON file.

### Functional bug found during design

`main.py` passes `datetime.now()`'s year and month, so only the *current* month
is ever checked. A survey of the live API on 2026-09-12 counted days matching
the notify condition (`sale_status == 1 and open_status == 1`):

| Month | Matching days |
|---|---|
| 2026-09 (current) | 0 |
| 2026-10 | 0 |
| 2026-11 | 0 |
| 2026-12 | 24 |

Tickets open roughly three months out, so the existing current-month-only
behavior would never fire. The month to watch therefore becomes explicit
configuration rather than being derived from the clock.

## Scope

In scope: single-shot refactor, config+state JSON, Gmail notification, removal
of Discord and proxy support, the scheduled workflow, and a pre-flight probe.

Out of scope: changing the availability condition itself, the `apply_type`
field's meaning, and any retry/backoff beyond what Actions' schedule provides.

## Architecture

```
cron-job.org --POST--> GitHub Actions (workflow_dispatch only)
        |
        v
   uv run main.py
        |
        +-- read state.json  -> config.target_months, state.available
        +-- fetch calendar for each target month   (src/monitor.py)
        +-- compute newly-available = current - previous
        +-- email if newly-available is non-empty  (src/notifier.py)
        +-- write state.available = current        (src/state.py)
        |
        v
   git commit + push state.json (only when the file actually changed)
```

### Components

- `main.py` — entry point. Orchestrates the five steps above. No loop.
- `src/monitor.py` — `NintendoMuseumMonitor.fetch_calendar(year, month)` and a
  pure `available_dates(calendar_data, today)`. No notification, no state, no
  loop, no proxies.
- `src/state.py` — load/save the JSON document. Save mutates **only** the
  `state` section and writes `config` back byte-for-identical in content.
- `src/notifier.py` — `send_availability_email(dates)` over stdlib `smtplib`
  and `email.message`. No new dependency.

Deleted: `utils/load_proxies.py`, `utils/discord_utils.py`, the
`discord-webhook` dependency, and `MONITOR_INTERVAL`.

`utils/logging_setter.py` stays as-is. It already calls
`os.makedirs(..., exist_ok=True)` and attaches a `StreamHandler`, so it works on
a fresh runner and its console output lands in the Actions log. Its file handler
writes to a gitignored `logs/` that nobody reads on CI — harmless, left alone to
avoid unrelated churn.

## Data: `state.json`

One file holds configuration and state, as requested. Name kept from the
original plan even though it now carries config too.

```json
{
  "config": {
    "target_months": ["2026-12"]
  },
  "state": {
    "available": ["2026-12-03", "2026-12-04"]
  }
}
```

- `config.target_months` — list of `YYYY-MM` strings. A single-element list is
  the normal case; a list costs nothing and avoids editing code to watch two
  months. Human-owned: the job never writes this section.
- `state.available` — the set of dates currently available, **not** an
  append-only log of what was notified. Notification fires on
  `current - previous`. This bounds file growth and correctly re-notifies a date
  that sold out and later reopened, which is the event of interest.

`last_run` from the original plan is deliberately omitted. It would change on
every run, producing a commit every 5 minutes (~288/day) with no information
that the Actions run history doesn't already carry.

### `.gitignore`

`.gitignore:49` is `*.json`, which silently ignores `state.json` — confirmed
with `git check-ignore -v state.json`. A `!state.json` negation must be added
**after** that line, and re-verified with `git check-ignore` returning no match.
Without it the workflow's `git add` is a permanent no-op.

## Failure behavior

State advances only on full success, so a failed run is always safe to retry.

- **A fetch fails transiently** — timeout, connection error, HTTP 5xx, or 429 →
  log a warning, write nothing, **exit 0**. On a 5-minute schedule a loud failure
  would mean a red X and a GitHub failure email every 5 minutes until Nintendo
  recovered. Retry logic is a deliberate follow-up, not part of this change.
- **A fetch fails in a way that is not transient** — HTTP 401/403, or a 200 whose
  body is not the expected JSON shape → log, **exit non-zero**. A 403 is the
  single most important signal this design can receive: it most likely means the
  runner's datacenter IP is blocked, which invalidates the architecture. It must
  never be swallowed as noise.
- **Any fetch failure, transient or not** → write nothing. Writing a partial
  `current` set would drop dates that were merely unfetched, then spuriously
  re-notify them on the next run.
- **Email fails** → log, exit non-zero, write nothing, so the next run retries
  the same notification.
- **Email succeeds** → write state, then let the workflow commit.
- **All fetches succeed and nothing is newly available** → still write state,
  then commit. Availability that *shrank* (a date sold out) must be recorded, or
  those dates stay in `state.available` forever and never re-notify when they
  reopen. The rule is: a full successful fetch always writes state; an email, if
  one is required, must succeed first.

Unexpected exceptions propagate and fail the job rather than being swallowed;
Actions surfaces them in the run log and its own failure history. Malformed
`state.json` and a failed email send are hard failures, never transient.

### Configured month entirely in the past

If every entry in `config.target_months` has fully elapsed, the job logs a
warning and exits 0. It is not a hard failure: this monitor is intended for one
specific month, and a hard failure after that month passes would just be noise.
The warning exists so that a permanently quiet monitor can be told apart from
one that simply has no tickets to report.

### First run

`state.available` starts empty, so every currently-available date counts as new.
With `target_months: ["2026-12"]` that is ~24 dates. Per decision, the first run
emails them all — as **one** email listing every new date, not one email per
date as the current Discord code does.

## Workflow

`.github/workflows/monitor.yml`

- `on: workflow_dispatch` only — no `schedule` trigger; see "Known
  limitation (RESOLVED)" below for why the cron was removed
- `permissions: contents: write` — nothing broader
- `concurrency: {group: ticket-monitor, cancel-in-progress: false}`
- `timeout-minutes: 5` — a hang guard, so a stuck run cannot occupy the job
  slot for the 6-hour default while new runs fire every 5 minutes
- Steps: checkout → `astral-sh/setup-uv` → `uv sync --frozen` →
  `uv run main.py` → conditional commit and push

Python setup uses `astral-sh/setup-uv` with `uv sync --frozen`, honoring
`.python-version`. The original plan's `pip install -r requirements.txt` does
not apply: this project uses `pyproject.toml` + `uv.lock`.

The working tree's modified `uv.lock` is committed as part of this work. Its only
changes are a lockfile format bump (`revision` 1 → 3), added `upload-time`
metadata, and the project version catching up to `pyproject.toml`
(`0.1.0` → `1.0.0`); no package versions move. Both the old and new lockfiles
were verified to `uv sync --frozen` cleanly, so this is hygiene rather than a
blocker — but leaving it dirty means the next `uv` command re-dirties the tree.

Commit step, guarded so an unchanged file produces no commit:

```
git add state.json
git diff --cached --quiet || (git commit -m "Update ticket availability state" \
  && git pull --rebase --autostash && git push)
```

The `pull --rebase` covers a human pushing between checkout and push.

### Secrets

`GMAIL_USER`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL_TO`, passed as `env` on the
run step and read via `os.environ`. Gmail SMTP over `smtp.gmail.com:587` with
STARTTLS. The app password requires 2FA on the Google account and is not the
account password. No secret appears in `state.json`, source, or workflow YAML.

## Step 0: validate before building

`src/monitor.py` uses `curl_cffi` with `impersonate="chrome110"` and supported
Webshare residential proxies. That combination is strong evidence that Nintendo
blocks datacenter traffic. GitHub runners are datacenter IPs. The API returns
200 from a residential IP, which proves nothing about a runner.

So the first deliverable is a throwaway `workflow_dispatch`-only probe that
fetches the calendar from a runner and prints the HTTP status. If it returns
non-200, this design is void: proxies become mandatory, which changes both the
secrets story and the "no extra infrastructure" premise. Nothing else is built
until the probe returns 200. The probe workflow is deleted afterward.

## Testing

`pytest` added as a dev dependency (none exists today).

- `available_dates()` against a captured calendar fixture: picks up
  `(1,1)` days, rejects `(2,1)` and `(1,2)`, rejects past dates.
- Set difference: unchanged availability yields no notification; a new date
  yields exactly one; a date that disappears and returns notifies again.
- `src/state.py` round-trip preserves `config.target_months` untouched.
- Fetch failure and email failure both leave `state.json` unmodified.

Email sending is tested against a stubbed SMTP transport; no live send in tests.

Manual validation, in order: run locally end-to-end; trigger via
`workflow_dispatch`; confirm the email arrives and `state.json` is committed;
trigger again and confirm no duplicate email; force a failure and confirm state
did not advance.

## Known limitation (RESOLVED 2026-09-14 — superseded by external trigger)

The original design accepted GitHub's best-effort `*/5` cron, noting it was
adequate for "probably notice within the hour" but not reliable 5-minute
polling, and that Actions would be the wrong scheduler if catching a drop
within minutes were a hard requirement.

**That limitation was measured and proved disqualifying.** Cron went live at
`2026-09-13T20:58:08Z`; over the following ~6 hours the observed gaps between
scheduled runs were **128, 113, and 115 minutes** — roughly 2 of every 71
requested runs. The target month is `2026-11`, which is sold out, so the
monitor's purpose is catching a *cancellation*. Returned tickets are claimed
quickly, making a ~2-hour poll interval effectively useless.

A second, worse defect surfaced while fixing the first: any workflow carrying a
`schedule` trigger is **auto-disabled after 60 days without repository
activity**, that disable applies to *every* trigger on the workflow (users
report `pull_request` triggers dying too), and it does **not** re-enable on new
activity. A monitor watching a sold-out month finds no new dates, so it writes
no state, so it makes no commits — meaning zero repository activity and a
silent death on day 60, precisely when it is being relied upon.

**Resolution:** the `schedule` trigger is removed entirely and the workflow is
driven only by `workflow_dispatch`, posted by an external scheduler
(cron-job.org) against the REST dispatch endpoint. Removing `schedule` is what
takes the 60-day auto-disable rule out of scope — it has no scheduled workflow
to act on. Per-run design, state model, and failure semantics are unchanged.

This moves the reliability dependency from GitHub's scheduler onto the external
service, which is the intended trade. The residual risk is that the external
job is deleted or silently stops; `workflow_dispatch` returns `204 No Content`
on success, so the external service can detect and alert on a non-2xx dispatch,
but it cannot detect its own absence.

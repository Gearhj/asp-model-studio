# Nightly Current-Statcast Synchronization

This runbook operates the existing `asp.mlb.statcast.current-pa.v1` and
`gold-table:gold_mlb_current_pa_v1` authorities. It does not fit, score,
calibrate, select, promote, or activate a model.

## Manual operation and catch-up

Run from the ASP Model Studio repository with its existing `.venv`:

```powershell
Set-Location C:\Users\james\asp-model-studio
.\scripts\run_nightly_current_statcast_sync.ps1
```

The safe default is `latest-completed`. It discovers every missing completed
date, so the same command is the normal manual catch-up after the computer was
off. To stop at an explicit official cutoff:

```powershell
.\scripts\run_nightly_current_statcast_sync.ps1 -Through 2026-09-03
```

The correction window defaults to the requested through-date plus the three
preceding completed dates. Override only when an operator intentionally needs a
different bounded review window:

```powershell
.\scripts\run_nightly_current_statcast_sync.ps1 -Through latest-completed -CorrectionLookback 3
```

The equivalent direct command is:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.sync_mlb_current_statcast --through latest-completed --correction-lookback 3
```

Repeated successful execution is a valid no-op. `COMPLETE_EMPTY` dates remain
accounted for without rows. An unresolved acquisition or verification failure
must leave coverage unadvanced and retryable.

## Logs, locking, and exit status

Each wrapper run writes one timestamped combined log to the ignored local
directory:

```text
.runtime\asp-model-studio\logs\current-statcast-sync-<timestamp>-<pid>.log
```

The log contains the command's human-readable output and machine-readable
health report. It does not print environment variables, credentials, provider
keys, or session secrets. Never put a secret in a Task Scheduler argument.

The Python synchronization command owns a nonblocking interprocess publication
lock. If another run owns the lock, it publishes nothing, reports `LOCK_BUSY`,
and exits `75`. Task Scheduler's own multiple-instance setting is an additional
operational safeguard, not the authority lock.

Exit codes:

- `0`: successful synchronization, including a verified no-op or accounted
  empty date;
- `75`: another synchronization owns the execution lock; nothing was
  published;
- any other nonzero value: preflight, acquisition, normalization, publication,
  or verification failed. The wrapper preserves the Python exit code; a
  wrapper preflight failure exits `1`.

## Recommended Windows Task Scheduler configuration

Create the task manually; the repository does not create or modify scheduled
tasks.

1. Open **Task Scheduler** and choose **Create Task**.
2. Name it `ASP Model Studio - Nightly Current Statcast Sync`.
3. Under **General**, select James's local Windows account and **Run whether
   user is logged on or not**, when local policy permits. Do not place the
   account password in the script or repository.
4. Add a **Daily** trigger for approximately **4:00 AM**. Confirm the computer's
   Windows time zone is Eastern.
5. Add one **Start a program** action:

   - Program/script:
     `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`
   - Arguments:
     `-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\Users\james\asp-model-studio\scripts\run_nightly_current_statcast_sync.ps1"`
   - Start in: `C:\Users\james\asp-model-studio`

6. Under **Conditions**, enable **Wake the computer to run this task** when the
   machine and local policy permit.
7. Under **Settings**:

   - enable **Run task as soon as possible after a scheduled start is missed**;
   - enable **If the task fails, restart every 30 minutes**, with **3** attempts;
   - choose **Do not start a new instance** when the task is already running.

After saving, use **Run** once and confirm a `0` last-run result plus a new log.
If the computer was off for multiple days, run the default manual catch-up
command above; it detects all missing completed dates in one bounded run.

Do not configure the task with data-root credentials, sportsbook credentials,
model-training flags, or a second provider. The task must run only from this
repository and its existing local Python environment.

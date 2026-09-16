# MLB V18 Windows scheduler ownership

The durable owner is the single Windows task `\ASP MLB V18 Research Publisher`.
Its action starts one bounded dispatcher tick using the repository's explicit
`.venv\Scripts\python.exe`. Windows owns the schedule independently of Codex.
The dispatcher decides from local event state whether acquisition or publication
is due; the five-minute trigger does not authorize a new fit, model selection,
paid source, betting action, or changes to AISP.

## Owner and schedule

The installer uses the current Windows user's SID, `S4U`, and `LeastPrivilege`.
It never requests or stores a password and never falls back to SYSTEM. S4U is
the least-privileged secretless noninteractive choice for this user-owned local
deployment. Interactive-token tasks would depend on an active login; SYSTEM
would grant broader privileges and use a different profile and credential
context. Microsoft documents that S4U has no network or encrypted-file access:
therefore registration alone does not establish that public HTTPS, localhost
PostgreSQL, or user-local dependencies work in the scheduled context. A real
scheduled dispatcher receipt must establish the capabilities actually exercised.
No working interactive-shell check should be reported as an S4U capability test.
[Microsoft: task logon types](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype).

The task has a startup trigger delayed one minute and a time trigger repeated
every five minutes indefinitely, with `StartWhenAvailable=true`. Omitting the
repetition duration is the documented indefinite form. Catch-up after downtime
is queued by Windows and can be delayed; the task does not execute while the
machine is powered off or asleep, and `WakeToRun` is false. It may run on battery.
[Microsoft: repetition duration](https://learn.microsoft.com/en-us/windows/win32/taskschd/repetitionpattern-duration),
[Microsoft: missed-start handling](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable).

`IgnoreNew` prevents overlapping instances of the Windows task, and its wall-clock
limit is 60 minutes. The runner supplies its own process lock and bounded work.
The launcher also owns its process tree in a Windows Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so termination of the launcher closes the
job and terminates its inherited Python descendants. Failure to establish that
guard fails closed before Python starts. This uses nested jobs supported since
Windows 8 / Windows Server 2012.
[Microsoft: multiple instances](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-multipleinstances),
[Microsoft: task time limit](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-executiontimelimit),
[Microsoft: process-tree job semantics](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

## Branch-safe code and shared evidence

The executable release is a frozen snapshot below
`.deployments/mlb-v18-unattended/<commit>/`, outside the mutable `.runtime`
and `outputs` directories. `build_mlb_v18_deployment.py` reads the current Git
HEAD and archives only tracked `.py`, `.json`, `.ps1`, `.toml`, `.yaml`, and `.yml`
files under `scripts` and `server`. It excludes `server/data`, `server/artifacts`,
and `server/static`. The narrow source-URL helper dependency closure is also
included: `tools/bronze_acquisition/{__init__,sources,safety}.py`, plus
`tools/__init__.py` if tracked. These helpers only construct the already-authorized
source URLs; the release does not copy their data or other acquisition tools.
The builder validates archive bytes against their original Git blob identities
and records SHA-256 hashes in `deployment-build.json`.

Existing identical release files are reused; any mismatch or unexpected code
file fails closed. Nothing is deleted or overwritten. The release's `outputs`
and `.runtime` directory junctions point to the original repository's
corresponding directories. The builder verifies existing junctions and only
creates absent ones. The installer checks both targets and refuses the ordinary
working checkout as `CodeRoot`.

The launcher and the task working directory are in the release snapshot. The
original repository's Python executable is absolute; no venv activation, shell
profile, current branch, Codex process, or PATH lookup selects executable code.
The task supplies no execution-policy override. Windows PowerShell 5.1 reported
an effective `RemoteSigned` policy during the bounded 2026-09-10 check; locally
generated release scripts therefore had no observed policy blocker. A later
policy restriction or downloaded-file marking must be reported, not bypassed.
The launcher exports `ASP_V18_REPOSITORY_ROOT` and `ASP_V18_CODE_ROOT` so runtime
state and code identity remain distinct. The runner receives
`MLB_V18_DEPLOYMENT_MANIFEST` for the installed deployment identity.

Installation records SHA-256 hashes for the Python executable and every deployed
file with the six code/config extensions under `scripts`, `server`, `tools`, or
the release root, including the launcher and build receipt. Every tick uses the
same enumeration to check both the file set and hashes before execution. An edit,
addition, or deletion fails closed and requires a reviewed replacement release.
This detects code drift; it is not an OS access-control boundary and does not
hash every installed venv package. Preserve the selected venv environment. The
runner separately verifies frozen model artifacts and their provenance. Changing
the main checkout to NBA does not select NBA code for this task.

## Prepare, inspect, and install

Commit the reviewed dispatcher, launcher, builder, and support changes first.
The builder reads only HEAD's bytes, so uncommitted working files cannot enter
the release. Neither the builder nor its plan mode registers or starts a task.

```powershell
& .\.venv\Scripts\python.exe .\scripts\build_mlb_v18_deployment.py --plan-only
$release = & .\.venv\Scripts\python.exe .\scripts\build_mlb_v18_deployment.py | ConvertFrom-Json

& .\scripts\install_mlb_v18_unattended.ps1 -Mode Plan `
  -RepositoryRoot C:\Users\james\asp-model-studio `
  -CodeRoot $release.code_root

& .\scripts\install_mlb_v18_unattended.ps1 -Mode Install `
  -RepositoryRoot C:\Users\james\asp-model-studio `
  -CodeRoot $release.code_root
```

`Plan` is read-only and prints the exact task XML and deployment summary.
`Install` writes `.runtime/mlb-v18-unattended/deployment.json`, registers or
updates the canonical task, and reads back its principal and important settings.
It does not explicitly start the task; the first time trigger is one minute
after registration. Existing V18 owners or a running canonical instance block
replacement. An unrelated task occupying the canonical name also blocks
registration. Existing deployment manifests are retained as timestamped backups.
No existing task, service, or process is automatically deleted or disabled.

After installation, inspect `Get-ScheduledTask` and `Get-ScheduledTaskInfo` for
this exact task and inspect the runner's receipt from an actual scheduled tick.
Task registration success and `LastTaskResult=0` alone do not establish source
freshness or publication success; the runner's evidence determines that result.
Treat logout/restart survival as configured, not empirically proven, until a
normal logout/restart followed by a scheduled receipt has been observed. The
installer does not reboot or log out the user.

## Stop and resume

Creating `.runtime/mlb-v18-unattended/STOP` in the original repository prevents
new launcher work; the runner checks the same switch during its bounded cycle.
The file is independent of the current Git branch. To stop an active task
immediately, use `Stop-ScheduledTask -TaskPath '\' -TaskName
'ASP MLB V18 Research Publisher'`; its Job Object tears down child workers.
Resume by removing only the exact `STOP` file when desired. Task disable/enable
may also be used for administrative maintenance, without creating another owner.
The launcher writes immutable small records under
`.runtime/mlb-v18-unattended/launcher-receipts/`. STOP evidence includes the first
observed timestamp and switch creation/modification clocks and never starts
Python. Readiness evidence records code validation, the process-tree guard,
actual owner SID, Windows session ID, PowerShell version, and effective execution
policy. Completion records include Python's exit code. Errors include a fixed
failure code, exception type, HRESULT, and native Windows error code when present,
without arbitrary exception text, credentials, or response data.

Records are deduplicated by deployment manifest, session, outcome, and stable
details; repeated healthy ticks, an unchanged error, or the same STOP episode
do not create a new launcher receipt every five minutes. The runner retains the
per-tick operational evidence. Correlate readiness with the actual task run time
and session before describing it as an S4U test; a manual launcher run has the
same user SID but is not a scheduled-logon capability test.

## Bounded host inventory observed 2026-09-10

The sandbox initially rejected `Get-ScheduledTask` and the process/service CIM
queries with `Access denied`. The same narrowly scoped read-only inventory
succeeded outside the sandbox. Windows Task Scheduler was running and accepted
a COM connection. The current principal was `JAMES\james`, without an elevated
administrator token. Seven tasks existed in the root task folder. No existing
V18 scheduled owner, MLB worker, or MLB-specific service was found in the bounded
name/action inventory. This does not claim a broad host audit.

The separate existing task `\ASP Backend 8010` was running as `james`, S4U,
Highest privilege, with a startup trigger. Its action points to
`C:\Users\james\ai-sports-predictor\scripts\asp-backend-supervisor.ps1`, working
directory `C:\Users\james\ai-sports-predictor`, and port 8010. Relevant supervisor
statements show a restart/backoff loop launching the AISP venv's
`uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8010`.
Port 8010 was listening; port 8018 was not. The PostgreSQL service
`postgresql-x64-16` was running with automatic startup as
`NT AUTHORITY\NetworkService`, and port 5432 was listening.

These are existing dependency owners, not components installed or modified by
this work. Their configuration supports startup, but metadata alone does not
prove ingestion freshness, health after a future restart, or availability of
each source the publisher needs. The research publisher must report unavailable
dependencies honestly and retry on its own later ticks. It must not start,
restart, reconfigure, or write to AISP to repair a missing dependency.

At the time this inventory was written, this agent had not registered or started
the new V18 task. S4U registration permissions, scheduled network/database
capabilities, and logout/reboot survival still required actual execution evidence.
If registration returns `Access denied` or a batch-logon/policy error, preserve
the exact Windows error in the operational report. Do not substitute SYSTEM,
store a password, change security policy, or report the task as installed.

### Actual installation result

Root attempted the reviewed current-user S4U/Limited registration. Windows returned `Access is denied`; no V18 task was installed. `-Mode Prepare` now writes/verifies the deployment manifest without attempting registration, allowing manual verification while awaiting administrator action. Run the documented `-Mode Install` command in an Administrator PowerShell **as James**, preserving S4U/Limited and the intended user SID. An administrator must then start the registered task and inspect its real task/runner receipts. Do not claim scheduled-logon or reboot testing from the manual launcher checks.

The launcher supports `-RunNow` for one manual bounded verification and marks that invocation separately; the actual task action uses `-ScheduledInvocation` and normal persisted cadence. This does not bypass game cutoffs or per-game cooldowns.

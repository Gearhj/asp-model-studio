# ASP Model Studio — Production Architecture Plan (Fable 5.1 audit)

Audit base `bff19a8a657bc96dea0469fad481acdcb4234386`. This plan is derived from the measured behaviour of the current build
(see `ASP_MODEL_STUDIO_FABLE51_CAPACITY_REPORT.md`) and the findings register. It is a plan, not an implementation; nothing
here was applied during the audit.

## 0. What the current build actually is

- One `uvicorn` process (single worker) running FastAPI with synchronous handlers on the default AnyIO thread pool (40 threads).
- Two SQLite files (persistence, security), WAL mode, `busy_timeout` 10 s, one connection per operation.
- Background model work executes **inside the API process** through a `ThreadPoolExecutor(max_workers=1)` per job family
  (model development, executable artifact). One coordinator thread fans out candidate fits with bounded native workers.
- Every scientific authority lives on the local filesystem: `.runtime/asp-model-studio/*`, `C:\Users\james\asp-data-staging\*`
  (hard-coded absolute defaults), `C:\Users\james\asp-model-exchange`.
- The Model Laboratory and every downstream stage are hard-bound to one project id (`asp-mtddc6pw`) and to expected checksums of
  that project's policies, feature sets, split, candidate, and OOF evidence.
- No reverse proxy, TLS, rate limiting, secret manager, backup schedule, metrics, tracing, or alerting exist.

## 1. Tier definitions and verdict per tier

| Tier | Safe registered users | Safe interactive concurrency | Safe simultaneous heavy jobs | Required infrastructure | Primary bottleneck | Blocking findings | Recovery expectation | Operational complexity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Tier 0 — Current local research** (one scientist, one workstation) | 1 (plus trusted collaborators on the same machine) | 1–3 | 1 (single in-process worker; a second job on the same project is refused, other projects cannot run at all) | Nothing beyond `scripts/start-asp-model-studio.ps1`; manual backups via the SQLite backup API | Single Python process (GIL + CPU); 4-core i7-4790 | F-002 (V2 authorities in a disposable worktree), F-005 (script actors writing authoritative rows), F-040 (no backups) | Manual: restart process; jobs surface as INTERRUPTED; scientist re-runs | Low |
| **Tier 1 — Private alpha** (≤10 invited users, one small team, private network) | 10 | 5 | 1 heavy + queued | Same process model but: F-001 fixed, F-004/F-006 fixed, nightly SQLite backup via backup API + off-box copy, TLS-terminating reverse proxy, `ATLAS_HOSTED_MODE=true` with real secrets, per-IP login throttling, integrity check at startup, staging roots made configurable and content-pinned | Still one process; Model Lab still single-project unless F-003 is fixed | F-001 (P0), F-003 (if more than one project must model), F-013, F-020 | Restart with orphan reconciliation (tested: INTERRUPTED + receipts preserved); restore from nightly backup (tested path) | Low–medium |
| **Tier 2 — Controlled beta** (100–500 registered, 25 concurrent, 4 heavy jobs + queue) | 100–500 | 25 (measured headroom: see capacity report) | 4 across projects **only after** the Model Lab is generalized (F-003) and jobs move to dedicated workers | PostgreSQL; 2–4 API workers behind a reverse proxy; dedicated model-worker processes (one container/process per job slot, 4 slots) fed by a durable queue (Redis Streams, RabbitMQ, or a Postgres-backed queue such as `pgqueuer`); object storage or a shared content-addressed volume for artifacts; Redis for sessions/rate limits; secrets manager; PITR backups; metrics + tracing + alerts; CI gates | Worker CPU/RAM per fit (a 234-feature XGBoost 5-fold fit occupied ~1.3 GB RSS and 60+ minutes on this workstation); SQLite write serialization if not migrated | F-001, F-002, F-003, F-004, F-005, F-006, F-010, F-013, F-020, F-022, F-024, F-040, data-rights blockers | Automated restart of workers with job re-queue; RPO ≤ 15 min (PITR), RTO ≤ 1 h | Medium |
| **Tier 3 — Enterprise / public multi-tenant** | 1,000s | 100+ | 10–50 across many projects | Everything in Tier 2 plus: tenant-scoped object storage prefixes, per-tenant quotas/admission control, container sandboxing for any deserialization, SSO/OIDC, audit log shipped to immutable storage (WORM), key management/encryption at rest, WAF, DR region | Artifact storage throughput and worker fleet cost; governance review throughput | All Tier 2 items plus source-rights resolution (Statcast commercial terms) and a real password-reset/MFA flow | Multi-AZ; RPO ≤ 5 min; RTO ≤ 30 min | High |
| **Tier 4 — Horizontally scaled multi-sport platform** | 10,000s | 1,000+ | Elastic (autoscaled worker pools per sport) | Kubernetes or equivalent; per-sport worker images; feature-store/lakehouse for Gold objects; event bus; multi-region object storage; policy engine for source rights | Data-rights and evidence lineage at scale; cost | NFL/NBA/UFC workflows are RESEARCH_ONLY/PLANNED today; sport namespaces exist only in manifests | Automated failover | Very high |

**Recommended deployment tier today: Tier 0 (private research), moving to Tier 1 once the P0/P1 items in section A of the
repair plan land.** The build is not safe for controlled beta.

## 2. Requirements assessment (component by component)

### PostgreSQL
- Needed at Tier 2. SQLite is correct for Tier 0/1 (single process). Migration path: the schema is already expressed as SQL
  migrations with `BEGIN IMMEDIATE` serialization; triggers implementing immutability (verified: policy/spec/feature-set/split
  versions) must be ported as Postgres triggers. Run records, projects, and audit tables need the same append-only protection they
  lack today (F-024).
- JSON columns (`*_json`) map to `jsonb`. Content checksums stay application-side.
- Connection pooling (pgbouncer) because the code opens one connection per operation.

### API workers
- Tier 1: 1 uvicorn worker with `--workers 2` is unsafe today because in-process state (`DATASTORE`, `RESULTS`, job futures,
  `_profile_gold` cache, interprocess locks) assumes one process; the job coordinator uses PID-based orphan detection that does
  work across processes, but session checkpoints and in-memory caches do not. Multi-worker requires: Redis session/cache, removal
  of process-local job registries, and cache keys that include content hashes.
- Tier 2: 2–4 workers behind a reverse proxy after the above.

### Dedicated model workers
- Required for any tier that promises concurrent heavy jobs. The current coordinator (`stage3_model_jobs._execute_job`) is a clean
  seam: it takes a database path, job id, project id, actor, and plan; it can be lifted into a worker entry point. Progress
  heartbeats already go through the DB under an interprocess lock.
- Worker must run with a read-only mount of Gold/companion objects and a write-only content-addressed artifact bucket.

### Durable job queue and admission control
- Today: one active job per project, one worker per process, no cross-project queue, no priority, no quota.
- Tier 2: queue with per-user and per-project quotas (e.g., 1 active + 2 queued per user; 4 global slots), admission check on
  `totalFits` and `computeIntensity` (both already computed in the plan), and a visible position in queue.

### Distributed locks
- Interprocess file locks (`server/sports_cockpit/interprocess_lock.py`) are adequate for one host. Tier 2 needs Redis/Postgres
  advisory locks for job claims and artifact publication.

### Worker isolation / sandboxing
- `joblib.load` executes pickle. The loader verifies every member hash before load (verified), which is the right control, but the
  API process still performs the load. Tier 2: deserialize only in a worker with no DB credentials and no network; Tier 3:
  container per job.
- User Python execution stays disabled (`ATLAS_ENABLE_PYTHON_RUN=0`; hosted mode blocks it).

### Object storage and artifact lifecycle
- Content-addressed directories with manifest-last publication (verified atomic) translate directly to object keys
  `sha256/<digest>/...`. Add: retention policy for `staging/`, garbage collection of unreferenced objects, and lifecycle rules for
  OOF parquet (71 MB per artifact).
- Move the V2 prior store from a worktree-relative default to a governed root (F-002).

### Redis (or equivalent)
- Sessions (currently SQLite rows), login throttling, per-user rate limits, cache for Stage 2 profiles keyed by
  `(manifest sha, partition shas)`, and the job queue if not Postgres-backed.

### Session storage
- Keep opaque server-side sessions (good). Add: idle timeout, maximum concurrent sessions per user, revoke-all-on-password-change,
  and rotation on privilege change (already revokes on role change).

### Reverse proxy and TLS
- Required from Tier 1. Terminate TLS, set HSTS, forward `X-Forwarded-For` only from the trusted proxy list the code already
  supports (`ATLAS_TRUSTED_PROXY_IPS`), and enforce `ATLAS_COOKIE_SECURE=true`.

### Rate limiting
- None exists (F-020). Tier 1: per-IP login throttle at the proxy; Tier 2: per-user API quotas and per-route limits on expensive
  reads (`stage2-data-review`, `stage3-eda/query`, `split-balance/automatic`).

### Secret management
- Session secret is generated per start by the launcher (fine for Tier 0) and defaults to a known string in code otherwise.
  Tier 1+: inject `ATLAS_SESSION_SECRET` and DB credentials from a secret store; rotate; never rely on `.env.local`.

### Encryption
- At rest: OS/volume encryption at Tier 1; KMS-managed keys at Tier 3. In transit: TLS from Tier 1.

### Backup and point-in-time recovery
- Today: no scheduled backup; naive file copy of a WAL database loses pending writes (demonstrated). Tier 0/1: nightly
  `sqlite3.Connection.backup()` plus WAL checkpoint, copied off-box, restore drill monthly (the restore path was verified).
  Tier 2: Postgres PITR with base backups + WAL archiving; artifact bucket versioning.

### Observability
- Add structured request logs with user/project ids, Prometheus metrics (request latency by route, job queue depth, fit duration,
  DB busy errors), OpenTelemetry traces across API→worker, and alerts on job INTERRUPTED rate, 5xx rate, lock timeouts.

### CI/CD, deployment gates, rollback
- Gate on: full backend suite (with the environment-dependent and stale-legacy failures classified), TypeScript build,
  `npm audit`/`pip-audit` thresholds, secret scan, migration dry-run against a restored backup, and the leakage certification
  tests (`tests/sports_stage3_*`). Blue/green deploy with schema-compatible migrations; rollback = previous image + PITR if needed.

### Disaster recovery
- Tier 2: documented RPO/RTO, quarterly restore drill, artifact bucket replication, and a runbook for orphaned-job reconciliation
  (the code already reconciles on read).

## 3. Sequencing

1. **Now (before any second user):** fix F-001 (self-grant), F-004 (ACL read), F-006 (cockpit scoping); move the V2 store into
   the governed runtime root and re-verify the pointer (F-002); stop script actors from writing authoritative rows (F-005);
   scheduled backups (F-040).
2. **Private alpha:** hosted-mode configuration with real secrets and TLS; login throttling; startup integrity check; audit/run
   ledger immutability triggers (F-024); configurable staging roots (F-012); Stage 2 cache keyed by partition hashes or TTL (F-010).
3. **Controlled beta:** generalize the Model Laboratory beyond `asp-mtddc6pw` (F-003) — this is the single largest engineering
   item; PostgreSQL; worker separation; durable queue with quotas; observability; data-rights review outcome recorded per source.
4. **Enterprise:** SSO, per-tenant storage isolation, WORM audit, sandboxed deserialization, DR.

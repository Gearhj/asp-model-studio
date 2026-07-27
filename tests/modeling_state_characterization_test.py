"""Stage 1 + Stage 2A + Stage 2B + Stage 3 + Stage 4 + Stage 6 (ATLAS_MODELING_STATE_ISOLATION_PLAN.md)
-- tests for the Predictive Modeling in-memory state architecture.

Stage 1 (characterization, tests-only) proved that DATASTORE/RESULTS/
TRAINING_JOBS resolved to a single shared "anonymous" scope (or, for
TRAINING_JOBS, no scope check at all) for every authenticated HTTP request.
Stage 2A fixed that for identity (ActiveUserContextMiddleware). Stage 2B
added project isolation to DATASTORE. Stage 3 did the same for RESULTS.
Stage 4 did the same for TRAINING_JOBS. Stage 6 (this update, there is no
Stage 5 in this file -- TRAINING_JOBS authorization WAS Stage 5's original
target in the plan document, delivered as part of Stage 4 above) fixes the
one remaining gap all three shared: restart/checkpoint restoration used to
collapse every user's and every project's state into one shared bucket.

=====================================================================
STAGE 2A FIX -- (unchanged from the prior version of this file)
=====================================================================

Root cause (confirmed in Stage 1): `require_user()` is a FastAPI
*dependency* (`Depends(require_user)`). FastAPI/Starlette resolves each
sync dependency via its own `run_in_threadpool` call, each with an
independently-copied `contextvars.Context`; `require_user()`'s
`set_active_user(user)` mutated only its own call's private copy, discarded
when the dependency returned -- never visible to the route handler body's
own, separate `run_in_threadpool` call.

Fix implemented in `server/security/security_store.py`: a shared,
side-effect-free `_resolve_authenticated_user()` helper, and
`ActiveUserContextMiddleware`, which sets `ACTIVE_USER` directly inside its
own `dispatch()` coroutine -- the request's own ambient async task, not a
nested `run_in_threadpool` call -- *before* routing/dependency resolution
runs. Every `run_in_threadpool` call downstream of that point copies its
context from this already-mutated ambient context.

=====================================================================
STAGE 2B FIX -- READ THIS FIRST
=====================================================================

Stage 2A fixed the USER half of DATASTORE's scope key. It did nothing for
the PROJECT half: `SetSamplePayload` and every other affected request model
had no `project_id` field at all, so a single user's two projects still
collided in one DATASTORE instance (`MissingProjectIsolationTests`, Stage
2A's KNOWN LIMITATION).

Fix implemented across three layers:

  1. `server/core/modeling_scope.py` (new): `ACTIVE_PROJECT_ID`, a second
     ContextVar alongside `ACTIVE_USER`, plus `authorize_modeling_scope
     (user, project_id, permission)` -- validates `project_id` is
     non-blank, looks the project up via the persistence service (404 if
     it doesn't exist), authorizes it via the EXISTING
     `SharingService.check_permission` (the same mechanism FND-001/FND-002
     already established -- no second authorization system), and only then
     calls `set_active_project_id(project_id)`.

     Why setting a ContextVar HERE works, unlike a `Depends()`-based
     attempt (which would hit the exact Stage 2A propagation gap again):
     `authorize_modeling_scope(...)` is called as the FIRST LINE of each
     affected route handler's own body -- not a separate FastAPI
     dependency. Everything that route handler calls afterward (the
     preprocessing/feature/split SERVICE functions, all left completely
     unmodified) is an ordinary, synchronous, nested Python function call
     within that SAME already-running `run_in_threadpool` call, so the
     ContextVar mutation is visible to all of them. Verified empirically
     with an isolated repro before use -- see the delivery report.

  2. `server/core/dataset_store.py`: `_DATASTORES` re-keyed from a bare
     `user_id: str` to an explicit `(user_id, project_id): Tuple[str, str]`
     tuple (never a concatenated string -- no delimiter-collision risk).
     `_scope_key()` now also reads `modeling_scope.active_project_id()`,
     falling back to the sentinel `UNSCOPED_PROJECT = "unscoped"` ONLY for
     callers that never went through `authorize_modeling_scope` at all
     (direct script/service-layer calls, e.g.
     tests/predictive_modeling_repair_test.py, and the still-unmodified
     checkpoint-restore path). A real HTTP request to an affected endpoint
     can never reach DATASTORE with this fallback: authorize_modeling_scope
     rejects it (400/403/404) first.

  3. Every DATASTORE-touching router (data acquisition, outliers, missing
     values, quality/feature profiling, bureau detection, feature
     engineering, balance & split, EDA, dataset-library activation) gained
     a required `project_id` field on its request model (or a required
     `project_id` query param for GET/DELETE endpoints) and a call to
     `authorize_modeling_scope(...)` as the first line of its handler.
     RESULTS, TRAINING_JOBS, and checkpoint restoration were deliberately
     NOT touched -- see "EXPECTED LIMITATIONS" below.

DECISION -- collaborator policy for DATASTORE working state: OPTION A,
user-and-project-private, even among authorized collaborators, per the
architecture plan's recommendation and this task's explicit instruction.
The scope key is `(user_id, project_id)`, not `project_id` alone: an
authorized collaborator passes `authorize_modeling_scope`'s check (no 403)
but still resolves their OWN, independent, initially-empty DATASTORE
instance for that project -- never the other collaborator's actual
in-progress draft data. See `ProjectAuthorizationForDatastoreTests` for the
tests proving this, and its class docstring for the full rationale.

IMPORTANT, NARROW EXCEPTION -- training's DATASTORE connectivity: TRAINING_
JOBS/RESULTS were NOT project-scoped or authorized in this stage (explicitly
out of scope). But `server/training/training_job_service.py`'s job-creation
path still reads DATASTORE (the governed split, feature manifest) via the
now-project-scoped ambient proxy, unmodified. Without SOME way to tell it
which project's DATASTORE scope to read, Stage 2B's DATASTORE re-keying
would silently orphan training from every dataset a real request had just
prepared. `server/training/trainer_router.py` therefore gained a single,
narrow, NON-authorizing call, `set_active_project_id(request.project_id or
None)`, at the top of `create_training_job`/`run_training_preflight`/the
sync `train_models` handler -- connectivity only, deliberately with no
SharingService check and no rejection of blank project_id, so that
"TRAINING_JOBS get/cancel authorization remains unresolved" (an explicitly
required unchanged limitation) stays literally true. See
`BackgroundContextTests`/`TrainingJobIsolationTests` for what this does and
does not change.

=====================================================================
STAGE 3 FIX -- READ THIS FIRST
=====================================================================

Stage 2B fixed DATASTORE (working/draft preprocessing state). It
deliberately left RESULTS (training summaries, model artifacts, evaluation/
interpretation/scoring outputs) purely user-scoped, not project-aware at
all -- a single user's two projects' training results collided in one
RESULTS instance, and (per the old `CollaboratorVisibilityTests`) an
authorized collaborator had no way to see a project's own committed result.

Fix, mechanically identical to Stage 2B's, applied to RESULTS instead of
DATASTORE:

  1. `server/core/result_store.py`: `_RESULT_STORES` re-keyed from a bare
     `user_id: str` to the SAME `(user_id, project_id): Tuple[str, str]`
     shape DATASTORE already uses, reading the SAME `ACTIVE_PROJECT_ID`
     ContextVar via the SAME `UNSCOPED_PROJECT` sentinel (re-exported from
     `dataset_store.py` so both stores share one literal, not two).

  2. Every RESULTS-touching router gained a required `project_id` and an
     `authorize_modeling_scope(...)` call, exactly like Stage 2B:
     `server/training/trainer_router.py`'s `/train/last` and
     `/models/availability`, and all 22 endpoints in
     `server/evaluation/eval_router.py` (`/eval/*`, `/interpretation/*`,
     `/model/save_final`, `/model/final/status`, `/model/export`,
     `/score/upload`, `/score/development-split`).

  3. No code changes were needed in `metadata_router.py`, `dataset_router.py`,
     `session_checkpoint.py`, `trainer_service.py`, or
     `training_job_service.py`: every RESULTS write in those files already
     runs (a) on a request thread where `authorize_modeling_scope` had
     already set `ACTIVE_PROJECT_ID` earlier in the SAME handler (the
     `RESULTS.clear_model_artifacts()` calls in `metadata_router.py`/
     `dataset_router.py`, and `trainer_service.py`'s writes from the
     synchronous `/model/train` endpoint), or (b) through a `ResultStore`
     INSTANCE explicitly captured on the request thread and carried across
     the background-thread boundary (`training_job_service.py`'s
     `job["_result_store"] = RESULTS.current()`, captured at job-creation
     time, used by the background thread at completion time) -- this was
     already the established pattern for surviving the "raw threads don't
     inherit ContextVars" limitation (`BackgroundContextTests`), and it
     transparently carries the correct (user, project) scope through
     unmodified.

DECISION -- collaborator policy for RESULTS: OPTION A, user-and-project-
private, SAME as DATASTORE, for reasons specific to RESULTS (this required a
real decision, not just applying Stage 2B's precedent by default):

    - The task's own goal is "eliminate cross-user and cross-project
      COLLISIONS," a correctness fix. Re-keying RESULTS to `project_id`
      alone (dropping user_id, making it genuinely project-shared) would
      trade today's cross-project collision bug for a NEW collaborator-vs-
      collaborator collision: two authorized collaborators training on the
      same project would silently overwrite each other's view of "the last
      result," which is a regression relative to today's per-user isolation,
      not an improvement.
    - RESULTS remains a purely in-memory, per-process cache -- there is no
      existing durable, versioned, project-scoped artifact store behind it
      for multiple collaborators to safely read/write concurrently. Turning
      it into a shared mutable resource without that underlying durability
      would be building a NEW, undesigned collaboration feature under the
      banner of a scoping fix.
    - The instruction governing this decision ("if committed project
      artifacts are intended to be shared with collaborators, implement
      that DELIBERATELY through the existing project authorization and
      PERSISTENCE architecture") describes a materially larger feature --
      real persisted, versioned, jointly-readable committed artifacts --
      than widening an in-memory cache's key. That remains open, undesigned
      future work, not something this stage silently backs into.
    - This also keeps RESULTS structurally consistent with requirement #3's
      own suggested shape, `Tuple[user_id, project_id]`, which IS Option
      A's key -- Option B would have meant deliberately NOT using that
      shape for RESULTS specifically.

Consequence: `CollaboratorVisibilityTests` (renamed `ResultsCollaboratorPolicyTests`)
now documents Option A as INTENDED, authorized, tested behavior -- not a gap
awaiting a later stage. Its `@unittest.expectedFailure` migration-target
test (which encoded the OPPOSITE decision, Option B) is retired: keeping a
test asserting behavior this stage deliberately chose not to build would
misrepresent an open design question as still-pending, when it has now been
decided. See that class's docstring for the full un-abridged reasoning.

=====================================================================
STAGE 4 FIX -- READ THIS FIRST
=====================================================================

Stage 4 does for TRAINING_JOBS what Stages 2B/3 did for DATASTORE/RESULTS,
with one structural difference: TRAINING_JOBS is not "one instance per
(user, project)" the way DATASTORE/RESULTS are -- many jobs can exist per
(user, project) over time, and each job is ALSO addressed directly by a
globally-unique `job_id` in its own URL (`/model/train/jobs/{job_id}`).

Fix:

  1. `server/training/training_job_service.py`: `_jobs` stays keyed by
     `job_id` (re-keying it by (user_id, project_id) would make direct
     job_id lookups ambiguous). Every job record now carries explicit,
     request-thread-captured `owner_user_id` and `project_id` fields (not
     derived from ambient context at read time -- set once, at creation).
     A NEW, separately structured index, `_project_job_ids: Dict[Tuple[str,
     str], list[str]]` (an explicit tuple key, never a concatenated
     string), maps (owner_user_id, project_id) -> ordered job_ids, used for
     project-scoped listing (`active()`). Every accessor that takes a
     job_id (`get`, `cancel`) now ALSO requires the caller's own
     (owner_user_id, project_id) and returns None unless the job's own
     recorded owner_user_id AND project_id both match -- authorization is
     NEVER inferred from job_id possession alone. A job_id that exists but
     belongs to someone else, or to a different project, is treated
     identically to a job_id that does not exist: both return None from the
     service layer, both surface as 404 at the router. This defeats guessing/
     enumeration: a syntactically correct job_id for the wrong owner or
     project is exactly as useless as a random string.

  2. `server/training/trainer_router.py`: every job-touching endpoint
     (`/model/train/jobs` POST, `/model/train/preflight` POST,
     `/model/train/jobs/active` GET, `/model/train/jobs/{job_id}` GET,
     `/model/train/jobs/{job_id}/cancel` POST, and the otherwise-dead
     `/model/train` POST) now requires `project_id` and calls
     `authorize_modeling_scope(user, project_id, permission)` -- view for
     reads/status/preflight, edit for creation/cancellation. This RETIRES
     the Stage 2B/3 temporary, non-authorizing `_connect_datastore_scope`/
     raw `set_active_project_id(...)` workaround entirely (grep confirms
     zero remaining call sites outside modeling_scope.py itself) --
     `authorize_modeling_scope` both authorizes AND sets the same ContextVar
     the old workaround set as a side effect, so DATASTORE connectivity is
     preserved with no separate/duplicate mechanism left behind.

  3. `server/training/training_job_types.py`: `TrainingJobRequest.
     project_id` changed from an optional, defaulted `str = ""` to a
     required field -- missing project_id now fails Pydantic validation
     (422) on every endpoint that accepts a `TrainingJobRequest` body.

STATUS CODE MAPPING for job-specific access (distinct from, but consistent
with, `authorize_modeling_scope`'s own 400/403/404 for the PROJECT-level
check that always runs first):

  - No project access at all (stranger) -> 403, from authorize_modeling_
    scope, before any job lookup is attempted.
  - Authorized for the project, but this specific job_id belongs to a
    different owner (e.g. an authorized collaborator peeking at another
    collaborator's private job) -> 404, from the service-layer ownership
    check -- deliberately indistinguishable from "this job_id does not
    exist," so an authorized-but-uninvolved party cannot even confirm
    another user's job exists in a project they both have access to.
  - Job_id from a different project entirely, regardless of who "owns" it
    -> 404, same mechanism (job["project_id"] mismatch).

BACKGROUND-THREAD SCOPE: TRAINING_JOBS' background thread
(`TrainingJobService._run`, a bare `threading.Thread`) does NOT inherit
`ACTIVE_USER`/`ACTIVE_PROJECT_ID` ContextVars -- confirmed unchanged by
BackgroundContextTests.test_bare_thread_does_not_inherit_active_user_context.
This was NEVER worked around by contextvars propagation, in this stage or
any prior one: `create()` reads DATASTORE and captures a RESULTS instance
entirely on the REQUEST thread (where authorize_modeling_scope's ContextVar
mutation IS visible) BEFORE the background thread starts, passing
X_train/X_test/y_train/y_test as plain function arguments and the captured
RESULTS instance as a job-record field (`job["_result_store"]`). Stage 4
adds `owner_user_id`/`project_id` to that SAME already-proven pattern --
explicit, request-thread-captured, immutable-after-creation job-record
fields, not a new propagation mechanism. See training_job_service.py's
module-level comment and TrainingJobProjectIsolationTests below for the
tests proving this explicit-capture strategy is sufficient.

DECISION -- collaborator policy for TRAINING_JOBS: OPTION A, same as
DATASTORE/RESULTS, per this stage's own explicit instruction ("use the
existing Option A policy unless a durable shared-model architecture already
exists" -- it does not). An authorized collaborator passes project-level
authorization (no 403 entering the project) but cannot read, cancel, or
otherwise access another collaborator's specific job (404, per the status-
code mapping above) -- private in-progress (and completed/failed/
cancelled) training jobs remain user-and-project-private. A collaborator
CAN create their own, independent job in a shared project (an "edit"-
permission action, exactly like DATASTORE/RESULTS's collaborator-write
tests) -- their own job is entirely their own, tracked under their own
(owner_user_id, project_id) entry in `_project_job_ids`, invisible to and
unaffected by the original owner's jobs. Committed shared artifacts
(if ever wanted) remain out of scope here, per this stage's own
instruction to use "the durable project artifact layer rather than
widening an in-memory job cache" -- consistent with Stage 3's identical
RESULTS decision.

=====================================================================
STAGE 6 FIX -- READ THIS FIRST
=====================================================================

ROOT CAUSE of the restart scope collapse: the pre-Stage-6 checkpoint
(server/core/session_checkpoint.py) was a SINGLE FLAT SNAPSHOT --
{"dataset": {...}, "results": {...}} -- of whichever ONE (user_id,
project_id) scope happened to be AMBIENT at the moment save_checkpoint()
was called, via DATASTORE/RESULTS's ambient proxies. Every one of the ~15
router call sites that trigger a save overwrote the ENTIRE file with only
its own caller's scope, discarding whatever any other user/project had
previously saved. At startup, load_checkpoint() ran from
@app.on_event("startup"), before any HTTP request had ever been handled,
so active_user()/active_project_id() were always unset -- the restored
data was written back into the shared ("anonymous", UNSCOPED_PROJECT)
sentinel scope regardless of who had actually saved it. Ownership was
destroyed, not merely relabeled.

FIX: save_checkpoint()/load_checkpoint() no longer touch the AMBIENT
DATASTORE/RESULTS proxies at all.

  1. save_checkpoint() iterates EVERY (user_id, project_id) entry
     currently resident in dataset_store_module._DATASTORES and
     result_store_module._RESULT_STORES and serializes EACH as its own
     explicit, structured record: {"owner_user_id": ..., "project_id":
     ..., "dataset": {...}} (or "results": {...}) -- a full multi-scope
     snapshot on every save. None of the ~15 call sites changed at all;
     they still just call save_checkpoint() with no arguments.

  2. load_checkpoint() reads each record's own explicit owner_user_id/
     project_id fields and calls get_scoped_dataset_store((user_id,
     project_id))/get_scoped_result_store((user_id, project_id)) with that
     EXPLICIT tuple -- bypassing ambient/ContextVar resolution entirely.
     Startup restoration therefore needs, and uses, no authenticated HTTP
     request and no ambient ContextVar.

SCHEMA: server/core/session_checkpoint.py's CHECKPOINT_SCHEMA_VERSION = 2.
A checkpoint with no "schema_version" key at all is the pre-Stage-6 LEGACY
format.

TRAINING_JOBS ARCHITECTURE DECISION: TRAINING_JOBS is NOT included in the
checkpoint -- deliberate, not an oversight. A job's in-memory bookkeeping
(per-model transition history, its threading.Event, ThreadPoolExecutor
state) cannot mean anything after a real restart -- the background thread
computing it is gone, so persisting a "running" job and reporting it as
such afterward would be an outright lie. Not persisting it means it simply
does not exist after restart, which satisfies "stale running jobs must not
be falsely resumed" by construction. A completed job's only durable VALUE
-- the fitted models' ranked metrics/metadata -- is already written into
RESULTS by TrainingJobService._finalize(), which Stage 6 DOES checkpoint;
persisting the TRAINING_JOBS record too would duplicate that same
information with no reconciliation path if the two ever disagreed. See
session_checkpoint.py's module docstring for the complete reasoning, and
TrainingJobCheckpointPolicyTests below for the tests proving this.

LEGACY CHECKPOINT HANDLING: loaded ONLY into the sentinel LEGACY_SCOPE =
("anonymous", UNSCOPED_PROJECT) -- the same non-HTTP-reachable scope
non-HTTP callers already resolve to (tests/predictive_modeling_repair_test.py,
etc.), never into any real user/project. This is the exact scope every
KNOWN LIMITATION test through Stage 4 already proved restart landed in by
accident; Stage 6 makes it happen on purpose, only for genuinely legacy
files, so pre-existing local development checkpoints are not silently
destroyed but also never leak into a real authenticated project.

CORRUPT/MALFORMED/UNSUPPORTED-VERSION CHECKPOINTS: load_checkpoint() fails
safe -- logs a warning, restores NOTHING, and never writes to the
checkpoint file itself (it has no write path at all), so a corrupt file is
left completely intact for inspection. An individual malformed SCOPE
RECORD within an otherwise-valid file is skipped with a warning rather
than aborting the whole restoration.

ATOMIC WRITES: unchanged in spirit from Stages 1-5 -- write the full
payload to a uniquely-named temp file in the same directory, then
Path.replace() (an atomic rename on POSIX and Windows) onto the live
checkpoint. A failure at any point before the replace leaves the previous
good checkpoint completely untouched and cleans up the temp file.

COLLABORATOR POLICY (unchanged, Option A): restoring scope-by-scope from
explicit (user_id, project_id) records cannot itself grant a collaborator
visibility into another user's restored draft state -- every restored
record lands in its own private scope, exactly as saved.

FRESH-PROCESS VERIFICATION: per this stage's own requirement not to treat
"clear the in-memory dicts within the same test process" as equivalent to
a real restart, CheckpointSubprocessRestartTests spawns genuinely separate
Python subprocesses (fresh module-level state, not merely .clear()'d
dicts) for the core two-users-two-projects scenario, in addition to the
faster in-process simulated-restart tests used for the rest of this file's
edge cases (which remain valid for exercising the save/load LOGIC itself).

=====================================================================
CLASSIFICATION (read this before reading or changing any test below)
=====================================================================

PASSING BASELINE -- behaviors that are correct and MUST remain correct
through every later migration stage.

    - AuthenticationIdentityBaselineTests (all tests)
    - ExistingUserIsolationTests (all tests)
    - MissingProjectIsolationTests (all tests -- promoted in Stage 2B)
    - ProjectAuthorizationForDatastoreTests (all tests -- new in Stage 2B)
    - ResultsProjectIsolationTests (all tests -- new in Stage 3)
    - ResultsAuthorizationTests (all tests -- new in Stage 3)
    - ResultsCollaboratorPolicyTests (all tests -- new in Stage 3, formerly
      CollaboratorVisibilityTests; see that class's docstring)
    - TrainingJobIsolationTests (all tests -- promoted in Stage 4; see below)
    - TrainingJobProjectIsolationTests (all tests -- new in Stage 4)
    - BackgroundContextTests.test_two_users_training_jobs_no_longer_collide_after_active_user_fix
    - CheckpointRestoreTests (all tests -- promoted/rewritten in Stage 6; see below)
    - CheckpointMultiScopeRestartTests (all tests -- new in Stage 6)
    - CheckpointSubprocessRestartTests (all tests -- new in Stage 6)
    - CheckpointAtomicWriteTests (all tests -- new in Stage 6)
    - CheckpointCorruptionAndVersioningTests (all tests -- new in Stage 6)
    - TrainingJobCheckpointPolicyTests (all tests -- new in Stage 6)

KNOWN LIMITATIONS -- behaviors that remain broken, intentionally out of
scope for this entire migration series, each still proven by a PASSES-
TODAY bug-reproduction test paired with an `@unittest.expectedFailure`
companion:

    - BackgroundContextTests.test_bare_thread_does_not_inherit_active_user_context
      -> raw threading.Thread still does not inherit ANY ContextVar
      (neither ACTIVE_USER nor ACTIVE_PROJECT_ID) -> general-purpose, not
      specific to DATASTORE/RESULTS/TRAINING_JOBS/checkpointing, none of
      which depend on this propagation (see the "STAGE 4 FIX"/"STAGE 6
      FIX" sections above) -- no further stage in this plan targets it; it
      is a standing, accepted property of the threading/contextvars model.

Tests that changed classification in Stage 2B (promoted from KNOWN
LIMITATION to PASSING BASELINE, per this task's explicit instruction to
convert rather than delete):

    - MissingProjectIsolationTests.test_same_user_two_projects_no_longer_collide
      (renamed from ..._second_project_overwrites_first_projects_dataset,
      which proved the opposite) and
      test_two_browser_tabs_different_projects_no_longer_collide (renamed
      from ..._share_and_collide) -- this is the primary scenario Stage 2B
      exists to fix.
    - MissingProjectIsolationTests.test_returning_to_project_a_correctly_retrieves_project_as_own_state
      (`@unittest.expectedFailure` removed; renamed from
      ..._should_still_retrieve_project_as_own_state, rewritten to use real
      created projects -- the literal string project_ids the Stage 2A
      version used would now correctly 404, since projects must exist).

Tests that changed classification in Stage 3 (RESULTS project-scoping;
former CollaboratorVisibilityTests, renamed ResultsCollaboratorPolicyTests):

    - test_authorized_collaborator_currently_cannot_see_owners_committed_result
      is retained, renamed test_authorized_collaborator_gets_own_independent_results_scope,
      and PROMOTED from KNOWN LIMITATION to PASSING BASELINE: the same
      observable behavior (collaborator sees nothing of the owner's result)
      is now DELIBERATE Option-A privacy, proven alongside a full
      authorization check (the collaborator is correctly let PAST
      authorization, not merely denied), not an accidental side effect of
      RESULTS having no project awareness at all.
    - test_results_access_should_match_project_authorization_exactly
      (`@unittest.expectedFailure`, encoding Option B -- project-shared
      RESULTS) is RETIRED, not carried forward: Stage 3 deliberately chose
      Option A (see "STAGE 3 FIX" above), so this hypothesis is no longer
      an open migration target -- keeping it would misrepresent a decided
      question as still-pending. The class docstring documents the decision
      and its reasoning in full so this is a traceable removal, not a
      silent one.

Tests that changed classification in Stage 4 (TRAINING_JOBS project
isolation and authorization; TrainingJobIsolationTests):

    - test_unrelated_authenticated_user_can_currently_view_another_users_job
      is retained, renamed test_unrelated_user_is_denied_job_read_with_403,
      and PROMOTED from PASSES-TODAY bug reproduction to PASSING BASELINE:
      the stranger is now correctly rejected (403) before any job lookup.
    - test_unrelated_authenticated_user_can_currently_cancel_another_users_job
      is retained, renamed test_unrelated_user_is_denied_job_cancel_with_403,
      PROMOTED the same way, for the cancel path.
    - test_unrelated_user_should_be_denied_view_access_to_another_users_job
      and test_unrelated_user_should_be_denied_cancel_access_to_another_users_job
      (both `@unittest.expectedFailure`) are RETIRED, not carried forward
      separately: their exact desired-end-state assertions are now
      literally what the two promoted tests above assert and pass, so
      keeping both the bug-reproduction and the migration-target version of
      the same scenario would be redundant duplication, not additional
      characterization. The rename/promotion above is the traceable record
      of this merge.
    - test_job_record_has_project_id_but_no_verified_owner_identity_field
      is retained, renamed test_job_record_has_explicit_owner_and_project_fields,
      and INVERTED (not merely promoted): it now asserts the OPPOSITE of
      its old finding, since job records gained a real, request-verified
      `owner_user_id` field this stage added specifically to fix the gap
      that test used to document.

Tests that changed classification in Stage 6 (checkpoint/restart project
isolation; CheckpointRestoreTests):

    - test_checkpoint_save_is_a_single_scope_last_writer_wins_file is
      retained, renamed test_checkpoint_save_preserves_all_scopes_not_just_the_last_writer,
      and INVERTED: it now asserts BOTH users' data survive a second save,
      since save_checkpoint() serializes every resident scope, not just
      the caller's own.
    - test_restart_reload_restores_into_anonymous_not_any_real_user is
      retained, renamed test_restart_reload_restores_into_each_users_own_real_scope,
      and INVERTED: it now asserts the restored data lands under the real
      user's own (user_id, project_id) scope, not the shared anonymous/
      unscoped bucket.
    - test_restart_should_restore_each_users_own_scope
      (`@unittest.expectedFailure`) is PROMOTED (decorator removed) exactly
      as originally written: its own scenario (no project context set
      during save) already resolved to (user_id, UNSCOPED_PROJECT), which
      IS "the user's own scope" for that narrow setup -- Stage 6 restores
      exactly the scope a record was saved under, so this assertion now
      holds for real, with no body changes needed.

No test in this file weakens an assertion to force a pass, and no test
represents current broken behavior as desirable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import uuid
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# server.security.security_store resolves its DB_PATH as a module-level
# constant at import time, so these environment variables must be set BEFORE
# server.main (or anything importing server.security.security_store) is
# imported for the first time in this process. Mirrors the isolation pattern
# already used by tests/persistence_authorization_test.py and
# tests/project_access_consolidation_test.py.
_TEST_DATA_ROOT = ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_modeling_state_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_modeling_state_persistence_{_RUN_ID}.db"
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"
# Stage 6.1: isolate this suite's checkpoint writes. The checkpoint is a
# full-snapshot last-writer-wins file; without this, any test class that does
# not monkeypatch CHECKPOINT_PATH would clobber the real dev backend's
# .runtime/workflow_checkpoint.json from a second process.
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_modeling_state_checkpoint_{_RUN_ID}.json"
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import (  # noqa: E402
    SESSION_COOKIE_NAME,
    active_user,
    init_security_store,
    set_active_user,
)

import server.core.dataset_store as dataset_store_module  # noqa: E402
import server.core.result_store as result_store_module  # noqa: E402
import server.core.session_checkpoint as session_checkpoint_module  # noqa: E402
import server.training.training_job_service as training_job_service_module  # noqa: E402
from server.core.dataset_store import get_scoped_dataset_store  # noqa: E402
from server.core.metadata_router import SetSamplePayload  # noqa: E402
from server.core.result_store import get_scoped_result_store  # noqa: E402
from server.splitting.split_service import split_service  # noqa: E402


def _cleanup_db_files() -> None:
    try:
        _CHECKPOINT_PATH.unlink(missing_ok=True)
    except PermissionError:
        pass
    for base in (_SECURITY_DB_PATH, _PERSISTENCE_DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(25):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 24:
                        time.sleep(0.2)


def _register(label: str) -> tuple[TestClient, str]:
    """Real HTTP registration -- mirrors tests/project_access_consolidation_test.py."""
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-modeling-state-test.local",
            "displayName": f"Modeling State Test {label} {suffix}",
            "password": "AuthModelingStateTestPass!",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()["user"]["userId"]


def _create_project(client: TestClient, name: str) -> str:
    """Real HTTP project creation via the FND-001 persistence routes --
    authorize_modeling_scope requires the project to genuinely exist."""
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _share_project(owner_client: TestClient, project_id: str, principal_id: str, permission_level: str) -> None:
    response = owner_client.post(
        f"/api/sharing/resources/project/{project_id}/share",
        json={"principalType": "user", "principalId": principal_id, "permissionLevel": permission_level},
    )
    assert response.status_code == 200, response.text


def _build_frame(rows: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "amount": [float(index % 37) for index in range(rows)],
            "velocity": [float((index * 7) % 19) for index in range(rows)],
            "target": [1 if index % 9 == 0 else 0 for index in range(rows)],
        }
    )


def _seed_governed_dataset_and_split(user_id: str, project_id: str, dataset_version: str, feature_manifest_version: str, split_id: str) -> None:
    """Populate a real, preflight-ready DATASTORE state directly into an
    EXPLICIT (user_id, project_id) scope (get_scoped_dataset_store bypasses
    contextvars entirely), mirroring the fixture pattern in
    tests/predictive_modeling_repair_test.py's configure_manifest()/
    create_governed_split().

    Used only by TrainingJobIsolationTests/BackgroundContextTests: training
    endpoints are deliberately NOT authorized in Stage 2B (see the module
    docstring's "IMPORTANT, NARROW EXCEPTION"), so `project_id` here can be
    any string the test chooses to use consistently -- it does not need to
    be a real, persisted project the way DATASTORE's OWN affected endpoints
    (which DO call authorize_modeling_scope) require.
    """
    store = get_scoped_dataset_store((user_id, project_id))
    store.reset_all()
    frame = _build_frame()
    store.set_raw(frame)
    store.set_target("target")
    store.meta["selected_columns"] = ["amount", "velocity"]
    store.meta["dataset_version"] = dataset_version
    store.meta["source"] = {"kind": "dataset_library", "datasetId": "ds-modeling-state-test"}
    store.meta["feature_manifest"] = {
        "manifest_version": feature_manifest_version,
        "dataset_version": dataset_version,
        "features": [
            {"feature_name": "amount", "origin": "original", "selected": True, "eligibility_status": "eligible"},
            {"feature_name": "velocity", "origin": "original", "selected": True, "eligibility_status": "eligible"},
        ],
        "pipeline_steps": [],
        "split_status": "not_created",
    }
    store.meta["split_status"] = "not_created"

    config = {
        "split_strategy": "holdout",
        "test_size": 0.2,
        "random_seed": 42,
        "stratify": True,
        "balance_method": "none",
        "minority_share": 0.5,
        "problem_type": "classification",
        "event_value": 1,
    }
    result = split_service.make_dev_split(frame, "target", ["amount", "velocity"], config)
    store.set_splits(result.X_train, result.X_test, result.y_train, result.y_test)
    store.meta["split_status"] = "current"
    store.meta["split_record"] = {
        "split_id": split_id,
        "dataset_version": dataset_version,
        "feature_manifest_version": feature_manifest_version,
        "selected_features": ["amount", "velocity"],
        "config": config,
    }


def _training_job_payload(project_id: str, dataset_version: str, feature_manifest_version: str, split_id: str, user_label: str, models: list | None = None) -> Dict[str, Any]:
    return {
        "models": list(models or ["logreg"]),
        "k_folds": 2,
        "max_parallel": 1,
        "calibrate": False,
        "target": "target",
        "event_value": 1,
        "non_event_value": 0,
        "problem_type": "classification",
        "dataset_version": dataset_version,
        "dataset_id": "ds-modeling-state-test",
        "feature_manifest_version": feature_manifest_version,
        "split_id": split_id,
        "project_id": project_id,
        "user": user_label,
    }


def _wait_for_terminal_job(client: TestClient, job_id: str, project_id: str, timeout: float = 30.0) -> Dict[str, Any]:
    """Bounded poll for job completion.

    TRAINING_JOBS exposes no public completion signal (its internal
    threading.Event, server/training/training_job_service.py's
    `_cancel_events`, only signals *cancellation*, not completion), so a
    bounded wait-for-condition loop is the smallest reliable mechanism
    available without reaching into private thread objects. This mirrors the
    already-reviewed `wait_for_job` pattern in
    tests/predictive_modeling_repair_test.py. This is not an arbitrary sleep:
    the loop exits as soon as the condition is observed, bounded by an
    explicit timeout that fails loudly if never reached.

    Stage 4: project_id is now required and authorized on GET
    /model/train/jobs/{job_id}.
    """
    terminal = {"complete", "failed", "cancelled", "interrupted"}
    deadline = time.time() + timeout
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        response = client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_id})
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("overall_status") in terminal:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Training job {job_id} did not reach a terminal state within {timeout}s: {last}")


class _DatastoreDictIsolationMixin:
    """Snapshot/restore the private _DATASTORES / _RESULT_STORES /
    TRAINING_JOBS module dicts around a test so class-local scope
    manipulation (especially the shared "anonymous"/"unscoped" bucket non-
    HTTP callers resolve to, and Stage 6's direct TRAINING_JOBS._jobs/
    _project_job_ids/_cancel_events manipulation for restart-policy tests)
    can never leak into other test classes in this file, regardless of
    execution order.
    """

    def _snapshot_global_stores(self) -> None:
        self._datastores_snapshot = dict(dataset_store_module._DATASTORES)
        self._result_stores_snapshot = dict(result_store_module._RESULT_STORES)
        self._training_jobs_snapshot = dict(training_job_service_module.TRAINING_JOBS._jobs)
        self._training_job_ids_snapshot = dict(training_job_service_module.TRAINING_JOBS._project_job_ids)
        self._training_cancel_events_snapshot = dict(training_job_service_module.TRAINING_JOBS._cancel_events)

    def _restore_global_stores(self) -> None:
        dataset_store_module._DATASTORES.clear()
        dataset_store_module._DATASTORES.update(self._datastores_snapshot)
        result_store_module._RESULT_STORES.clear()
        result_store_module._RESULT_STORES.update(self._result_stores_snapshot)
        training_job_service_module.TRAINING_JOBS._jobs.clear()
        training_job_service_module.TRAINING_JOBS._jobs.update(self._training_jobs_snapshot)
        training_job_service_module.TRAINING_JOBS._project_job_ids.clear()
        training_job_service_module.TRAINING_JOBS._project_job_ids.update(self._training_job_ids_snapshot)
        training_job_service_module.TRAINING_JOBS._cancel_events.clear()
        training_job_service_module.TRAINING_JOBS._cancel_events.update(self._training_cancel_events_snapshot)
        set_active_user(None)


class AuthenticationIdentityBaselineTests(unittest.TestCase):
    """PASSING BASELINE.

    require_user() (server/security/security_store.py:544-608) correctly
    resolves a distinct, real identity per authenticated session, from an
    unforgeable server-side session cookie. This is proven via
    GET /api/auth/me, whose handler receives that identity as an ordinary
    injected function parameter (`user: Dict = Depends(require_user)`), NOT
    through the ContextVar path DATASTORE/RESULTS rely on -- establishing
    precisely which half of the identity-propagation chain is sound (this
    class) and which half is broken (ExistingUserIsolationTests below).
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def test_me_endpoint_correctly_distinguishes_two_real_users(self) -> None:
        client_a, user_a_id = _register("auth-baseline-a")
        client_b, user_b_id = _register("auth-baseline-b")
        self.assertNotEqual(user_a_id, user_b_id)

        me_a = client_a.get("/api/auth/me")
        me_b = client_b.get("/api/auth/me")
        self.assertEqual(me_a.json()["user"]["userId"], user_a_id)
        self.assertEqual(me_b.json()["user"]["userId"], user_b_id)

        # Repeated/interleaved calls remain correctly attributed -- this is
        # not a one-shot coincidence.
        self.assertEqual(client_a.get("/api/auth/me").json()["user"]["userId"], user_a_id)
        self.assertEqual(client_b.get("/api/auth/me").json()["user"]["userId"], user_b_id)


class ExistingUserIsolationTests(unittest.TestCase):
    """PASSING BASELINE. See the module docstring's "STAGE 2A FIX" section
    for the user-isolation mechanism (`ActiveUserContextMiddleware`).

    Since Stage 2B, /api/data/set_sample requires project_id, so these tests
    now create a real project per user (each user working their OWN
    project), in addition to proving cross-user isolation -- covers this
    task's required scenario 3 ("different users, different projects").
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def test_store_class_correctly_isolates_by_explicit_scope_key(self) -> None:
        """PASSING BASELINE. The `_DATASTORES`/`_RESULT_STORES` dict-of-
        instances design (server/core/dataset_store.py) is sound in
        isolation: two distinct explicit (user_id, project_id) scope keys
        never share state. This isolates the defect Stage 1/2A/2B fixed to
        key POPULATION (how the key is derived from a live request), not
        the storage structure itself.
        """
        key_a = (f"scope-check-a-{uuid.uuid4().hex[:8]}", f"proj-a-{uuid.uuid4().hex[:8]}")
        key_b = (f"scope-check-b-{uuid.uuid4().hex[:8]}", f"proj-b-{uuid.uuid4().hex[:8]}")
        get_scoped_dataset_store(key_a).set_raw(pd.DataFrame({"marker": ["A"]}))
        get_scoped_dataset_store(key_b).set_raw(pd.DataFrame({"marker": ["B"]}))
        self.assertEqual(list(get_scoped_dataset_store(key_a).raw_df["marker"]), ["A"])
        self.assertEqual(list(get_scoped_dataset_store(key_b).raw_df["marker"]), ["B"])
        self.assertIsNot(get_scoped_dataset_store(key_a), get_scoped_dataset_store(key_b))

    def test_datastore_is_isolated_between_real_authenticated_users_over_http(self) -> None:
        """PASSING BASELINE. Two different, genuinely authenticated users,
        each working their OWN real project, each see only their own
        upload -- covers scenario 3 (different users, different projects).
        """
        client_a, user_a_id = _register("http-iso-a")
        client_b, user_b_id = _register("http-iso-b")
        self.assertNotEqual(user_a_id, user_b_id)
        project_a = _create_project(client_a, "HTTP Isolation Project A")
        project_b = _create_project(client_b, "HTTP Isolation Project B")

        set_a = client_a.post(
            "/api/data/set_sample",
            json={"project_id": project_a, "headers": ["amount", "target"], "rows": [{"amount": 111, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_a.status_code, 200, set_a.text)
        set_b = client_b.post(
            "/api/data/set_sample",
            json={"project_id": project_b, "headers": ["amount", "target"], "rows": [{"amount": 222, "target": 0}], "target": "target"},
        )
        self.assertEqual(set_b.status_code, 200, set_b.text)

        get_a = client_a.get("/api/data/get_sample", params={"project_id": project_a})
        get_b = client_b.get("/api/data/get_sample", params={"project_id": project_b})
        self.assertEqual(get_a.json()["rows"][0]["amount"], 111)
        self.assertEqual(get_b.json()["rows"][0]["amount"], 222)

        # Direct store inspection confirms distinct, real (userId, projectId)
        # scopes were used -- not "anonymous"/"unscoped".
        self.assertIsNone(get_scoped_dataset_store(("anonymous", dataset_store_module.UNSCOPED_PROJECT)).raw_df)
        self.assertEqual(list(get_scoped_dataset_store((user_a_id, project_a)).raw_df["amount"]), [111])
        self.assertEqual(list(get_scoped_dataset_store((user_b_id, project_b)).raw_df["amount"]), [222])

    def test_result_store_is_isolated_between_real_authenticated_users(self) -> None:
        """PASSING BASELINE. Since Stage 3, RESULTS is (user_id, project_id)-
        scoped and /api/train/last requires project_id -- each user works
        their own real project, writes their own result directly into their
        own explicit (user_id, project_id) scope (RESULTS.set_last_summary,
        exercised directly here rather than via a full training run), and
        reads it back through the real, now-authorized endpoint.
        """
        client_a, user_a_id = _register("http-iso-results-a")
        client_b, user_b_id = _register("http-iso-results-b")
        project_a = _create_project(client_a, "HTTP Isolation Results Project A")
        project_b = _create_project(client_b, "HTTP Isolation Results Project B")

        get_scoped_result_store((user_a_id, project_a)).set_last_summary({"marker": "A", "project_id": project_a})
        get_scoped_result_store((user_b_id, project_b)).set_last_summary({"marker": "B", "project_id": project_b})

        last_a = client_a.get("/api/train/last", params={"project_id": project_a})
        last_b = client_b.get("/api/train/last", params={"project_id": project_b})
        self.assertEqual(last_a.status_code, 200)
        self.assertEqual(last_b.status_code, 200)
        self.assertEqual(last_a.json()["summary"]["marker"], "A")
        self.assertEqual(last_b.json()["summary"]["marker"], "B")
        self.assertIsNone(get_scoped_result_store(("anonymous", result_store_module.UNSCOPED_PROJECT)).get_last_summary())

    def test_two_browser_requests_same_authenticated_user_same_project_share_state(self) -> None:
        """PASSING BASELINE -- confirms the fix is genuinely per-(user,
        project), not per-request: two separate requests from the SAME
        authenticated session, for the SAME project, correctly continue to
        share one scope (this is desired -- see MissingProjectIsolationTests
        for the different-project case).
        """
        client_a, _user_a_id = _register("http-iso-samesession-a")
        project_id = _create_project(client_a, "Same Session Same Project")
        client_a.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 333, "target": 1}], "target": "target"},
        )
        get_a = client_a.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(get_a.json()["rows"][0]["amount"], 333)


class MissingProjectIsolationTests(unittest.TestCase):
    """PASSING BASELINE (as of Stage 2B) -- the primary scenario this stage
    exists to fix. See the module docstring's "STAGE 2B FIX" section.

    Before Stage 2B, every non-identifier test in this class proved that a
    single user's two projects collided in DATASTORE, because no affected
    request model had a project_id field at all. Stage 2B added a REQUIRED
    project_id field to every affected request model, authorized via
    SharingService, and re-keyed DATASTORE by (user_id, project_id).
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def test_set_sample_payload_requires_project_identifier(self) -> None:
        """PASSING BASELINE. Formerly
        test_set_sample_payload_has_no_project_identifier, which proved the
        opposite (no project_id field at all). project_id is now a
        REQUIRED (no-default) field on the real Pydantic model -- verified
        directly, not inferred from the route name.
        """
        fields = SetSamplePayload.model_fields
        self.assertIn("project_id", fields)
        self.assertTrue(fields["project_id"].is_required(), "project_id must be a required field, not optional/defaulted.")

    def test_missing_project_id_is_rejected_not_silently_defaulted(self) -> None:
        """PASSING BASELINE -- REQUIRED SCENARIO 6. Sending
        /api/data/set_sample with no project_id at all must be rejected
        clearly (422, FastAPI/Pydantic's standard missing-required-field
        response) -- never silently treated as a user-only-scoped or
        anonymous request.
        """
        client, _user_id = _register("missing-project-id")
        response = client.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 1, "target": 1}], "target": "target"},
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_blank_project_id_is_rejected(self) -> None:
        """PASSING BASELINE. A whitespace-only project_id satisfies
        Pydantic's `str` type validation but must still be rejected by
        authorize_modeling_scope's own non-blank check (400), never treated
        as a valid scope.
        """
        client, _user_id = _register("blank-project-id")
        response = client.post(
            "/api/data/set_sample",
            json={"project_id": "   ", "headers": ["amount", "target"], "rows": [{"amount": 1, "target": 1}], "target": "target"},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_same_user_two_projects_no_longer_collide(self) -> None:
        """PASSING BASELINE. Formerly
        test_same_user_second_project_overwrites_first_projects_dataset,
        which proved Project A's dataset was silently destroyed the moment
        the same user loaded Project B's. Retained under a new name, using
        two real created projects and inverted assertions, as a permanent
        regression guard -- the primary scenario Stage 2B exists to fix
        (required scenario 1: same user, sequential projects).
        """
        client, _user_id = _register("same-user-sequential")
        project_a = _create_project(client, "Sequential Project A")
        project_b = _create_project(client, "Sequential Project B")

        set_a = client.post(
            "/api/data/set_sample",
            json={"project_id": project_a, "headers": ["amount", "target"], "rows": [{"amount": 1001, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_a.status_code, 200, set_a.text)
        get_after_a = client.get("/api/data/get_sample", params={"project_id": project_a})
        self.assertEqual(get_after_a.json()["rows"][0]["amount"], 1001)

        # The user switches to a second, real project and loads its dataset.
        set_b = client.post(
            "/api/data/set_sample",
            json={"project_id": project_b, "headers": ["amount", "target"], "rows": [{"amount": 2002, "target": 0}], "target": "target"},
        )
        self.assertEqual(set_b.status_code, 200, set_b.text)
        get_after_b = client.get("/api/data/get_sample", params={"project_id": project_b})
        self.assertEqual(get_after_b.json()["rows"][0]["amount"], 2002)

        # Returning to Project A retrieves Project A's own data, untouched.
        get_a_again = client.get("/api/data/get_sample", params={"project_id": project_a})
        self.assertEqual(get_a_again.json()["rows"][0]["amount"], 1001)

    def test_returning_to_project_a_correctly_retrieves_project_as_own_state(self) -> None:
        """PASSING BASELINE. Formerly (Stage 2A)
        `test_returning_to_project_a_should_still_retrieve_project_as_own_state`,
        an `@unittest.expectedFailure` that sent literal, never-created
        strings ("proj-a"/"proj-b") as project_id, back when project_id was
        an ignored, non-existent field -- those literal strings would now
        correctly 404 (see ProjectAuthorizationForDatastoreTests), so this
        version uses two real created projects instead. The
        `@unittest.expectedFailure` decorator is removed: this now passes
        for real.
        """
        client, _user_id = _register("same-user-target-behavior")
        project_a = _create_project(client, "Target Behavior Project A")
        project_b = _create_project(client, "Target Behavior Project B")
        client.post(
            "/api/data/set_sample",
            json={"project_id": project_a, "headers": ["amount", "target"], "rows": [{"amount": 5005, "target": 1}], "target": "target"},
        )
        client.post(
            "/api/data/set_sample",
            json={"project_id": project_b, "headers": ["amount", "target"], "rows": [{"amount": 6006, "target": 0}], "target": "target"},
        )
        get_proj_a = client.get("/api/data/get_sample", params={"project_id": project_a})
        self.assertEqual(get_proj_a.json()["rows"][0]["amount"], 5005)

    def test_two_browser_tabs_different_projects_no_longer_collide(self) -> None:
        """PASSING BASELINE. Formerly
        test_two_browser_tabs_same_user_share_and_collide, which proved two
        tabs of the SAME session collided when working on what were
        (implicitly) two different projects, because nothing could
        distinguish them. Retained under a new name, using two real created
        projects, as a permanent regression guard -- required scenario 2
        (same user, two logical browser tabs, interleaved requests for
        Project A and Project B).
        """
        client_tab1, _user_id = _register("two-tabs-user")
        session_cookie = client_tab1.cookies.get(SESSION_COOKIE_NAME)
        self.assertTrue(session_cookie, "Registration must issue a session cookie.")
        project_a = _create_project(client_tab1, "Two Tabs Project A")
        project_b = _create_project(client_tab1, "Two Tabs Project B")

        client_tab2 = TestClient(app)
        client_tab2.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        # Interleaved: tab 1 writes A, tab 2 writes B, tab 1 reads A again.
        set_tab1 = client_tab1.post(
            "/api/data/set_sample",
            json={"project_id": project_a, "headers": ["amount", "target"], "rows": [{"amount": 3003, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_tab1.status_code, 200, set_tab1.text)
        set_tab2 = client_tab2.post(
            "/api/data/set_sample",
            json={"project_id": project_b, "headers": ["amount", "target"], "rows": [{"amount": 4004, "target": 0}], "target": "target"},
        )
        self.assertEqual(set_tab2.status_code, 200, set_tab2.text)

        get_tab1_a = client_tab1.get("/api/data/get_sample", params={"project_id": project_a})
        get_tab2_b = client_tab2.get("/api/data/get_sample", params={"project_id": project_b})
        self.assertEqual(get_tab1_a.json()["rows"][0]["amount"], 3003)
        self.assertEqual(get_tab2_b.json()["rows"][0]["amount"], 4004)

    def test_two_browser_tabs_same_project_intentionally_share_state(self) -> None:
        """PASSING BASELINE -- documents the boundary of the fix above: two
        tabs of the SAME session, BOTH pinned to the SAME project via
        project_id, correctly (and intentionally) continue to share one
        DATASTORE scope. This is desired, not a bug -- it's what "reopen the
        same project in a second tab" should look like, and it is NOT the
        scenario Stage 2B fixes.
        """
        client_tab1, _user_id = _register("two-tabs-same-project-user")
        session_cookie = client_tab1.cookies.get(SESSION_COOKIE_NAME)
        project_id = _create_project(client_tab1, "Two Tabs Same Project")

        client_tab2 = TestClient(app)
        client_tab2.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        client_tab1.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 9009, "target": 1}], "target": "target"},
        )
        get_tab2 = client_tab2.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(get_tab2.json()["rows"][0]["amount"], 9009)


class ProjectAuthorizationForDatastoreTests(unittest.TestCase):
    """PASSING BASELINE (new in Stage 2B). Proves `authorize_modeling_scope`
    (server/core/modeling_scope.py)'s SharingService-backed authorization
    for DATASTORE-touching endpoints, and the chosen collaborator policy.

    COLLABORATOR POLICY DECISION: OPTION A -- DATASTORE working state is
    user-and-project-private, even among authorized collaborators. Per
    ATLAS_MODELING_STATE_ISOLATION_PLAN.md's recommendation and this task's
    explicit instruction ("DATASTORE working state must resolve by:
    authenticated user_id + project_id"), the scope key is
    (user_id, project_id), never project_id alone. A collaborator who is
    correctly AUTHORIZED for the project (no 403) still resolves their OWN,
    independent, initially-empty DatasetStore for that project, never the
    other collaborator's actual in-progress draft data. This prevents two
    collaborators editing the same project concurrently from corrupting
    each other's unsaved work, and matches the plan's distinction between
    temporary/draft state (private) and committed artifacts (to be shared
    later through RESULTS/project artifacts, Stage 4+ -- see
    CollaboratorVisibilityTests for that separate, still-open concern).
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def test_unauthorized_user_is_denied_with_403_and_receives_no_data(self) -> None:
        """PASSING BASELINE -- required scenario 4 (same project,
        unauthorized user). A user with no relationship to the project must
        be denied, and must never see the owner's actual data.
        """
        owner_client, _owner_id = _register("datastore-authz-owner")
        project_id = _create_project(owner_client, "DATASTORE Authz Project")
        set_response = owner_client.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 8008, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_response.status_code, 200, set_response.text)

        stranger_client, _stranger_id = _register("datastore-authz-stranger")
        response = stranger_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn("8008", response.text)

        write_response = stranger_client.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 9999, "target": 1}], "target": "target"},
        )
        self.assertEqual(write_response.status_code, 403, write_response.text)

        # Owner's data is unaffected by the denied attempts.
        owner_view = owner_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(owner_view.json()["rows"][0]["amount"], 8008)

    def test_nonexistent_project_id_returns_404_and_creates_no_scope(self) -> None:
        """PASSING BASELINE -- required scenario 7 (invalid/inaccessible
        project ID). A syntactically valid but never-created project_id
        must 404, and must not create any DATASTORE scope as a side effect.
        """
        client, user_id = _register("datastore-authz-404")
        fake_project_id = f"proj-does-not-exist-{uuid.uuid4().hex[:12]}"
        response = client.post(
            "/api/data/set_sample",
            json={"project_id": fake_project_id, "headers": ["amount", "target"], "rows": [{"amount": 1, "target": 1}], "target": "target"},
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn((user_id, fake_project_id), dataset_store_module._DATASTORES)

    def test_collaborator_with_view_access_is_authorized_but_gets_independent_empty_scope(self) -> None:
        """PASSING BASELINE -- required scenario 5 (shared collaborator),
        view-only half. A collaborator granted "view" access is correctly
        let PAST authorization (no 403 entering the workflow) but does NOT
        see the owner's actual data (Option A: independent scope), and
        cannot mutate it (view permission maps to "view", not "edit").
        """
        owner_client, owner_id = _register("datastore-collab-view-owner")
        collaborator_client, collaborator_id = _register("datastore-collab-view-collab")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)
        project_id = _create_project(owner_client, "DATASTORE Collab View Project")
        _share_project(owner_client, project_id, collaborator_id, "view")

        owner_set = owner_client.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 7007, "target": 1}], "target": "target"},
        )
        self.assertEqual(owner_set.status_code, 200, owner_set.text)

        # Collaborator authorization succeeds (entering the workflow is
        # allowed)...
        collaborator_view = collaborator_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(collaborator_view.status_code, 200, collaborator_view.text)
        # ...but they do NOT see the owner's actual data -- their own scope
        # was never populated.
        self.assertEqual(collaborator_view.json()["rows"], [])
        self.assertIsNone(get_scoped_dataset_store((collaborator_id, project_id)).raw_df)

        # View-only permission does not allow mutation.
        collaborator_write = collaborator_client.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 1234, "target": 1}], "target": "target"},
        )
        self.assertEqual(collaborator_write.status_code, 403, collaborator_write.text)

    def test_collaborator_with_edit_access_gets_own_independent_working_state(self) -> None:
        """PASSING BASELINE -- required scenario 5, edit half. A
        collaborator granted "edit" access can successfully create their
        OWN working DATASTORE state for the project, entirely independent
        of (and without disturbing) the owner's.
        """
        owner_client, owner_id = _register("datastore-collab-edit-owner")
        collaborator_client, collaborator_id = _register("datastore-collab-edit-collab")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)
        project_id = _create_project(owner_client, "DATASTORE Collab Edit Project")
        _share_project(owner_client, project_id, collaborator_id, "edit")

        owner_client.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 5150, "target": 1}], "target": "target"},
        )
        collaborator_write = collaborator_client.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 6260, "target": 0}], "target": "target"},
        )
        self.assertEqual(collaborator_write.status_code, 200, collaborator_write.text)

        collaborator_view = collaborator_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(collaborator_view.json()["rows"][0]["amount"], 6260)

        # The owner's own draft is completely unaffected by the
        # collaborator's independent write.
        owner_view = owner_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(owner_view.json()["rows"][0]["amount"], 5150)


class ResultsProjectIsolationTests(unittest.TestCase):
    """PASSING BASELINE (new in Stage 3). RESULTS analogue of
    MissingProjectIsolationTests: proves the primary scenarios Stage 3
    exists to fix -- a single user's two projects' training results no
    longer collide in one RESULTS instance. See the module docstring's
    "STAGE 3 FIX" section.

    Setup uses direct get_scoped_result_store((user_id, project_id)).
    set_last_summary(...) writes (mirroring
    ExistingUserIsolationTests.test_result_store_is_isolated_between_real_authenticated_users
    and the original, pre-Stage-3 CollaboratorVisibilityTests fixture
    pattern) rather than running real training jobs -- the mechanism being
    tested here is RESULTS's scope-key resolution and /api/train/last's
    authorization, not the training pipeline itself, which is already
    covered by TrainingJobIsolationTests/BackgroundContextTests.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def test_missing_project_id_is_rejected_not_silently_defaulted(self) -> None:
        """PASSING BASELINE -- required scenario (missing project_id).
        GET /api/train/last with no project_id at all must be rejected
        clearly (422), never silently treated as user-only/anonymous.
        """
        client, _user_id = _register("results-missing-project-id")
        response = client.get("/api/train/last")
        self.assertEqual(response.status_code, 422, response.text)

    def test_blank_project_id_is_rejected(self) -> None:
        """PASSING BASELINE -- required scenario (blank project_id). A
        whitespace-only project_id satisfies FastAPI's `str` query-param
        validation but must still be rejected by authorize_modeling_scope's
        own non-blank check (400).
        """
        client, _user_id = _register("results-blank-project-id")
        response = client.get("/api/train/last", params={"project_id": "   "})
        self.assertEqual(response.status_code, 400, response.text)

    def test_same_user_two_projects_no_longer_collide(self) -> None:
        """PASSING BASELINE -- required scenario (same user, two projects).
        The primary defect this stage fixes: a single user's two real
        projects each get their own RESULTS, never overwriting each other.
        """
        client, user_id = _register("results-same-user-two-projects")
        project_a = _create_project(client, "Results Same User Project A")
        project_b = _create_project(client, "Results Same User Project B")

        get_scoped_result_store((user_id, project_a)).set_last_summary({"marker": "RESULT-A", "project_id": project_a})
        get_scoped_result_store((user_id, project_b)).set_last_summary({"marker": "RESULT-B", "project_id": project_b})

        last_a = client.get("/api/train/last", params={"project_id": project_a})
        last_b = client.get("/api/train/last", params={"project_id": project_b})
        self.assertEqual(last_a.json()["summary"]["marker"], "RESULT-A")
        self.assertEqual(last_b.json()["summary"]["marker"], "RESULT-B")

    def test_returning_to_project_a_after_modifying_project_b_retrieves_project_as_own_state(self) -> None:
        """PASSING BASELINE -- required scenario (return to project A after
        modifying project B). Sequential: read A, modify B, read A again --
        A's result must be exactly what it was, untouched by B's write.
        """
        client, user_id = _register("results-return-to-a")
        project_a = _create_project(client, "Results Return To A Project A")
        project_b = _create_project(client, "Results Return To A Project B")

        get_scoped_result_store((user_id, project_a)).set_last_summary({"marker": "ORIGINAL-A", "project_id": project_a})
        first_read = client.get("/api/train/last", params={"project_id": project_a})
        self.assertEqual(first_read.json()["summary"]["marker"], "ORIGINAL-A")

        get_scoped_result_store((user_id, project_b)).set_last_summary({"marker": "NEW-B", "project_id": project_b})
        b_read = client.get("/api/train/last", params={"project_id": project_b})
        self.assertEqual(b_read.json()["summary"]["marker"], "NEW-B")

        return_to_a = client.get("/api/train/last", params={"project_id": project_a})
        self.assertEqual(return_to_a.json()["summary"]["marker"], "ORIGINAL-A")

    def test_two_browser_tabs_different_projects_no_longer_collide(self) -> None:
        """PASSING BASELINE -- required scenario (two browser tabs, different
        projects). Same authenticated session, two logical tabs, each
        pinned to a different project via project_id -- neither's read is
        affected by the other's data.
        """
        client_tab1, user_id = _register("results-two-tabs-user")
        session_cookie = client_tab1.cookies.get(SESSION_COOKIE_NAME)
        project_a = _create_project(client_tab1, "Results Two Tabs Project A")
        project_b = _create_project(client_tab1, "Results Two Tabs Project B")

        client_tab2 = TestClient(app)
        client_tab2.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        get_scoped_result_store((user_id, project_a)).set_last_summary({"marker": "TAB1-A", "project_id": project_a})
        get_scoped_result_store((user_id, project_b)).set_last_summary({"marker": "TAB2-B", "project_id": project_b})

        read_tab1 = client_tab1.get("/api/train/last", params={"project_id": project_a})
        read_tab2 = client_tab2.get("/api/train/last", params={"project_id": project_b})
        self.assertEqual(read_tab1.json()["summary"]["marker"], "TAB1-A")
        self.assertEqual(read_tab2.json()["summary"]["marker"], "TAB2-B")


class ResultsAuthorizationTests(unittest.TestCase):
    """PASSING BASELINE (new in Stage 3). RESULTS analogue of
    ProjectAuthorizationForDatastoreTests: proves authorize_modeling_scope's
    SharingService-backed authorization for RESULTS-touching endpoints, and
    the Option-A collaborator policy (see the module docstring's "STAGE 3
    FIX" -- DECISION section for the full rationale).

    View-permission tests use GET /api/train/last (safe with no RESULTS
    data present: returns `{"summary": None}`, HTTP 200 -- an ordinary
    business response, not an error). Edit-permission tests use POST
    /api/score/development-split (also safe with no DATASTORE split
    present: returns `{"ok": False, "error": "No ... split is available"}`,
    HTTP 200 -- again a business response). Both endpoints call
    authorize_modeling_scope as the FIRST line of their handler, so an
    unauthorized caller is rejected (400/403/404) strictly BEFORE any of
    that business logic runs -- these tests assert on status codes for
    exactly that reason: the authorization boundary, not the business
    outcome, is what's under test. RESULTS's actual (user, project) scope-
    key isolation is proven once, directly, in
    ResultsProjectIsolationTests/ExistingUserIsolationTests -- since every
    RESULTS accessor (whichever endpoint) goes through the same
    get_scoped_result_store()/_scope_key(), that isolation guarantee is not
    re-proven per-endpoint here.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def test_unauthorized_user_is_denied_read_and_write_with_403(self) -> None:
        """PASSING BASELINE -- required scenarios (unauthorized user read,
        unauthorized user write). A user with no relationship to the
        project is denied both a RESULTS read and a RESULTS-touching write,
        and never sees the owner's actual data.
        """
        owner_client, owner_id = _register("results-authz-owner")
        project_id = _create_project(owner_client, "Results Authz Project")
        get_scoped_result_store((owner_id, project_id)).set_last_summary({"marker": "OWNER-ONLY-RESULT", "project_id": project_id})

        stranger_client, _stranger_id = _register("results-authz-stranger")
        read_response = stranger_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(read_response.status_code, 403, read_response.text)
        self.assertNotIn("OWNER-ONLY-RESULT", read_response.text)

        write_response = stranger_client.post("/api/score/development-split", params={"project_id": project_id})
        self.assertEqual(write_response.status_code, 403, write_response.text)

        # Owner's own read is unaffected by the denied attempts.
        owner_view = owner_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(owner_view.json()["summary"]["marker"], "OWNER-ONLY-RESULT")

    def test_nonexistent_project_id_returns_404_and_creates_no_scope(self) -> None:
        """PASSING BASELINE -- required scenario (nonexistent project ID).
        A syntactically valid but never-created project_id must 404 on both
        a RESULTS read and a RESULTS-touching write, with no scope created.
        """
        client, user_id = _register("results-authz-404")
        fake_project_id = f"proj-does-not-exist-{uuid.uuid4().hex[:12]}"

        read_response = client.get("/api/train/last", params={"project_id": fake_project_id})
        self.assertEqual(read_response.status_code, 404, read_response.text)

        write_response = client.post("/api/score/development-split", params={"project_id": fake_project_id})
        self.assertEqual(write_response.status_code, 404, write_response.text)

        self.assertNotIn((user_id, fake_project_id), result_store_module._RESULT_STORES)

    def test_collaborator_with_view_access_is_authorized_but_gets_independent_empty_scope(self) -> None:
        """PASSING BASELINE -- required scenario (authorized collaborator
        behavior), view half. A collaborator granted "view" access is
        correctly let PAST authorization (no 403) but does NOT see the
        owner's actual result (Option A: independent scope), and cannot
        perform an edit-permission action.
        """
        owner_client, owner_id = _register("results-collab-view-owner")
        collaborator_client, collaborator_id = _register("results-collab-view-collab")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)
        project_id = _create_project(owner_client, "Results Collab View Project")
        _share_project(owner_client, project_id, collaborator_id, "view")

        get_scoped_result_store((owner_id, project_id)).set_last_summary({"marker": "OWNER-RESULT", "project_id": project_id})

        collaborator_view = collaborator_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(collaborator_view.status_code, 200, collaborator_view.text)
        self.assertIsNone(collaborator_view.json()["summary"])
        self.assertIsNone(get_scoped_result_store((collaborator_id, project_id)).get_last_summary())

        collaborator_write = collaborator_client.post("/api/score/development-split", params={"project_id": project_id})
        self.assertEqual(collaborator_write.status_code, 403, collaborator_write.text)

    def test_collaborator_with_edit_access_is_authorized_for_results_mutating_endpoints(self) -> None:
        """PASSING BASELINE -- required scenario (authorized collaborator
        behavior), edit half. A collaborator granted "edit" access is
        correctly let PAST authorization for a RESULTS-mutating endpoint
        (POST /api/score/development-split) -- the owner's own RESULTS
        scope is untouched by the collaborator's authorized action, per the
        Option-A collaborator policy (see the class docstring).
        """
        owner_client, owner_id = _register("results-collab-edit-owner")
        collaborator_client, collaborator_id = _register("results-collab-edit-collab")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)
        project_id = _create_project(owner_client, "Results Collab Edit Project")
        _share_project(owner_client, project_id, collaborator_id, "edit")

        get_scoped_result_store((owner_id, project_id)).set_last_summary({"marker": "OWNER-RESULT", "project_id": project_id})

        collaborator_write = collaborator_client.post("/api/score/development-split", params={"project_id": project_id})
        self.assertEqual(collaborator_write.status_code, 200, collaborator_write.text)

        # The owner's own result is completely unaffected by the
        # collaborator's independently-authorized action.
        owner_view = owner_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(owner_view.json()["summary"]["marker"], "OWNER-RESULT")
        self.assertIsNone(get_scoped_result_store((collaborator_id, project_id)).get_last_summary())


class BackgroundContextTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """Mixed: one remaining KNOWN LIMITATION (general-purpose, not
    TRAINING_JOBS-specific), one PASSING test.

    test_bare_thread_does_not_inherit_active_user_context remains a KNOWN
    LIMITATION -- targets Stage 6 of ATLAS_MODELING_STATE_ISOLATION_PLAN.md.
    Root defect: contextvars.Context is not inherited by a bare
    threading.Thread or a raw concurrent.futures.ThreadPoolExecutor. This
    is a general property of the Python contextvars/threading model, proven
    here directly against DATASTORE's own `_scope_key()`, independent of any
    particular endpoint. Stage 4 does NOT fix this general limitation and
    does not need to: as documented in training_job_service.py's module
    comment, TRAINING_JOBS' background thread (`_run`) never actually
    depended on contextvars propagating into it -- it receives
    X_train/X_test/y_train/y_test as explicit arguments and writes through
    an explicitly captured RESULTS instance and job-record fields
    (`owner_user_id`, `project_id`) set on the request thread before the
    background thread starts. See test_two_users_training_jobs_no_longer_collide
    below for the TRAINING_JOBS-specific proof that this explicit-capture
    strategy is sufficient without needing this general contextvars fix.

    test_two_users_training_jobs_no_longer_collide_after_active_user_fix is
    PASSING BASELINE: `training_job_service.create()` captures
    `RESULTS.current()` **on the request thread**, and reads DATASTORE via
    the (now project-scoped) ambient proxy also on the request thread --
    both correctly resolve thanks to ActiveUserContextMiddleware (user) and
    the real `authorize_modeling_scope` call now guarding
    `/model/train/jobs` (project) -- Stage 4 retired the old temporary,
    non-authorizing `set_active_project_id` connectivity workaround this
    docstring used to describe; see trainer_router.py and this file's
    module docstring's "STAGE 4 FIX" section. Since Stage 3, RESULTS is
    also (user_id, project_id)-scoped, so this test additionally confirms
    the completed job's summary lands in the correct explicit RESULTS
    scope, not just the correct user's.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()

    def tearDown(self) -> None:
        self._restore_global_stores()

    def test_bare_thread_does_not_inherit_active_user_context(self) -> None:
        """PASSES TODAY. Smallest reliable reproduction of the raw
        mechanism, using the real production `_scope_key()` function
        (server/core/dataset_store.py) with an EXPLICITLY set
        active_user() (via set_active_user(), the exact call
        require_user() makes) -- proving that even when a context IS
        correctly populated in the calling thread, a bare background
        thread still does not inherit it. This is a distinct, independent
        defect from the Depends()-propagation gap Stage 2A fixed: fixing
        one does not fix the other. Uses threading.Event for deterministic
        synchronization -- no sleeps.
        """
        marker_user = {"userId": f"context-probe-{uuid.uuid4().hex[:8]}"}
        set_active_user(marker_user)
        try:
            self.assertEqual(dataset_store_module._scope_key(), (marker_user["userId"], dataset_store_module.UNSCOPED_PROJECT))

            observed: Dict[str, Any] = {}
            done = threading.Event()

            def worker() -> None:
                observed["scope"] = dataset_store_module._scope_key()
                done.set()

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            signaled = done.wait(timeout=5.0)
            thread.join(timeout=5.0)

            self.assertTrue(signaled, "Background thread did not signal completion in time.")
            self.assertEqual(observed["scope"], ("anonymous", dataset_store_module.UNSCOPED_PROJECT))
            self.assertNotEqual(observed["scope"][0], marker_user["userId"])
        finally:
            set_active_user(None)

    def test_two_users_training_jobs_no_longer_collide_after_active_user_fix(self) -> None:
        """PASSING BASELINE. Two DIFFERENT real authenticated users each
        create a real training job through the real HTTP router, each with
        their own governed dataset/split seeded under their own
        (user_id, project_id) scope. Both jobs correctly find their own
        data (trainer_router.py's set_active_project_id connectivity call)
        and land their results under their own real userId, not a shared
        bucket.
        """
        client_a, user_a_id = _register("bg-collide-a")
        client_b, user_b_id = _register("bg-collide-b")
        self.assertNotEqual(user_a_id, user_b_id)

        # Real, persisted projects: /model/train/jobs itself does not
        # authorize project_id (see the module docstring's "IMPORTANT,
        # NARROW EXCEPTION" -- training authorization remains Stage 5's
        # target), but /train/last DOES, so these need to genuinely exist
        # and be owned by their respective callers for the read below.
        project_a = _create_project(client_a, "BG Collide Project A")
        project_b = _create_project(client_b, "BG Collide Project B")

        _seed_governed_dataset_and_split(user_a_id, project_a, "bg-v1", "bg-fm-v1", "bg-split-v1")
        create_a = client_a.post("/api/model/train/jobs", json=_training_job_payload(project_a, "bg-v1", "bg-fm-v1", "bg-split-v1", "user-a"))
        self.assertEqual(create_a.status_code, 200, create_a.text)
        job_a_id = create_a.json()["job_id"]
        final_a = _wait_for_terminal_job(client_a, job_a_id, project_a)
        self.assertEqual(final_a["overall_status"], "complete", final_a)

        # User A's result now lands under their own real (userId, projectId)
        # scope, not the shared "anonymous"/"unscoped" bucket.
        self.assertIsNotNone(get_scoped_result_store((user_a_id, project_a)).get_last_summary())
        self.assertIsNone(get_scoped_result_store(("anonymous", result_store_module.UNSCOPED_PROJECT)).get_last_summary())

        # User B, working on a COMPLETELY different project, now trains too.
        _seed_governed_dataset_and_split(user_b_id, project_b, "bg-v2", "bg-fm-v2", "bg-split-v2")
        create_b = client_b.post("/api/model/train/jobs", json=_training_job_payload(project_b, "bg-v2", "bg-fm-v2", "bg-split-v2", "user-b"))
        self.assertEqual(create_b.status_code, 200, create_b.text)
        job_b_id = create_b.json()["job_id"]
        final_b = _wait_for_terminal_job(client_b, job_b_id, project_b)
        self.assertEqual(final_b["overall_status"], "complete", final_b)
        self.assertIsNotNone(get_scoped_result_store((user_b_id, project_b)).get_last_summary())

        # User A's own subsequent read of "their" last training result still
        # correctly reflects User A's own job, unaffected by User B's.
        last_for_a = client_a.get("/api/train/last", params={"project_id": project_a})
        self.assertEqual(last_for_a.json()["summary"]["project_id"], project_a)
        self.assertNotEqual(last_for_a.json()["summary"]["project_id"], project_b)
        last_for_b = client_b.get("/api/train/last", params={"project_id": project_b})
        self.assertEqual(last_for_b.json()["summary"]["project_id"], project_b)


def _simulate_restart() -> bool:
    """Clear the in-memory _DATASTORES/_RESULT_STORES dicts (what a fresh
    process actually starts with) and call the real load_checkpoint().
    Fast and sufficient for exercising the save/load LOGIC itself; does
    NOT prove there is no reliance on other same-process state a genuine
    restart would also clear -- see CheckpointSubprocessRestartTests for
    that stronger guarantee.
    """
    dataset_store_module._DATASTORES.clear()
    result_store_module._RESULT_STORES.clear()
    return session_checkpoint_module.load_checkpoint()


class CheckpointRestoreTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (promoted/rewritten in Stage 6; see the module
    docstring's "STAGE 6 FIX" section and "Tests that changed
    classification in Stage 6" list). Covers the CORE save/restore
    mechanics using set_active_user() directly (not HTTP) for
    deterministic scope control. CheckpointMultiScopeRestartTests (below)
    covers the required multi-project/multi-user/collaborator scenarios
    using real HTTP requests; CheckpointSubprocessRestartTests covers
    genuinely fresh-process verification.

    These tests monkeypatch session_checkpoint.CHECKPOINT_PATH to an
    isolated temporary file for the duration of each test and restore the
    original path afterward -- the real shared development checkpoint file
    is never touched.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()
        self._original_checkpoint_path = session_checkpoint_module.CHECKPOINT_PATH
        self._temp_dir = Path(tempfile.mkdtemp(prefix="atlas_checkpoint_test_"))
        session_checkpoint_module.CHECKPOINT_PATH = self._temp_dir / "workflow_checkpoint.json"

    def tearDown(self) -> None:
        session_checkpoint_module.CHECKPOINT_PATH = self._original_checkpoint_path
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._restore_global_stores()

    def test_checkpoint_save_preserves_all_scopes_not_just_the_last_writer(self) -> None:
        """PASSING BASELINE (inverted from its Stage 1-5-era finding -- see
        the module docstring). Formerly proved saving User B's state after
        User A's overwrote A's snapshot entirely. Since save_checkpoint()
        now serializes every resident scope on every call, both users'
        data survive both saves.
        """
        user_a = {"userId": f"checkpoint-a-{uuid.uuid4().hex[:8]}"}
        user_b = {"userId": f"checkpoint-b-{uuid.uuid4().hex[:8]}"}

        set_active_user(user_a)
        try:
            from server.core.dataset_store import DATASTORE

            DATASTORE.reset_all()
            DATASTORE.set_raw(pd.DataFrame({"marker": ["A-ONLY"]}))
            self.assertTrue(session_checkpoint_module.save_checkpoint())
        finally:
            set_active_user(None)

        set_active_user(user_b)
        try:
            from server.core.dataset_store import DATASTORE

            DATASTORE.reset_all()
            DATASTORE.set_raw(pd.DataFrame({"marker": ["B-ONLY"]}))
            self.assertTrue(session_checkpoint_module.save_checkpoint())
        finally:
            set_active_user(None)

        raw_contents = session_checkpoint_module.CHECKPOINT_PATH.read_text(encoding="utf-8")
        self.assertIn("B-ONLY", raw_contents)
        self.assertIn("A-ONLY", raw_contents, "The checkpoint file must retain BOTH users' scopes -- save_checkpoint() snapshots every resident scope, not just the caller's own.")
        self.assertIn(user_a["userId"], raw_contents)
        self.assertIn(user_b["userId"], raw_contents)

    def test_restart_reload_restores_into_each_users_own_real_scope(self) -> None:
        """PASSING BASELINE (inverted from its Stage 1-5-era finding -- see
        the module docstring). Formerly proved restart always collapsed
        into the shared ("anonymous", "unscoped") bucket regardless of who
        saved the data. Since load_checkpoint() now restores each record
        into its own explicit (user_id, project_id) from the file itself,
        User B's data lands under User B's own real identity.

        Stage 6.1 update: the user and project must now genuinely EXIST --
        save/load filter out scopes whose owner or project was deleted (or
        never existed), so this test registers them for real instead of
        fabricating ids (see tests/checkpoint_lifecycle_test.py for the
        filtering behavior itself).
        """
        client_b, user_b_id = _register("checkpoint-restart-b")
        project_id = _create_project(client_b, "Checkpoint Restart B Project")
        user_b = {"userId": user_b_id}
        set_active_user(user_b)
        try:
            from server.core.modeling_scope import set_active_project_id

            set_active_project_id(project_id)
            from server.core.dataset_store import DATASTORE
            from server.core.result_store import RESULTS

            DATASTORE.reset_all()
            DATASTORE.set_raw(pd.DataFrame({"marker": ["RESTART-B"]}))
            RESULTS.set_last_summary({"marker": "RESTART-B-RESULT"})
            self.assertTrue(session_checkpoint_module.save_checkpoint())
        finally:
            set_active_user(None)
            # ACTIVE_PROJECT_ID is a separate ContextVar from ACTIVE_USER --
            # set_active_user(None) does not reset it. Since this test's
            # process/thread is shared across the whole suite (unittest
            # runs all tests in one process), leaving it set here would
            # leak this project_id into whichever test happens to run next
            # in this same thread. Reset it explicitly, the same discipline
            # set_active_user(None) already follows for its own ContextVar.
            set_active_project_id(None)

        self.assertIsNone(active_user())
        self.assertTrue(_simulate_restart())

        own_scope = (user_b["userId"], project_id)
        own_df = get_scoped_dataset_store(own_scope).raw_df
        self.assertIsNotNone(own_df)
        self.assertEqual(list(own_df["marker"]), ["RESTART-B"])
        own_result = get_scoped_result_store(own_scope).get_last_summary()
        self.assertIsNotNone(own_result)
        self.assertEqual(own_result["marker"], "RESTART-B-RESULT")

        # The shared anonymous/unscoped bucket is untouched by this save --
        # ownership was preserved, not collapsed into it.
        legacy_scope = ("anonymous", dataset_store_module.UNSCOPED_PROJECT)
        self.assertIsNone(get_scoped_dataset_store(legacy_scope).raw_df)
        self.assertIsNone(get_scoped_result_store(legacy_scope).get_last_summary())

    def test_restart_should_restore_each_users_own_scope(self) -> None:
        """PASSING BASELINE (promoted in Stage 6 -- decorator removed, no
        body changes needed; see the module docstring's "Tests that
        changed classification in Stage 6" list). No project context is
        set during save here, so the scope saved under is (user_id,
        UNSCOPED_PROJECT) -- which correctly IS "the user's own scope" for
        this narrow, project-less setup. Stage 6 restores exactly the
        scope a record was saved under, so this now holds for real.
        """
        user_b = {"userId": f"checkpoint-restart-target-{uuid.uuid4().hex[:8]}"}
        set_active_user(user_b)
        try:
            from server.core.dataset_store import DATASTORE

            DATASTORE.reset_all()
            DATASTORE.set_raw(pd.DataFrame({"marker": ["RESTART-TARGET"]}))
            self.assertTrue(session_checkpoint_module.save_checkpoint())
        finally:
            set_active_user(None)

        self.assertTrue(_simulate_restart())

        restored = get_scoped_dataset_store((user_b["userId"], dataset_store_module.UNSCOPED_PROJECT)).raw_df
        self.assertIsNotNone(restored)
        self.assertEqual(list(restored["marker"]), ["RESTART-TARGET"])

    def test_checkpoint_save_triggered_by_a_real_request_now_saves_the_real_users_scope(self) -> None:
        """PASSING BASELINE. server/core/metadata_router.py's `set_sample()`
        marks the checkpoint dirty via `schedule_checkpoint_save()` (Stage
        6.1: routine mutations coalesce in a background writer instead of
        rewriting the whole file on the request thread -- flush_checkpoint()
        makes the pending state durable on demand). Since
        ActiveUserContextMiddleware (Stage 2A) fixes ambient user
        resolution for the request thread, the checkpointed state captures
        that user's own scope -- and, since Stage 6, restores into that
        SAME real (user_id, project_id) scope, not the shared
        anonymous/unscoped bucket.
        """
        client, user_id = _register("checkpoint-real-request")
        project_id = _create_project(client, "Checkpoint Real Request Project")
        set_a = client.post(
            "/api/data/set_sample",
            json={"project_id": project_id, "headers": ["amount", "target"], "rows": [{"amount": 777, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_a.status_code, 200, set_a.text)

        # Stage 6.1: the request only SCHEDULED the save; force the pending
        # write before inspecting the file (shutdown does the same flush).
        self.assertTrue(session_checkpoint_module.flush_checkpoint())
        raw_contents = session_checkpoint_module.CHECKPOINT_PATH.read_text(encoding="utf-8")
        self.assertIn("777", raw_contents)
        self.assertIn(user_id, raw_contents)
        self.assertIn(project_id, raw_contents)

        self.assertTrue(_simulate_restart())
        own_scope = (user_id, project_id)
        self.assertEqual(list(get_scoped_dataset_store(own_scope).raw_df["amount"]), [777])

        # And, since restoration no longer depends on any ambient
        # ContextVar, the real authorized HTTP path sees it too.
        get_response = client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(get_response.status_code, 200, get_response.text)
        self.assertEqual(get_response.json()["rows"][0]["amount"], 777)


def _create_real_training_job(
    label: str,
    client: TestClient | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    models: list | None = None,
) -> tuple[TestClient, str, str, str]:
    """Register a user (or reuse one) and a real project (or reuse one),
    seed a governed dataset/split into that (user, project) scope, and
    create a real training job through the real HTTP router. Returns
    (client, user_id, project_id, job_id).

    Since Stage 4, /api/model/train/jobs requires AND authorizes
    project_id, so -- unlike the Stage 2B-era version of this helper --
    project_id must be a genuine, persisted, accessible project, not an
    arbitrary string. Shared by TrainingJobIsolationTests and
    TrainingJobProjectIsolationTests.
    """
    if client is None or user_id is None:
        client, user_id = _register(label)
    if project_id is None:
        project_id = _create_project(client, f"Training Job {label} Project")
    _seed_governed_dataset_and_split(user_id, project_id, f"{label}-v1", f"{label}-fm-v1", f"{label}-split-v1")
    create = client.post(
        "/api/model/train/jobs",
        json=_training_job_payload(project_id, f"{label}-v1", f"{label}-fm-v1", f"{label}-split-v1", label, models=models),
    )
    assert create.status_code == 200, create.text
    return client, user_id, project_id, create.json()["job_id"]


class CheckpointMultiScopeRestartTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (new in Stage 6). Covers the required multi-
    project/multi-user/collaborator restart scenarios (A-F) using real HTTP
    requests end to end -- registration, project creation, sharing, and
    (post-restart) authorized/unauthorized reads all go through the actual
    routers, not direct store manipulation alone, so these tests also prove
    that restored state does not bypass SharingService authorization.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()
        self._original_checkpoint_path = session_checkpoint_module.CHECKPOINT_PATH
        self._temp_dir = Path(tempfile.mkdtemp(prefix="atlas_checkpoint_multiscope_test_"))
        session_checkpoint_module.CHECKPOINT_PATH = self._temp_dir / "workflow_checkpoint.json"

    def tearDown(self) -> None:
        session_checkpoint_module.CHECKPOINT_PATH = self._original_checkpoint_path
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._restore_global_stores()

    def test_same_user_two_projects_restart_restores_each_independently(self) -> None:
        """PASSING BASELINE -- required scenario A (same user, two
        projects). Distinct DATASTORE and RESULTS values in two real
        projects both survive restart, each in its own scope only.
        """
        client, user_id = _register("ckpt-same-user")
        project_a = _create_project(client, "Checkpoint Same User Project A")
        project_b = _create_project(client, "Checkpoint Same User Project B")

        get_scoped_dataset_store((user_id, project_a)).set_raw(pd.DataFrame({"marker": ["A-DATA"]}))
        get_scoped_result_store((user_id, project_a)).set_last_summary({"marker": "A-RESULT"})
        get_scoped_dataset_store((user_id, project_b)).set_raw(pd.DataFrame({"marker": ["B-DATA"]}))
        get_scoped_result_store((user_id, project_b)).set_last_summary({"marker": "B-RESULT"})

        self.assertTrue(session_checkpoint_module.save_checkpoint())
        self.assertTrue(_simulate_restart())

        self.assertEqual(list(get_scoped_dataset_store((user_id, project_a)).raw_df["marker"]), ["A-DATA"])
        self.assertEqual(list(get_scoped_dataset_store((user_id, project_b)).raw_df["marker"]), ["B-DATA"])
        self.assertEqual(get_scoped_result_store((user_id, project_a)).get_last_summary()["marker"], "A-RESULT")
        self.assertEqual(get_scoped_result_store((user_id, project_b)).get_last_summary()["marker"], "B-RESULT")

        # Real, authorized HTTP reads confirm the same, post-restart.
        read_a = client.get("/api/data/get_sample", params={"project_id": project_a})
        read_b = client.get("/api/data/get_sample", params={"project_id": project_b})
        self.assertEqual(read_a.json()["rows"][0]["marker"], "A-DATA")
        self.assertEqual(read_b.json()["rows"][0]["marker"], "B-DATA")

    def test_two_users_two_projects_restart_no_cross_user_visibility(self) -> None:
        """PASSING BASELINE -- required scenario B (two users). Distinct
        users' distinct projects both survive restart with no cross-user
        visibility, in memory or over HTTP.
        """
        client_a, user_a_id = _register("ckpt-two-users-a")
        client_b, user_b_id = _register("ckpt-two-users-b")
        project_a = _create_project(client_a, "Checkpoint Two Users Project A")
        project_b = _create_project(client_b, "Checkpoint Two Users Project B")

        get_scoped_dataset_store((user_a_id, project_a)).set_raw(pd.DataFrame({"marker": ["USER-A-DATA"]}))
        get_scoped_dataset_store((user_b_id, project_b)).set_raw(pd.DataFrame({"marker": ["USER-B-DATA"]}))

        self.assertTrue(session_checkpoint_module.save_checkpoint())
        self.assertTrue(_simulate_restart())

        self.assertEqual(list(get_scoped_dataset_store((user_a_id, project_a)).raw_df["marker"]), ["USER-A-DATA"])
        self.assertEqual(list(get_scoped_dataset_store((user_b_id, project_b)).raw_df["marker"]), ["USER-B-DATA"])
        self.assertIsNone(get_scoped_dataset_store((user_a_id, project_b)).raw_df)
        self.assertIsNone(get_scoped_dataset_store((user_b_id, project_a)).raw_df)

        # After restart, User B still cannot read User A's project over
        # HTTP -- restored state alone does not grant access; SharingService
        # still governs it exactly as before any restart.
        cross_read = client_b.get("/api/data/get_sample", params={"project_id": project_a})
        self.assertEqual(cross_read.status_code, 403, cross_read.text)

    def test_two_browser_tabs_interleaved_writes_restart_restores_both(self) -> None:
        """PASSING BASELINE -- required scenario C (two browser tabs).
        Interleaved writes from two logical tabs of the same session, into
        two different projects, both survive restart correctly.
        """
        client_tab1, user_id = _register("ckpt-two-tabs")
        session_cookie = client_tab1.cookies.get(SESSION_COOKIE_NAME)
        project_a = _create_project(client_tab1, "Checkpoint Two Tabs Project A")
        project_b = _create_project(client_tab1, "Checkpoint Two Tabs Project B")
        client_tab2 = TestClient(app)
        client_tab2.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        set_a = client_tab1.post("/api/data/set_sample", json={"project_id": project_a, "headers": ["amount", "target"], "rows": [{"amount": 111, "target": 1}], "target": "target"})
        set_b = client_tab2.post("/api/data/set_sample", json={"project_id": project_b, "headers": ["amount", "target"], "rows": [{"amount": 222, "target": 0}], "target": "target"})
        self.assertEqual(set_a.status_code, 200, set_a.text)
        self.assertEqual(set_b.status_code, 200, set_b.text)

        # Stage 6.1: set_sample schedules a debounced save; flush the pending
        # write before simulating the restart (a real shutdown also flushes).
        self.assertTrue(session_checkpoint_module.flush_checkpoint())
        self.assertTrue(_simulate_restart())

        self.assertEqual(int(get_scoped_dataset_store((user_id, project_a)).raw_df["amount"].iloc[0]), 111)
        self.assertEqual(int(get_scoped_dataset_store((user_id, project_b)).raw_df["amount"].iloc[0]), 222)

    def test_return_to_project_a_after_project_b_survives_restart(self) -> None:
        """PASSING BASELINE -- required scenario D (return to project A
        after project B), before AND after restart.
        """
        client, user_id = _register("ckpt-return-a")
        project_a = _create_project(client, "Checkpoint Return A Project A")
        project_b = _create_project(client, "Checkpoint Return A Project B")

        client.post("/api/data/set_sample", json={"project_id": project_a, "headers": ["amount", "target"], "rows": [{"amount": 5005, "target": 1}], "target": "target"})
        before_restart = client.get("/api/data/get_sample", params={"project_id": project_a})
        self.assertEqual(before_restart.json()["rows"][0]["amount"], 5005)

        client.post("/api/data/set_sample", json={"project_id": project_b, "headers": ["amount", "target"], "rows": [{"amount": 6006, "target": 0}], "target": "target"})

        # Stage 6.1: set_sample schedules a debounced save; flush the pending
        # write before simulating the restart (a real shutdown also flushes).
        self.assertTrue(session_checkpoint_module.flush_checkpoint())
        self.assertTrue(_simulate_restart())

        after_restart = client.get("/api/data/get_sample", params={"project_id": project_a})
        self.assertEqual(after_restart.status_code, 200, after_restart.text)
        self.assertEqual(after_restart.json()["rows"][0]["amount"], 5005)

    def test_collaborator_does_not_inherit_owners_state_after_restart(self) -> None:
        """PASSING BASELINE -- required scenario E (collaborator). The
        owner's private draft state does not become visible to an
        authorized collaborator after restart; the collaborator's own
        (separately saved) private state remains their own.
        """
        owner_client, owner_id = _register("ckpt-collab-owner")
        collaborator_client, collaborator_id = _register("ckpt-collab-user")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)
        project_id = _create_project(owner_client, "Checkpoint Collaborator Project")
        _share_project(owner_client, project_id, collaborator_id, "edit")

        get_scoped_dataset_store((owner_id, project_id)).set_raw(pd.DataFrame({"marker": ["OWNER-DRAFT"]}))
        get_scoped_dataset_store((collaborator_id, project_id)).set_raw(pd.DataFrame({"marker": ["COLLAB-DRAFT"]}))

        self.assertTrue(session_checkpoint_module.save_checkpoint())
        self.assertTrue(_simulate_restart())

        self.assertEqual(list(get_scoped_dataset_store((owner_id, project_id)).raw_df["marker"]), ["OWNER-DRAFT"])
        self.assertEqual(list(get_scoped_dataset_store((collaborator_id, project_id)).raw_df["marker"]), ["COLLAB-DRAFT"])

        # Over HTTP: the collaborator sees only their OWN restored draft.
        collaborator_view = collaborator_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(collaborator_view.status_code, 200, collaborator_view.text)
        self.assertEqual(collaborator_view.json()["rows"][0]["marker"], "COLLAB-DRAFT")

        owner_view = owner_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(owner_view.json()["rows"][0]["marker"], "OWNER-DRAFT")

    def test_restored_state_does_not_bypass_project_authorization(self) -> None:
        """PASSING BASELINE -- required scenario F (missing/nonexistent
        project). Restored state never grants HTTP access by itself: a
        stranger is still 403'd, missing project_id still 422s, and a
        nonexistent project_id still 404s, exactly as if the process had
        never restarted.
        """
        owner_client, owner_id = _register("ckpt-authz-owner")
        project_id = _create_project(owner_client, "Checkpoint Authz Project")
        get_scoped_dataset_store((owner_id, project_id)).set_raw(pd.DataFrame({"marker": ["OWNER-ONLY"]}))
        self.assertTrue(session_checkpoint_module.save_checkpoint())
        self.assertTrue(_simulate_restart())

        stranger_client, _stranger_id = _register("ckpt-authz-stranger")
        stranger_response = stranger_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(stranger_response.status_code, 403, stranger_response.text)

        missing_response = owner_client.get("/api/data/get_sample")
        self.assertEqual(missing_response.status_code, 422, missing_response.text)

        nonexistent_response = owner_client.get("/api/data/get_sample", params={"project_id": "proj-does-not-exist-ckpt"})
        self.assertEqual(nonexistent_response.status_code, 404, nonexistent_response.text)

        # Owner's own restored data is unaffected by the denied attempts.
        owner_response = owner_client.get("/api/data/get_sample", params={"project_id": project_id})
        self.assertEqual(owner_response.json()["rows"][0]["marker"], "OWNER-ONLY")


class TrainingJobCheckpointPolicyTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (new in Stage 6). Proves the TRAINING_JOBS-not-
    checkpointed architecture decision (see the module docstring's "STAGE
    6 FIX" section) directly -- required scenarios G (interrupted job) and
    H (completed job/result).
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()
        self._original_checkpoint_path = session_checkpoint_module.CHECKPOINT_PATH
        self._temp_dir = Path(tempfile.mkdtemp(prefix="atlas_checkpoint_jobs_test_"))
        session_checkpoint_module.CHECKPOINT_PATH = self._temp_dir / "workflow_checkpoint.json"

    def tearDown(self) -> None:
        session_checkpoint_module.CHECKPOINT_PATH = self._original_checkpoint_path
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._restore_global_stores()

    def _clear_training_jobs(self) -> None:
        training_job_service_module.TRAINING_JOBS._jobs.clear()
        training_job_service_module.TRAINING_JOBS._project_job_ids.clear()
        training_job_service_module.TRAINING_JOBS._cancel_events.clear()

    def test_interrupted_training_job_does_not_resume_as_running_after_restart(self) -> None:
        """PASSING BASELINE -- required scenario G (interrupted training
        job). A job record injected as "running" -- simulating a job
        genuinely still in flight at the moment of a real process restart,
        without depending on racy real background-thread timing -- is
        simply not present in the checkpoint file at all (TRAINING_JOBS is
        never serialized), and correctly 404s after restart: never falsely
        reported as "running" with no worker actually computing it.
        """
        client, user_id, project_id, job_id = _create_real_training_job("ckpt-interrupted")
        _wait_for_terminal_job(client, job_id, project_id)  # let the real background thread finish cleanly first

        fake_job_id = f"train-job-{uuid.uuid4().hex}"
        with training_job_service_module.TRAINING_JOBS._lock:
            base_job = dict(training_job_service_module.TRAINING_JOBS._jobs[job_id])
            base_job.update({"job_id": fake_job_id, "overall_status": "running"})
            training_job_service_module.TRAINING_JOBS._jobs[fake_job_id] = base_job
            training_job_service_module.TRAINING_JOBS._project_job_ids.setdefault((user_id, project_id), []).append(fake_job_id)

        self.assertTrue(session_checkpoint_module.save_checkpoint())
        raw_contents = session_checkpoint_module.CHECKPOINT_PATH.read_text(encoding="utf-8")
        self.assertNotIn(fake_job_id, raw_contents, "TRAINING_JOBS must never be written into the checkpoint file at all.")
        self.assertNotIn("overall_status", raw_contents, "The checkpoint file must contain no job-record fields whatsoever.")

        self._clear_training_jobs()
        self.assertTrue(_simulate_restart())

        post_restart = client.get(f"/api/model/train/jobs/{fake_job_id}", params={"project_id": project_id})
        self.assertEqual(post_restart.status_code, 404, post_restart.text)

    def test_completed_job_result_survives_restart_in_correct_scope_only(self) -> None:
        """PASSING BASELINE -- required scenario H (completed training job
        and result). The job RECORD itself does not survive restart (by
        design), but its real output (RESULTS) does, in its original
        owner/project scope only.
        """
        client, user_id, project_id, job_id = _create_real_training_job("ckpt-completed-result")
        final = _wait_for_terminal_job(client, job_id, project_id)
        self.assertEqual(final["overall_status"], "complete", final)

        self.assertTrue(session_checkpoint_module.save_checkpoint())
        self._clear_training_jobs()
        self.assertTrue(_simulate_restart())

        post_restart_job = client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_id})
        self.assertEqual(post_restart_job.status_code, 404, post_restart_job.text)

        restored_summary = get_scoped_result_store((user_id, project_id)).get_last_summary()
        self.assertIsNotNone(restored_summary)
        self.assertEqual(restored_summary["training_job_id"], job_id)
        last_response = client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(last_response.status_code, 200, last_response.text)
        self.assertEqual(last_response.json()["summary"]["training_job_id"], job_id)


class CheckpointAtomicWriteTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (new in Stage 6) -- required scenario I (atomic
    save): a failed temporary-file write must leave the previous good
    checkpoint completely intact.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()
        self._original_checkpoint_path = session_checkpoint_module.CHECKPOINT_PATH
        self._temp_dir = Path(tempfile.mkdtemp(prefix="atlas_checkpoint_atomic_test_"))
        session_checkpoint_module.CHECKPOINT_PATH = self._temp_dir / "workflow_checkpoint.json"

    def tearDown(self) -> None:
        session_checkpoint_module.CHECKPOINT_PATH = self._original_checkpoint_path
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._restore_global_stores()

    def test_failed_temp_write_leaves_previous_checkpoint_intact(self) -> None:
        client, user_id = _register("ckpt-atomic")
        project_id = _create_project(client, "Checkpoint Atomic Project")
        get_scoped_dataset_store((user_id, project_id)).set_raw(pd.DataFrame({"marker": ["GOOD-CHECKPOINT"]}))
        self.assertTrue(session_checkpoint_module.save_checkpoint())
        good_contents = session_checkpoint_module.CHECKPOINT_PATH.read_text(encoding="utf-8")
        self.assertIn("GOOD-CHECKPOINT", good_contents)

        original_write_text = Path.write_text

        def failing_write_text(self_path: Path, *args: Any, **kwargs: Any) -> int:
            if self_path.suffix == ".tmp":
                raise OSError("simulated disk failure during checkpoint write")
            return original_write_text(self_path, *args, **kwargs)

        get_scoped_dataset_store((user_id, project_id)).set_raw(pd.DataFrame({"marker": ["SHOULD-NOT-BE-SAVED"]}))
        with unittest.mock.patch.object(Path, "write_text", failing_write_text):
            result = session_checkpoint_module.save_checkpoint()
        self.assertFalse(result)

        post_failure_contents = session_checkpoint_module.CHECKPOINT_PATH.read_text(encoding="utf-8")
        self.assertEqual(post_failure_contents, good_contents, "A failed save must leave the previous good checkpoint byte-for-byte intact.")
        self.assertNotIn("SHOULD-NOT-BE-SAVED", post_failure_contents)

        leftover_temp_files = list(session_checkpoint_module.CHECKPOINT_PATH.parent.glob("*.tmp"))
        self.assertEqual(leftover_temp_files, [], f"A failed save must clean up its own temp file: {leftover_temp_files}")


class CheckpointCorruptionAndVersioningTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (new in Stage 6) -- required scenarios J (corrupt
    checkpoint), K (legacy checkpoint), L (unsupported version).
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()
        self._original_checkpoint_path = session_checkpoint_module.CHECKPOINT_PATH
        self._temp_dir = Path(tempfile.mkdtemp(prefix="atlas_checkpoint_corrupt_test_"))
        session_checkpoint_module.CHECKPOINT_PATH = self._temp_dir / "workflow_checkpoint.json"

    def tearDown(self) -> None:
        session_checkpoint_module.CHECKPOINT_PATH = self._original_checkpoint_path
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._restore_global_stores()

    def test_corrupt_checkpoint_fails_safely_without_partial_restore(self) -> None:
        """Required scenario J: invalid JSON fails safe -- no restoration,
        no crash, and the corrupt file itself is left untouched for
        inspection (load_checkpoint() never writes to the file).
        """
        client, user_id = _register("ckpt-corrupt")
        project_id = _create_project(client, "Checkpoint Corrupt Project")
        get_scoped_dataset_store((user_id, project_id)).set_raw(pd.DataFrame({"marker": ["PRE-EXISTING"]}))

        session_checkpoint_module.CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        session_checkpoint_module.CHECKPOINT_PATH.write_text("{not valid json!!!", encoding="utf-8")
        result = session_checkpoint_module.load_checkpoint()
        self.assertFalse(result)

        self.assertEqual(list(get_scoped_dataset_store((user_id, project_id)).raw_df["marker"]), ["PRE-EXISTING"])
        self.assertEqual(session_checkpoint_module.CHECKPOINT_PATH.read_text(encoding="utf-8"), "{not valid json!!!")

    def test_malformed_checkpoint_missing_scope_lists_fails_safely(self) -> None:
        """A checkpoint with a current schema_version but missing the
        expected scope-list structure fails safe (no restoration), rather
        than crashing or partially restoring.
        """
        session_checkpoint_module.CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        session_checkpoint_module.CHECKPOINT_PATH.write_text(
            json.dumps({"schema_version": session_checkpoint_module.CHECKPOINT_SCHEMA_VERSION, "saved_at": "now"}),
            encoding="utf-8",
        )
        result = session_checkpoint_module.load_checkpoint()
        self.assertFalse(result)

    def test_legacy_checkpoint_loads_only_into_non_http_reachable_scope(self) -> None:
        """Required scenario K: a pre-Stage-6 legacy checkpoint (no
        schema_version, flat {"dataset", "results"} shape) is loaded ONLY
        into the non-HTTP-reachable LEGACY_SCOPE -- never mapped to a real,
        authenticated user or project.
        """
        legacy_payload = {
            "dataset": {
                "raw_df": {"__atlas_type__": "dataframe", "payload": json.loads(pd.DataFrame({"marker": ["LEGACY-DATA"]}).to_json(orient="split"))},
                "processed_df": None, "target": None, "X_train": None, "X_test": None, "y_train": None, "y_test": None, "meta": {},
            },
            "results": {
                "last_training_summary": {"marker": "LEGACY-RESULT"}, "training_timestamp": None,
                "model_availability": {}, "model_artifacts": {}, "final_model_metadata": None, "scoring_reference": None,
            },
        }
        session_checkpoint_module.CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        session_checkpoint_module.CHECKPOINT_PATH.write_text(json.dumps(legacy_payload), encoding="utf-8")
        result = session_checkpoint_module.load_checkpoint()
        self.assertTrue(result)

        legacy_scope = session_checkpoint_module.LEGACY_SCOPE
        self.assertEqual(legacy_scope, ("anonymous", dataset_store_module.UNSCOPED_PROJECT))
        restored_df = get_scoped_dataset_store(legacy_scope).raw_df
        self.assertIsNotNone(restored_df)
        self.assertEqual(list(restored_df["marker"]), ["LEGACY-DATA"])
        restored_result = get_scoped_result_store(legacy_scope).get_last_summary()
        self.assertEqual(restored_result["marker"], "LEGACY-RESULT")

        # Never exposed through a real authenticated project: UNSCOPED_PROJECT
        # is never a real, persisted project_id, so a real user requesting it
        # still 404s exactly as any other never-created project would.
        client, user_id = _register("ckpt-legacy-check")
        self.assertNotEqual(user_id, "anonymous")
        response = client.get("/api/data/get_sample", params={"project_id": dataset_store_module.UNSCOPED_PROJECT})
        self.assertEqual(response.status_code, 404, response.text)

    def test_unsupported_schema_version_fails_safely(self) -> None:
        """Required scenario L: an unrecognized schema_version fails safe
        (no restoration), rather than guessing at how to interpret it.
        """
        client, user_id = _register("ckpt-version")
        project_id = _create_project(client, "Checkpoint Version Project")
        get_scoped_dataset_store((user_id, project_id)).set_raw(pd.DataFrame({"marker": ["PRE-EXISTING"]}))

        session_checkpoint_module.CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        session_checkpoint_module.CHECKPOINT_PATH.write_text(
            json.dumps({"schema_version": 999, "datastore_scopes": [], "results_scopes": []}),
            encoding="utf-8",
        )
        result = session_checkpoint_module.load_checkpoint()
        self.assertFalse(result)
        self.assertEqual(list(get_scoped_dataset_store((user_id, project_id)).raw_df["marker"]), ["PRE-EXISTING"])


class CheckpointSubprocessRestartTests(unittest.TestCase):
    """PASSING BASELINE (new in Stage 6) -- required subprocess-based /
    genuinely fresh-process restart verification (requirements #29-30).
    Every OTHER checkpoint test in this file "simulates restart" by
    clearing the in-memory _DATASTORES/_RESULT_STORES dicts within the SAME
    test process -- fast and sufficient for exercising the save/load LOGIC,
    but it cannot by itself prove there is no reliance on some other piece
    of same-process state a real restart would also clear. This class
    spawns two genuinely separate Python subprocesses -- a writer, which
    saves a checkpoint and exits, and a reader, which starts with
    completely fresh module-level state (a brand-new process import of
    server.core.session_checkpoint/dataset_store/result_store, so
    _DATASTORES/_RESULT_STORES start as literally new, empty dicts, not
    merely .clear()'d ones) and loads it -- the strongest practical proof
    available short of a full uvicorn server restart (covered separately by
    live verification).
    """

    @classmethod
    def setUpClass(cls) -> None:
        # Stage 6.1: this class now registers real users/projects (see the
        # test body), so it needs initialized security/persistence stores of
        # its own -- sibling classes delete the DB files in tearDownClass.
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._temp_dir = Path(tempfile.mkdtemp(prefix="atlas_checkpoint_subprocess_test_"))
        self._checkpoint_path = self._temp_dir / "workflow_checkpoint.json"

    def tearDown(self) -> None:
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def _run(self, script: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["ATLAS_CHECKPOINT_TEST_PATH"] = str(self._checkpoint_path)
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_two_users_two_projects_survive_a_genuine_fresh_process_restart(self) -> None:
        # Stage 6.1: save/load now filter out scopes whose owner or project
        # does not exist (deleted-scope garbage collection), so the two
        # identities must be REAL registered users and REAL persisted
        # projects -- created here in the parent against the same isolated
        # security/persistence databases the subprocesses inherit via env.
        client_a, user_a_id = _register("subproc-a")
        client_b, user_b_id = _register("subproc-b")
        project_a = _create_project(client_a, "Checkpoint Subprocess Project A")
        project_b = _create_project(client_b, "Checkpoint Subprocess Project B")

        writer_script = f"""
import os, sys
sys.path.insert(0, {str(ROOT)!r})
import server.core.session_checkpoint as ckpt
from pathlib import Path
ckpt.CHECKPOINT_PATH = Path(os.environ["ATLAS_CHECKPOINT_TEST_PATH"])
from server.core.dataset_store import get_scoped_dataset_store
from server.core.result_store import get_scoped_result_store
import pandas as pd

get_scoped_dataset_store(({user_a_id!r}, {project_a!r})).set_raw(pd.DataFrame({{"marker": ["SUBPROC-A"]}}))
get_scoped_dataset_store(({user_b_id!r}, {project_b!r})).set_raw(pd.DataFrame({{"marker": ["SUBPROC-B"]}}))
get_scoped_result_store(({user_a_id!r}, {project_a!r})).set_last_summary({{"marker": "SUBPROC-A-RESULT"}})
get_scoped_result_store(({user_b_id!r}, {project_b!r})).set_last_summary({{"marker": "SUBPROC-B-RESULT"}})
ok = ckpt.save_checkpoint()
print("SAVE_OK" if ok else "SAVE_FAILED")
"""
        writer_result = self._run(writer_script)
        self.assertEqual(writer_result.returncode, 0, writer_result.stderr)
        self.assertIn("SAVE_OK", writer_result.stdout)
        self.assertTrue(self._checkpoint_path.exists())

        reader_script = f"""
import os, sys, json
sys.path.insert(0, {str(ROOT)!r})
import server.core.session_checkpoint as ckpt
from pathlib import Path
ckpt.CHECKPOINT_PATH = Path(os.environ["ATLAS_CHECKPOINT_TEST_PATH"])
from server.core.dataset_store import get_scoped_dataset_store
from server.core.result_store import get_scoped_result_store

ok = ckpt.load_checkpoint()
a_df = get_scoped_dataset_store(({user_a_id!r}, {project_a!r})).raw_df
b_df = get_scoped_dataset_store(({user_b_id!r}, {project_b!r})).raw_df
a_result = get_scoped_result_store(({user_a_id!r}, {project_a!r})).get_last_summary()
b_result = get_scoped_result_store(({user_b_id!r}, {project_b!r})).get_last_summary()
report = {{
    "load_ok": ok,
    "a_marker": list(a_df["marker"]) if a_df is not None else None,
    "b_marker": list(b_df["marker"]) if b_df is not None else None,
    "a_result_marker": (a_result or {{}}).get("marker"),
    "b_result_marker": (b_result or {{}}).get("marker"),
    "cross_a_in_b_scope": get_scoped_dataset_store(({user_a_id!r}, {project_b!r})).raw_df is not None,
}}
print(json.dumps(report))
"""
        reader_result = self._run(reader_script)
        self.assertEqual(reader_result.returncode, 0, reader_result.stderr)
        report = json.loads(reader_result.stdout.strip().splitlines()[-1])
        self.assertTrue(report["load_ok"])
        self.assertEqual(report["a_marker"], ["SUBPROC-A"])
        self.assertEqual(report["b_marker"], ["SUBPROC-B"])
        self.assertEqual(report["a_result_marker"], "SUBPROC-A-RESULT")
        self.assertEqual(report["b_result_marker"], "SUBPROC-B-RESULT")
        self.assertFalse(report["cross_a_in_b_scope"], "User A's project-A data must not appear under project B.")


class TrainingJobIsolationTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (promoted in Stage 4; see the module docstring's
    "STAGE 4 FIX" section and the "Tests that changed classification in
    Stage 4" list). Covers TRAINING_JOBS AUTHORIZATION: ownership fields,
    unauthorized read/cancel, guessed job_id, and the Option-A collaborator
    boundary. TrainingJobProjectIsolationTests (below) covers project-scope
    ISOLATION (same user/two projects, two tabs, background-thread scope,
    completed/failed/cancelled job publication) -- mirroring the DATASTORE/
    RESULTS split between *ProjectIsolationTests and *AuthorizationTests
    used elsewhere in this file.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()

    def tearDown(self) -> None:
        self._restore_global_stores()

    def _create_real_job(
        self,
        label: str,
        client: TestClient | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        models: list | None = None,
    ) -> tuple[TestClient, str, str, str]:
        return _create_real_training_job(label, client=client, user_id=user_id, project_id=project_id, models=models)

    def test_job_record_has_explicit_owner_and_project_fields(self) -> None:
        """PASSING BASELINE (inverted from its Stage 2B/3-era finding -- see
        the module docstring's "Tests that changed classification in Stage
        4" list). The public job record now carries a real, request-
        verified `owner_user_id` (from require_user()/authorize_modeling_
        scope, not client input) alongside `project_id` -- distinct from
        the pre-existing `contract.user`, which remains free-text and
        client-supplied, and is intentionally NOT used for authorization.
        """
        client_a, user_a_id, project_a, job_id = self._create_real_job("ownership-fields")
        job = _wait_for_terminal_job(client_a, job_id, project_a)

        self.assertIn("project_id", job)
        self.assertEqual(job["project_id"], project_a)
        self.assertIn("owner_user_id", job)
        self.assertEqual(job["owner_user_id"], user_a_id)
        self.assertIn("user", job["contract"])
        self.assertEqual(job["contract"]["user"], "ownership-fields")  # still client-supplied, unverified, unused for authorization

    def test_unrelated_user_is_denied_job_read_with_403(self) -> None:
        """PASSING BASELINE -- required scenario (unauthorized user job
        read). Formerly test_unrelated_authenticated_user_can_currently_view_another_users_job,
        which proved the opposite. A stranger with zero relationship to the
        job's project is now rejected at the project-authorization gate,
        before any job lookup, and never sees the job's contract/data.
        """
        client_a, user_a_id, project_a, job_id = self._create_real_job("cross-view-a")
        client_b, user_b_id = _register("cross-view-b")
        self.assertNotEqual(user_a_id, user_b_id)

        response = client_b.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_a})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn(project_a, response.text)

    def test_unrelated_user_is_denied_job_cancel_with_403(self) -> None:
        """PASSING BASELINE -- required scenario (unauthorized user job
        cancellation). Formerly test_unrelated_authenticated_user_can_currently_cancel_another_users_job.
        The destructive action is now rejected at the project-authorization
        gate; User A's job is completely unaffected by the attempt.
        """
        client_a, user_a_id, project_a, job_id = self._create_real_job("cross-cancel-a")
        client_b, user_b_id = _register("cross-cancel-b")
        self.assertNotEqual(user_a_id, user_b_id)

        response = client_b.post(f"/api/model/train/jobs/{job_id}/cancel", params={"project_id": project_a})
        self.assertEqual(response.status_code, 403, response.text)

        # User A's own view of the job is unaffected by the denied attempt.
        after = _wait_for_terminal_job(client_a, job_id, project_a)
        self.assertEqual(after["overall_status"], "complete", after)

    def test_unrelated_user_is_denied_result_retrieval_with_403(self) -> None:
        """PASSING BASELINE -- required scenario (unauthorized user result
        retrieval). Once the job has actually COMPLETED (unlike the read/
        cancel tests above, which act on a still-running job), a stranger
        still cannot retrieve its results (the job's own `summary` field,
        or the project's /train/last) -- both denied with 403, neither
        exposes any of User A's real data.
        """
        client_a, user_a_id, project_a, job_id = self._create_real_job("cross-result-a")
        completed = _wait_for_terminal_job(client_a, job_id, project_a)
        self.assertEqual(completed["overall_status"], "complete", completed)

        client_b, user_b_id = _register("cross-result-b")
        job_response = client_b.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_a})
        self.assertEqual(job_response.status_code, 403, job_response.text)

        last_response = client_b.get("/api/train/last", params={"project_id": project_a})
        self.assertEqual(last_response.status_code, 403, last_response.text)

    def test_missing_project_id_is_rejected_on_job_endpoints(self) -> None:
        """PASSING BASELINE -- required scenario (missing project_id).
        Every job-touching endpoint rejects a request with no project_id at
        all: 422 for the Pydantic-modeled POST /model/train/jobs (project_id
        is a required field with no default), 422 for the Query(...)-typed
        GET endpoints.
        """
        client, _user_id = _register("jobs-missing-project-id")
        payload = _training_job_payload("placeholder", "v1", "fm-v1", "split-v1", "missing-project-id")
        del payload["project_id"]
        create_response = client.post("/api/model/train/jobs", json=payload)
        self.assertEqual(create_response.status_code, 422, create_response.text)

        active_response = client.get("/api/model/train/jobs/active")
        self.assertEqual(active_response.status_code, 422, active_response.text)

        get_response = client.get("/api/model/train/jobs/some-job-id")
        self.assertEqual(get_response.status_code, 422, get_response.text)

    def test_blank_project_id_is_rejected_on_job_endpoints(self) -> None:
        """PASSING BASELINE -- required scenario (blank project_id). A
        whitespace-only project_id satisfies type validation but is
        rejected by authorize_modeling_scope's own non-blank check (400).
        """
        client, _user_id = _register("jobs-blank-project-id")
        payload = _training_job_payload("   ", "v1", "fm-v1", "split-v1", "blank-project-id")
        create_response = client.post("/api/model/train/jobs", json=payload)
        self.assertEqual(create_response.status_code, 400, create_response.text)

        active_response = client.get("/api/model/train/jobs/active", params={"project_id": "   "})
        self.assertEqual(active_response.status_code, 400, active_response.text)

    def test_nonexistent_project_id_returns_404_and_creates_no_job(self) -> None:
        """PASSING BASELINE -- required scenario (nonexistent project_id).
        A syntactically valid but never-created project_id 404s on job
        creation and on every job-scoped read, without creating any job.
        """
        client, user_id = _register("jobs-authz-404")
        fake_project_id = f"proj-does-not-exist-{uuid.uuid4().hex[:12]}"
        payload = _training_job_payload(fake_project_id, "v1", "fm-v1", "split-v1", "authz-404")
        create_response = client.post("/api/model/train/jobs", json=payload)
        self.assertEqual(create_response.status_code, 404, create_response.text)

        active_response = client.get("/api/model/train/jobs/active", params={"project_id": fake_project_id})
        self.assertEqual(active_response.status_code, 404, active_response.text)
        self.assertNotIn((user_id, fake_project_id), training_job_service_module.TRAINING_JOBS._project_job_ids)

    def test_collaborator_cannot_read_or_cancel_another_collaborators_job_by_guessing_its_id(self) -> None:
        """PASSING BASELINE -- required scenarios (authorized collaborator
        read behavior; guessed job ID from another user). A collaborator
        who IS authorized for the project (unlike a stranger, above) still
        cannot read, cancel, or otherwise access the OWNER's own job by
        obtaining/guessing its real job_id -- correctly indistinguishable
        from a nonexistent job (404), per Option A (the module docstring's
        "STAGE 4 FIX" -- STATUS CODE MAPPING section): project-level
        authorization is necessary but not sufficient for job-level access.
        """
        owner_client, owner_id, project_id, job_id = self._create_real_job("collab-guess-owner")
        collaborator_client, collaborator_id = _register("collab-guess-collab")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)
        _share_project(owner_client, project_id, collaborator_id, "edit")

        read_response = collaborator_client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_id})
        self.assertEqual(read_response.status_code, 404, read_response.text)

        cancel_response = collaborator_client.post(f"/api/model/train/jobs/{job_id}/cancel", params={"project_id": project_id})
        self.assertEqual(cancel_response.status_code, 404, cancel_response.text)

        # The owner's own job is completely unaffected by the collaborator's
        # denied attempts.
        owner_view = _wait_for_terminal_job(owner_client, job_id, project_id)
        self.assertEqual(owner_view["overall_status"], "complete", owner_view)

    def test_collaborator_with_edit_access_can_create_their_own_independent_job(self) -> None:
        """PASSING BASELINE -- required scenario (authorized collaborator
        mutation behavior). A collaborator granted "edit" access can create
        their OWN, entirely independent training job in the shared
        project -- tracked under their own (owner_user_id, project_id)
        entry, invisible in the owner's own /model/train/jobs/active
        listing, and not a mutation of the owner's job in any way.
        """
        owner_client, owner_id, project_id, owner_job_id = self._create_real_job("collab-edit-owner")
        collaborator_client, collaborator_id = _register("collab-edit-collab")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)
        _share_project(owner_client, project_id, collaborator_id, "edit")

        # Owner's job must finish before the collaborator reuses the same
        # governed split/manifest (both scoped to (user, project), so the
        # collaborator's own DATASTORE scope for this SAME project is
        # independently seeded below -- Option A applies to DATASTORE too).
        _wait_for_terminal_job(owner_client, owner_job_id, project_id)

        _, collaborator_user_id, _, collaborator_job_id = self._create_real_job(
            "collab-edit-collab-job", client=collaborator_client, user_id=collaborator_id, project_id=project_id
        )
        self.assertNotEqual(collaborator_job_id, owner_job_id)
        collaborator_final = _wait_for_terminal_job(collaborator_client, collaborator_job_id, project_id)
        self.assertEqual(collaborator_final["overall_status"], "complete", collaborator_final)
        self.assertEqual(collaborator_final["owner_user_id"], collaborator_user_id)

        # The collaborator's active-jobs listing never includes the owner's
        # job (both are terminal by now, but the ownership index itself is
        # checked directly for a stronger guarantee than "nothing active").
        self.assertIn((collaborator_user_id, project_id), training_job_service_module.TRAINING_JOBS._project_job_ids)
        collaborator_job_ids = training_job_service_module.TRAINING_JOBS._project_job_ids[(collaborator_user_id, project_id)]
        self.assertIn(collaborator_job_id, collaborator_job_ids)
        self.assertNotIn(owner_job_id, collaborator_job_ids)

        # The owner's own job/result is untouched by the collaborator's
        # independent job.
        owner_final = _wait_for_terminal_job(owner_client, owner_job_id, project_id)
        self.assertEqual(owner_final["owner_user_id"], owner_id)


class TrainingJobProjectIsolationTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (new in Stage 4). TRAINING_JOBS analogue of
    ResultsProjectIsolationTests/MissingProjectIsolationTests: covers
    project-scope ISOLATION (as opposed to TrainingJobIsolationTests'
    AUTHORIZATION focus) -- same user/two projects, two tabs, interleaved
    creation and polling, returning to project A after project B, cross-
    user isolation of the (owner_user_id, project_id) index, background-
    thread scope preservation, and correct RESULTS publication/isolation
    across completed, failed, and cancelled terminal states.

    Uses lightweight training configurations throughout (a single "logreg"
    model, k_folds=2, tiny synthetic frames via _build_frame) -- these
    tests exercise the REAL background-thread job pipeline end-to-end, not
    a mock, so keeping runs fast matters for overall suite time.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()

    def tearDown(self) -> None:
        self._restore_global_stores()

    def test_same_user_two_projects_jobs_do_not_collide(self) -> None:
        """PASSING BASELINE -- required scenario (same user, two projects).
        A single user's two real projects each get their own training job;
        neither job is visible under the other project's scope.
        """
        client, user_id, project_a, job_a_id = _create_real_training_job("tj-same-user-a")
        _, _, project_b, job_b_id = _create_real_training_job("tj-same-user-b", client=client, user_id=user_id)

        final_a = _wait_for_terminal_job(client, job_a_id, project_a)
        final_b = _wait_for_terminal_job(client, job_b_id, project_b)
        self.assertEqual(final_a["overall_status"], "complete", final_a)
        self.assertEqual(final_b["overall_status"], "complete", final_b)

        cross_a = client.get(f"/api/model/train/jobs/{job_a_id}", params={"project_id": project_b})
        self.assertEqual(cross_a.status_code, 404, cross_a.text)
        cross_b = client.get(f"/api/model/train/jobs/{job_b_id}", params={"project_id": project_a})
        self.assertEqual(cross_b.status_code, 404, cross_b.text)

    def test_two_browser_tabs_different_projects_interleaved_creation_and_polling(self) -> None:
        """PASSING BASELINE -- required scenarios (two browser tabs with
        different projects; interleaved job creation and polling). Same
        authenticated session, two logical tabs, each creates and polls a
        job for a DIFFERENT project, interleaved -- neither tab's job or
        poll result is ever affected by the other's.
        """
        client_tab1, user_id = _register("tj-two-tabs-user")
        session_cookie = client_tab1.cookies.get(SESSION_COOKIE_NAME)
        self.assertTrue(session_cookie, "Registration must issue a session cookie.")
        project_a = _create_project(client_tab1, "TJ Two Tabs Project A")
        project_b = _create_project(client_tab1, "TJ Two Tabs Project B")

        client_tab2 = TestClient(app)
        client_tab2.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        _, _, _, job_a_id = _create_real_training_job("tj-tabs-a", client=client_tab1, user_id=user_id, project_id=project_a)
        _, _, _, job_b_id = _create_real_training_job("tj-tabs-b", client=client_tab2, user_id=user_id, project_id=project_b)

        # Interleave polling: tab1 polls A, tab2 polls B, tab1 polls A again.
        poll_a_1 = client_tab1.get(f"/api/model/train/jobs/{job_a_id}", params={"project_id": project_a})
        poll_b_1 = client_tab2.get(f"/api/model/train/jobs/{job_b_id}", params={"project_id": project_b})
        poll_a_2 = client_tab1.get(f"/api/model/train/jobs/{job_a_id}", params={"project_id": project_a})
        self.assertEqual(poll_a_1.status_code, 200, poll_a_1.text)
        self.assertEqual(poll_b_1.status_code, 200, poll_b_1.text)
        self.assertEqual(poll_a_2.status_code, 200, poll_a_2.text)
        self.assertEqual(poll_a_1.json()["project_id"], project_a)
        self.assertEqual(poll_b_1.json()["project_id"], project_b)
        self.assertEqual(poll_a_2.json()["job_id"], job_a_id)

        # Cross-project access is denied even from the "matching" tab if it
        # supplies the wrong project_id.
        cross = client_tab1.get(f"/api/model/train/jobs/{job_b_id}", params={"project_id": project_a})
        self.assertEqual(cross.status_code, 404, cross.text)

    def test_returning_to_project_a_after_creating_job_in_project_b(self) -> None:
        """PASSING BASELINE -- required scenario (return to project A after
        creating a job in project B). Sequential: create+complete a job in
        A, create+complete a different job in B, then confirm A's listing
        and job detail are exactly as they were, untouched by B.
        """
        client, user_id, project_a, job_a_id = _create_real_training_job("tj-return-a")
        first_read = _wait_for_terminal_job(client, job_a_id, project_a)
        self.assertEqual(first_read["overall_status"], "complete", first_read)

        _, _, project_b, job_b_id = _create_real_training_job("tj-return-b", client=client, user_id=user_id)
        final_b = _wait_for_terminal_job(client, job_b_id, project_b)
        self.assertEqual(final_b["overall_status"], "complete", final_b)

        return_to_a = client.get(f"/api/model/train/jobs/{job_a_id}", params={"project_id": project_a})
        self.assertEqual(return_to_a.status_code, 200, return_to_a.text)
        self.assertEqual(return_to_a.json()["project_id"], project_a)
        self.assertEqual(return_to_a.json()["job_id"], job_a_id)

        active_a = client.get("/api/model/train/jobs/active", params={"project_id": project_a})
        self.assertEqual(active_a.status_code, 200, active_a.text)
        active_a_ids = {job["job_id"] for job in active_a.json()["jobs"]}
        self.assertNotIn(job_b_id, active_a_ids)

    def test_two_users_separate_projects_job_index_is_isolated(self) -> None:
        """PASSING BASELINE -- required scenario (two users with separate
        projects). Complements BackgroundContextTests' end-to-end RESULTS
        check with a direct, timing-independent check of the structured
        (owner_user_id, project_id) job index itself -- both jobs are tiny
        and may already be terminal by the time this runs, so this checks
        the persistent index rather than the transient active() listing.
        """
        client_a, user_a_id, project_a, job_a_id = _create_real_training_job("tj-two-users-a")
        client_b, user_b_id, project_b, job_b_id = _create_real_training_job("tj-two-users-b")
        self.assertNotEqual(user_a_id, user_b_id)
        _wait_for_terminal_job(client_a, job_a_id, project_a)
        _wait_for_terminal_job(client_b, job_b_id, project_b)

        index = training_job_service_module.TRAINING_JOBS._project_job_ids
        a_job_ids = index.get((user_a_id, project_a), [])
        b_job_ids = index.get((user_b_id, project_b), [])
        self.assertIn(job_a_id, a_job_ids)
        self.assertIn(job_b_id, b_job_ids)
        self.assertNotIn(job_b_id, a_job_ids)
        self.assertNotIn(job_a_id, b_job_ids)

    def test_background_thread_preserves_owner_and_project_scope(self) -> None:
        """PASSING BASELINE -- required scenario (background-thread scope
        preservation). owner_user_id/project_id are set once, on the
        request thread, at job creation (training_job_service.py's module
        comment) -- this test confirms they survive unchanged through the
        job's full background-thread lifecycle (queued -> preparing ->
        running -> complete), proving the explicit-capture strategy, not
        contextvar propagation, is what keeps the job correctly scoped. See
        BackgroundContextTests.test_bare_thread_does_not_inherit_active_user_context
        for the proof that contextvar propagation itself is NOT available.
        """
        client, user_id, project_id, job_id = _create_real_training_job("tj-bg-scope")
        immediate = client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_id})
        self.assertEqual(immediate.status_code, 200, immediate.text)
        self.assertEqual(immediate.json()["owner_user_id"], user_id)
        self.assertEqual(immediate.json()["project_id"], project_id)

        final = _wait_for_terminal_job(client, job_id, project_id)
        self.assertEqual(final["overall_status"], "complete", final)
        self.assertEqual(final["owner_user_id"], user_id)
        self.assertEqual(final["project_id"], project_id)

    def test_completed_job_publishes_into_correct_results_scope(self) -> None:
        """PASSING BASELINE -- required scenario (completed job publication
        into the correct RESULTS scope). Complements Stage 3's RESULTS
        tests with an explicit check that a completed TRAINING_JOBS run
        lands its summary in the SAME (user_id, project_id) RESULTS scope
        the job itself belongs to, readable back through the real,
        authorized /train/last endpoint.
        """
        client, user_id, project_id, job_id = _create_real_training_job("tj-complete-results")
        final = _wait_for_terminal_job(client, job_id, project_id)
        self.assertEqual(final["overall_status"], "complete", final)

        summary = get_scoped_result_store((user_id, project_id)).get_last_summary()
        self.assertIsNotNone(summary)
        self.assertEqual(summary["training_job_id"], job_id)
        self.assertEqual(summary["project_id"], project_id)

        last_response = client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(last_response.status_code, 200, last_response.text)
        self.assertEqual(last_response.json()["summary"]["training_job_id"], job_id)

    def test_failed_job_is_isolated_and_does_not_leak_into_other_projects(self) -> None:
        """PASSING BASELINE -- required scenario (failed job isolation). A
        job that fails (every requested model errors) still correctly
        records its owner_user_id/project_id, and does not affect a
        completely separate user/project's own, independently successful
        job.
        """
        original_train_models = training_job_service_module.train_models

        def always_fail(*args, **kwargs):
            requested = kwargs.get("requested_models") or ["unknown"]
            return {"ok": False, "error": "intentional isolated failure", "model": requested[0]}

        training_job_service_module.train_models = always_fail
        try:
            client, user_id, project_id, job_id = _create_real_training_job("tj-failed")
            final = _wait_for_terminal_job(client, job_id, project_id)
        finally:
            training_job_service_module.train_models = original_train_models

        self.assertEqual(final["overall_status"], "failed", final)
        self.assertEqual(final["owner_user_id"], user_id)
        self.assertEqual(final["project_id"], project_id)

        other_client, other_user_id, other_project, other_job_id = _create_real_training_job("tj-failed-other")
        other_final = _wait_for_terminal_job(other_client, other_job_id, other_project)
        self.assertEqual(other_final["overall_status"], "complete", other_final)
        self.assertNotEqual(other_user_id, user_id)

    def test_cancelled_job_is_isolated_and_does_not_leak_into_other_projects(self) -> None:
        """PASSING BASELINE -- required scenario (cancelled job isolation).
        A cancelled job still correctly records its owner_user_id/
        project_id, and remains just as inaccessible to a stranger as any
        other terminal-state job.
        """
        original_train_models = training_job_service_module.train_models

        def slow_model(*args, **kwargs):
            time.sleep(0.3)
            return original_train_models(*args, **kwargs)

        training_job_service_module.train_models = slow_model
        try:
            client, user_id, project_id, job_id = _create_real_training_job("tj-cancelled")
            cancel_response = client.post(f"/api/model/train/jobs/{job_id}/cancel", params={"project_id": project_id})
            self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
            final = _wait_for_terminal_job(client, job_id, project_id)
        finally:
            training_job_service_module.train_models = original_train_models

        self.assertEqual(final["overall_status"], "cancelled", final)
        self.assertEqual(final["owner_user_id"], user_id)
        self.assertEqual(final["project_id"], project_id)

        stranger_client, _stranger_id = _register("tj-cancelled-stranger")
        stranger_response = stranger_client.get(f"/api/model/train/jobs/{job_id}", params={"project_id": project_id})
        self.assertEqual(stranger_response.status_code, 403, stranger_response.text)


class ResultsCollaboratorPolicyTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """PASSING BASELINE (Stage 3). Formerly CollaboratorVisibilityTests.

    Before Stage 3, RESULTS had no project awareness at all -- it was
    scoped purely per-user, with no `authorize_modeling_scope` call
    anywhere. An unrelated stranger was correctly denied (Stage 2A's user
    isolation), but for the WRONG reason: they simply had their own,
    separate, empty per-user RESULTS bucket, not because any project-level
    authorization check ran. An authorized collaborator fared no better
    than a stranger -- also just a different user with their own empty
    bucket -- which was a KNOWN LIMITATION, since collaborators had no
    principled way to be treated differently from strangers at all.

    Stage 3 fixes this properly: every RESULTS-touching endpoint now calls
    the same `authorize_modeling_scope` DATASTORE already uses, so a
    stranger is denied WITH a real project-authorization check (403), and a
    collaborator is correctly let PAST that same check. What happens next
    is this stage's key decision:

    DECISION (restated from the module docstring's "STAGE 3 FIX" section):
    RESULTS is OPTION A, user-and-project-private, same as DATASTORE -- an
    authorized collaborator is let past authorization but still resolves
    their OWN, independent, initially-empty RESULTS scope for the project,
    never the owner's actual committed result. This was a genuine decision,
    not a default: Option B (project-shared RESULTS, keyed by project_id
    alone) was considered and rejected because it would trade today's
    cross-project collision bug for a NEW collaborator-vs-collaborator
    collision (concurrent training on a shared project silently clobbering
    each other's "last result"), and because real shared committed
    artifacts belong in the durable persistence layer, not an in-memory
    cache widened by dropping its user dimension -- see the module
    docstring for the complete reasoning.

    test_authorized_collaborator_gets_own_independent_results_scope (below)
    is therefore PROMOTED from KNOWN LIMITATION to PASSING BASELINE: the
    observable outcome (collaborator sees nothing of the owner's result) is
    unchanged from before Stage 3, but it is now backed by a real
    authorization check proving it is INTENDED privacy, not an accident of
    RESULTS never having been made project-aware to begin with.

    The former test_results_access_should_match_project_authorization_exactly
    (`@unittest.expectedFailure`, asserting the OPPOSITE decision -- Option
    B) is retired, not carried forward: it encoded a design direction this
    stage explicitly did not take. See ResultsAuthorizationTests for the
    dedicated Stage 3 authorization-boundary tests (unauthorized/collab
    view+edit, 403/404, no-scope-created) -- this class keeps only the
    tests specific to the collaborator-vs-stranger CONTRAST that motivated
    Stage 4's original framing, updated to their Stage 3 outcome.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        self._snapshot_global_stores()

    def tearDown(self) -> None:
        self._restore_global_stores()

    def test_project_authorization_itself_is_correct_but_disconnected_from_results_visibility(self) -> None:
        """PASSES TODAY. Establishes that SharingService's own authorization
        decision is correct (collaborator: allowed, stranger: denied for the
        PROJECT resource) -- isolating the defect to RESULTS's own scoping,
        not to the authorization system it should be, but currently isn't,
        wired into.
        """
        owner_client, owner_id = _register("authz-baseline-owner")
        collaborator_client, collaborator_id = _register("authz-baseline-collab")
        stranger_client, stranger_id = _register("authz-baseline-stranger")
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)

        project_id = _create_project(owner_client, "Modeling State Authz Baseline Project")
        _share_project(owner_client, project_id, collaborator_id, "edit")

        collab_check = collaborator_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertTrue(collab_check.json()["access"]["allowed"])

        stranger_check = stranger_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertFalse(stranger_check.json()["access"]["allowed"])

    def test_authorized_collaborator_gets_own_independent_results_scope(self) -> None:
        """PASSING BASELINE (promoted in Stage 3 -- see the class docstring's
        DECISION section). The owner correctly sees their own real result;
        the authorized collaborator -- correctly let PAST authorization,
        confirmed via the direct access-check below, not merely denied --
        still gets nothing back for the owner's result, because Option A
        gives them their OWN independent RESULTS scope for this project.
        """
        owner_client, owner_id, collaborator_client, collaborator_id, project_id = self._setup_shared_project_with_owner_result(
            "collab-vis"
        )
        access_check = collaborator_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertTrue(access_check.json()["access"]["allowed"], "Collaborator must be authorized for the project itself.")

        owner_view = owner_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(owner_view.status_code, 200)
        self.assertEqual(owner_view.json()["summary"]["marker"], "OWNER_RESULT")

        collaborator_view = collaborator_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(collaborator_view.status_code, 200, collaborator_view.text)
        self.assertIsNone(collaborator_view.json()["summary"])
        self.assertIsNone(get_scoped_result_store((collaborator_id, project_id)).get_last_summary())

    def test_unrelated_unauthorized_stranger_no_longer_sees_another_users_result(self) -> None:
        """PASSING BASELINE -- REQUIRED SECURITY TEST. Formerly (through
        Stage 2B) a test proving a stranger with zero project relationship
        (correctly denied by SharingService for the PROJECT resource
        itself) could still get a benign `{"summary": None}` 200 from GET
        /api/train/last, because that endpoint performed no project-level
        authorization check at all -- it happened to be safe only because
        RESULTS was per-user-scoped, not because anything actually checked
        the stranger's relationship to the project.

        Since Stage 3, /api/train/last calls authorize_modeling_scope,
        so a stranger with zero project relationship is now correctly
        rejected with 403 BEFORE any RESULTS read is attempted -- a
        strictly stronger property than the old "empty response" behavior,
        and consistent with ProjectAuthorizationForDatastoreTests/
        ResultsAuthorizationTests's identical denial for DATASTORE.
        """
        owner_client, owner_id, _collaborator_client, _collaborator_id, project_id = self._setup_shared_project_with_owner_result(
            "collab-vis-stranger"
        )
        stranger_client, stranger_id = _register("collab-vis-stranger-user")
        stranger_check = stranger_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertFalse(stranger_check.json()["access"]["allowed"], "This user must NOT have project access.")

        stranger_view = stranger_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(stranger_view.status_code, 403, stranger_view.text)
        self.assertIsNone(get_scoped_result_store((stranger_id, project_id)).get_last_summary())

        # The owner's own view is unaffected by the stranger's attempt.
        owner_view = owner_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(owner_view.json()["summary"]["marker"], "OWNER_RESULT")

    def _setup_shared_project_with_owner_result(self, label: str, permission_level: str = "edit") -> tuple[TestClient, str, TestClient, str, str]:
        owner_client, owner_id = _register(f"{label}-owner")
        collaborator_client, collaborator_id = _register(f"{label}-collab")
        # The collaborator must have made at least one authenticated request
        # before being shareable (an unrelated, pre-existing SharingService
        # quirk documented during the FND-002 work in this codebase: sharing
        # writes a project_collaborators row with an FK on users(user_id),
        # which requires the target user already synced into the persistence
        # layer). Not this task's concern to fix -- just sequenced correctly.
        self.assertEqual(collaborator_client.get("/api/auth/me").status_code, 200)

        project_id = _create_project(owner_client, f"Modeling State {label} Project")
        _share_project(owner_client, project_id, collaborator_id, permission_level)

        access_check = collaborator_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertEqual(access_check.status_code, 200)
        self.assertTrue(access_check.json()["access"]["allowed"], "Collaborator must have real, confirmed project access before this test proceeds.")

        # Seeded into the owner's own real (user_id, project_id) scope --
        # the owner's real HTTP request path is what actually populates
        # this in production.
        get_scoped_result_store((owner_id, project_id)).set_last_summary(
            {"marker": "OWNER_RESULT", "project_id": project_id, "training_job_id": "job-collab-vis-demo", "ranked": [{"key": "logreg"}]}
        )
        return owner_client, owner_id, collaborator_client, collaborator_id, project_id


if __name__ == "__main__":
    unittest.main()

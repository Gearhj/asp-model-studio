"""Stage 1 (ATLAS_MODELING_STATE_ISOLATION_PLAN.md) -- characterization tests for
the current Predictive Modeling in-memory state architecture.

This file makes NO production code changes. It only proves, with executable
tests against the real FastAPI app (`fastapi.testclient.TestClient`) and the
real `DATASTORE` / `RESULTS` / `TRAINING_JOBS` singletons, exactly what is
true today -- including one finding that CONTRADICTS a claim in
ATLAS_MODELING_STATE_ISOLATION_PLAN.md. That contradiction is documented
here, in the delivery report, and should be treated as authoritative over
the plan document's prior (code-reading-only) claim, per this exercise's own
purpose: proving things with execution, not just reading.

=====================================================================
CORRECTION TO THE PLAN DOCUMENT -- READ THIS FIRST
=====================================================================

ATLAS_MODELING_STATE_ISOLATION_PLAN.md Sec 6 claims: "FastAPI/Starlette's
`run_in_threadpool` ... explicitly copies the caller's `contextvars.Context`
into its worker thread, so [active_user() resolving correctly] holds even
though most of these are plain `def` endpoints." Executed evidence in this
file (and independently reconfirmed against a real running `uvicorn`
process, not just TestClient -- see the delivery report) disproves this:

    server/security/security_store.py's `require_user()` is a *dependency*
    (`Depends(require_user)`, mounted at the router level via
    `dependencies=[Depends(require_user)]` in server/main.py:241-275).
    FastAPI/Starlette resolves each sync dependency via its OWN
    `run_in_threadpool` call, with its own independently-copied
    `contextvars.Context`. `require_user()`'s call to `set_active_user(user)`
    (security_store.py:580,585,608) mutates that dependency-call's private
    context copy. That mutation is discarded once the dependency returns --
    it is never merged back into the request's ambient context, so the
    ROUTE HANDLER BODY's later `run_in_threadpool` call (a SEPARATE copy)
    never sees it. `active_user()` is therefore **None inside every route
    handler body** across this entire application, for every request,
    regardless of which user is authenticated -- confirmed for both
    per-endpoint `Depends()` parameters and router-level `dependencies=[]`,
    and for both sync and async endpoint bodies.

Consequence: `DATASTORE`/`RESULTS`'s `_scope_key()` (server/core/
dataset_store.py:229-236, server/core/result_store.py:76-83) falls back to
the literal string `"anonymous"` for literally every real HTTP request, not
just when project_id is missing. The defect is more severe than "isolated
by user, not by project" -- in real operation there is currently **no
isolation dimension at all** for DATASTORE/RESULTS reached through the
ordinary request path; every authenticated user, on every project, shares
one process-wide "anonymous" bucket. Authentication *itself* is unaffected
by this (require_user()'s RETURN VALUE, used by routes that accept
`user: Dict = Depends(require_user)` as an actual parameter -- e.g.
`/api/auth/me`, and all of the FND-001/002 persistence/sharing routes --
correctly identifies the right user every time; only the ContextVar-reading
path that DATASTORE/RESULTS rely on is broken).

This changes the "smallest safe first implementation step" recommendation
-- see the delivery report, item 14.

=====================================================================
CLASSIFICATION (read this before reading or changing any test below)
=====================================================================

PASSING BASELINE -- behaviors that are correct today and MUST remain correct
through every later migration stage.

    - AuthenticationIdentityBaselineTests (all tests)
    - ExistingUserIsolationTests.test_store_class_correctly_isolates_by_explicit_scope_key

KNOWN LIMITATIONS -- behaviors that are currently broken. Each defect is
proven by a test that PASSES today (because it asserts the *actual*, broken
behavior -- it is a bug-reproduction test, not an endorsement of that
behavior) and is paired with a companion test decorated
`@unittest.expectedFailure` that asserts the *desired* future behavior from
ATLAS_MODELING_STATE_ISOLATION_PLAN.md. The companion currently fails (by
design -- `expectedFailure` reports it as an "expected failure", not a
suite failure). Once the relevant migration stage ships, that companion
will start passing, `unittest` will report an "unexpected success", and it
should then be un-decorated and promoted to an ordinary regression test.

    - ExistingUserIsolationTests (HTTP-path tests) -> targets a prerequisite
      fix to the Depends()/ContextVar propagation gap above, which must land
      before or alongside Stage 3 of the plan (Stage 3 assumed this already
      worked and only needed a project_id added to the key).
    - MissingProjectIsolationTests               -> targets Stage 2 + Stage 3
    - BackgroundContextTests                      -> targets Stage 6 (and the
      prerequisite fix above)
    - CheckpointRestoreTests                      -> targets Stage 6
    - TrainingJobIsolationTests                   -> targets Stage 5
    - CollaboratorVisibilityTests                 -> targets Stage 4 (and the
      prerequisite fix above)

No test in this file weakens an assertion to force a pass, and no test
represents current broken behavior as desirable. Every "passes today"
assertion has a code comment pointing at the exact production mechanism it
is reproducing.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
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
from server.core.dataset_store import get_scoped_dataset_store  # noqa: E402
from server.core.metadata_router import SetSamplePayload  # noqa: E402
from server.core.result_store import get_scoped_result_store  # noqa: E402
from server.splitting.split_service import split_service  # noqa: E402


def _cleanup_db_files() -> None:
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


def _build_frame(rows: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "amount": [float(index % 37) for index in range(rows)],
            "velocity": [float((index * 7) % 19) for index in range(rows)],
            "target": [1 if index % 9 == 0 else 0 for index in range(rows)],
        }
    )


def _seed_governed_dataset_and_split(scope: str, dataset_version: str, feature_manifest_version: str, split_id: str) -> None:
    """Populate a real, preflight-ready DATASTORE state directly into an
    EXPLICIT scope (get_scoped_dataset_store bypasses contextvars entirely),
    mirroring the fixture pattern in tests/predictive_modeling_repair_test.py's
    configure_manifest()/create_governed_split().

    `scope` must be "anonymous" for any state that a real HTTP call (through
    POST /api/model/train/jobs etc.) needs to see -- see the module docstring's
    "CORRECTION TO THE PLAN DOCUMENT": every real request currently resolves
    DATASTORE/RESULTS to the "anonymous" scope, confirmed empirically, not
    the caller's own userId.
    """
    store = get_scoped_dataset_store(scope)
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


def _training_job_payload(project_id: str, dataset_version: str, feature_manifest_version: str, split_id: str, user_label: str) -> Dict[str, Any]:
    return {
        "models": ["logreg"],
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


def _wait_for_terminal_job(client: TestClient, job_id: str, timeout: float = 30.0) -> Dict[str, Any]:
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
    """
    terminal = {"complete", "failed", "cancelled", "interrupted"}
    deadline = time.time() + timeout
    last: Dict[str, Any] = {}
    while time.time() < deadline:
        response = client.get(f"/api/model/train/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("overall_status") in terminal:
            return last
        time.sleep(0.05)
    raise AssertionError(f"Training job {job_id} did not reach a terminal state within {timeout}s: {last}")


class _DatastoreDictIsolationMixin:
    """Snapshot/restore the private _DATASTORES / _RESULT_STORES module dicts
    around a test so class-local scope manipulation (especially the shared
    "anonymous" bucket every real HTTP call resolves to) can never leak into
    other test classes in this file, regardless of execution order.
    """

    def _snapshot_global_stores(self) -> None:
        self._datastores_snapshot = dict(dataset_store_module._DATASTORES)
        self._result_stores_snapshot = dict(result_store_module._RESULT_STORES)

    def _restore_global_stores(self) -> None:
        dataset_store_module._DATASTORES.clear()
        dataset_store_module._DATASTORES.update(self._datastores_snapshot)
        result_store_module._RESULT_STORES.clear()
        result_store_module._RESULT_STORES.update(self._result_stores_snapshot)
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
    """See the module docstring's "CORRECTION TO THE PLAN DOCUMENT" section.

    Contains ONE genuinely passing baseline test (the store classes
    themselves isolate correctly by explicit key) and several KNOWN
    LIMITATION tests proving that, in real HTTP operation, DATASTORE/RESULTS
    provide NO isolation between different authenticated users at all --
    not merely "isolated by user but not by project," as the plan document
    assumed.
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
        instances design (server/core/dataset_store.py:226,239-243) is sound
        in isolation: two distinct explicit scope keys never share state.
        This isolates the defect to key POPULATION (how the key is derived
        from a live request), not the storage structure itself.
        """
        key_a = f"scope-check-a-{uuid.uuid4().hex[:8]}"
        key_b = f"scope-check-b-{uuid.uuid4().hex[:8]}"
        get_scoped_dataset_store(key_a).set_raw(pd.DataFrame({"marker": ["A"]}))
        get_scoped_dataset_store(key_b).set_raw(pd.DataFrame({"marker": ["B"]}))
        self.assertEqual(list(get_scoped_dataset_store(key_a).raw_df["marker"]), ["A"])
        self.assertEqual(list(get_scoped_dataset_store(key_b).raw_df["marker"]), ["B"])
        self.assertIsNot(get_scoped_dataset_store(key_a), get_scoped_dataset_store(key_b))

    def test_datastore_does_not_isolate_real_authenticated_users_over_http(self) -> None:
        """PASSES TODAY -- reproduces the defect, does not endorse it.

        Two different, genuinely authenticated users (distinct session
        cookies, distinct userIds -- confirmed via
        AuthenticationIdentityBaselineTests) each POST to
        /api/data/set_sample; User A's dataset is silently visible to (and
        overwritten by) User B's, because active_user() -- read inside
        set_sample()'s call to DATASTORE.set_raw() -- is None for both
        requests, and _scope_key() falls back to the same "anonymous" bucket
        for everyone. Independently reconfirmed against a real running
        `uvicorn` process (not just TestClient) -- see the delivery report.
        """
        client_a, user_a_id = _register("http-iso-a")
        client_b, user_b_id = _register("http-iso-b")
        self.assertNotEqual(user_a_id, user_b_id)

        set_a = client_a.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 111, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_a.status_code, 200, set_a.text)
        set_b = client_b.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 222, "target": 0}], "target": "target"},
        )
        self.assertEqual(set_b.status_code, 200, set_b.text)

        get_a = client_a.get("/api/data/get_sample")
        get_b = client_b.get("/api/data/get_sample")
        # Both users see the SAME (most-recently-written) data -- User A's
        # own upload is gone from User A's own perspective.
        self.assertEqual(get_a.json()["rows"][0]["amount"], 222)
        self.assertEqual(get_b.json()["rows"][0]["amount"], 222)

    def test_result_store_does_not_isolate_real_authenticated_users(self) -> None:
        """PASSES TODAY -- same defect, RESULTS side. Explicit-scope writes
        (get_scoped_result_store(user_id)) prove the two users' *intended*
        scopes are independent (mirroring the passing-baseline test above),
        but the endpoint an authenticated user actually calls,
        GET /api/train/last, always reads the "anonymous" scope, not the
        caller's own userId's scope -- so neither user's real request can
        ever reach the data this test seeded for them specifically.
        """
        client_a, user_a_id = _register("http-iso-results-a")
        client_b, user_b_id = _register("http-iso-results-b")

        get_scoped_result_store(user_a_id).set_last_summary({"marker": "A"})
        get_scoped_result_store(user_b_id).set_last_summary({"marker": "B"})

        # The store-level values are correctly independent (as proven at
        # the class level above)...
        self.assertEqual(get_scoped_result_store(user_a_id).get_last_summary()["marker"], "A")
        self.assertEqual(get_scoped_result_store(user_b_id).get_last_summary()["marker"], "B")

        # ...but neither real request can see them: GET /api/train/last
        # reads the "anonymous" RESULTS scope, which has nothing in it here,
        # for both users.
        last_a = client_a.get("/api/train/last")
        last_b = client_b.get("/api/train/last")
        self.assertEqual(last_a.status_code, 200)
        self.assertEqual(last_b.status_code, 200)
        self.assertIsNone(last_a.json()["summary"])
        self.assertIsNone(last_b.json()["summary"])

    @unittest.expectedFailure
    def test_datastore_should_be_isolated_between_real_authenticated_users_over_http(self) -> None:
        """MIGRATION TARGET.

        Desired future behavior: two different authenticated users' uploads
        through /api/data/set_sample must never collide, regardless of
        project. This requires fixing how DATASTORE's scope key is
        populated from a live request (the ContextVar-propagation gap
        described in the module docstring) at minimum -- and, per the
        plan's Stage 3, extending that key to include project_id.
        """
        client_a, _user_a_id = _register("http-iso-target-a")
        client_b, _user_b_id = _register("http-iso-target-b")
        client_a.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 333, "target": 1}], "target": "target"},
        )
        client_b.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 444, "target": 0}], "target": "target"},
        )
        get_a = client_a.get("/api/data/get_sample")
        self.assertEqual(get_a.json()["rows"][0]["amount"], 333)


class MissingProjectIsolationTests(unittest.TestCase):
    """KNOWN LIMITATION -- targets Stage 2 (require project_id at the request
    boundary) and Stage 3 (re-key DATASTORE by (user_id, project_id)) of
    ATLAS_MODELING_STATE_ISOLATION_PLAN.md.

    These tests use a SINGLE authenticated session throughout, so they
    reproduce the "one user, two projects" defect regardless of which
    broader scope bucket that session's requests happen to land in --
    unaffected by the ExistingUserIsolationTests finding above, and
    independently true either way. (In today's reality, per that finding,
    the *effective* second dimension missing is not just project_id but
    identity entirely -- see ExistingUserIsolationTests -- but the specific,
    demonstrable symptom below is the same regardless.)

    Root defect: SetSamplePayload (server/core/metadata_router.py:77-82) has
    no project_id field, so DATASTORE.set_raw() (metadata_router.py:141) has
    no way to know which project a given upload belongs to.
    """

    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def test_set_sample_payload_has_no_project_identifier(self) -> None:
        # Documents exactly how project identity is absent from the affected
        # request, per the investigation brief -- verified against the real
        # Pydantic model, not inferred from the route name.
        fields = set(SetSamplePayload.model_fields.keys())
        self.assertEqual(fields, {"headers", "rows", "target", "selected_columns", "dataset_version"})
        self.assertNotIn("project_id", fields)
        self.assertNotIn("projectId", fields)

    def test_same_user_second_project_overwrites_first_projects_dataset(self) -> None:
        """PASSES TODAY -- reproduces the defect, does not endorse it."""
        client, _user_id = _register("same-user-sequential")

        set_a = client.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 1001, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_a.status_code, 200, set_a.text)
        get_after_a = client.get("/api/data/get_sample")
        self.assertEqual(get_after_a.json()["rows"][0]["amount"], 1001)

        # The user switches to a second project and loads its dataset --
        # nothing in this request can express "this is a different project."
        set_b = client.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 2002, "target": 0}], "target": "target"},
        )
        self.assertEqual(set_b.status_code, 200, set_b.text)

        # "Returning" to Project A: the same GET call has no way to ask for
        # Project A specifically, and it does not return Project A's data.
        get_after_b = client.get("/api/data/get_sample")
        self.assertEqual(get_after_b.json()["rows"][0]["amount"], 2002)
        self.assertNotEqual(get_after_b.json()["rows"][0]["amount"], 1001)

    def test_two_browser_tabs_same_user_share_and_collide(self) -> None:
        """PASSES TODAY -- reproduces the defect for the two-tabs scenario
        specifically (plan Sec 5, scenario 3): two independent TestClient
        instances carrying the SAME session cookie (as two tabs of one
        logged-in browser would) resolve to the identical DATASTORE scope.
        """
        client_tab1, _user_id = _register("two-tabs-user")
        session_cookie = client_tab1.cookies.get(SESSION_COOKIE_NAME)
        self.assertTrue(session_cookie, "Registration must issue a session cookie.")

        client_tab2 = TestClient(app)
        client_tab2.cookies.set(SESSION_COOKIE_NAME, session_cookie)

        set_tab1 = client_tab1.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 3003, "target": 1}], "target": "target"},
        )
        self.assertEqual(set_tab1.status_code, 200, set_tab1.text)

        set_tab2 = client_tab2.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 4004, "target": 0}], "target": "target"},
        )
        self.assertEqual(set_tab2.status_code, 200, set_tab2.text)

        # Tab 1, which never touched this endpoint again, now sees Tab 2's
        # data if it re-reads -- because both tabs share one session, hence
        # one DATASTORE scope.
        get_tab1 = client_tab1.get("/api/data/get_sample")
        self.assertEqual(get_tab1.json()["rows"][0]["amount"], 4004)

    @unittest.expectedFailure
    def test_returning_to_project_a_should_still_retrieve_project_as_own_state(self) -> None:
        """MIGRATION TARGET (Stage 2 + Stage 3).

        Desired future behavior: once /api/data/set_sample accepts a
        project_id and DATASTORE is keyed accordingly, sending
        project_id="proj-a" then project_id="proj-b" then asking to view
        "proj-a" again must return Project A's own data, not Project B's.
        Today's SetSamplePayload silently ignores unknown fields (Pydantic's
        default behavior), so passing project_id today has zero effect --
        this test sends it anyway, to fail in exactly the way Stage 2/3 must
        fix, and to flip to an ordinary pass the moment they do.
        """
        client, _user_id = _register("same-user-target-behavior")
        client.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 5005, "target": 1}], "target": "target", "project_id": "proj-a"},
        )
        client.post(
            "/api/data/set_sample",
            json={"headers": ["amount", "target"], "rows": [{"amount": 6006, "target": 0}], "target": "target", "project_id": "proj-b"},
        )
        get_proj_a = client.get("/api/data/get_sample", params={"project_id": "proj-a"})
        self.assertEqual(get_proj_a.json()["rows"][0]["amount"], 5005)


class BackgroundContextTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """KNOWN LIMITATION -- targets Stage 6 (fix background-thread context
    propagation) of ATLAS_MODELING_STATE_ISOLATION_PLAN.md, compounded by
    the Depends()/ContextVar gap documented in the module docstring.

    Root defect: contextvars.Context is not inherited by a bare
    threading.Thread or a raw concurrent.futures.ThreadPoolExecutor.
    server/training/training_job_service.py's `_run` (its Thread entry
    point, spawned at lines 178-183) touches DATASTORE.meta directly in its
    `finally` block (lines 352-354).
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
        (server/core/dataset_store.py:229-236) with an EXPLICITLY set
        active_user() (via set_active_user(), the exact call
        require_user() makes) -- proving that even when a context IS
        correctly populated in the calling thread, a bare background
        thread still does not inherit it. This is a distinct, independent
        defect from the Depends()-propagation gap documented in the module
        docstring: fixing one does not fix the other. Uses threading.Event
        for deterministic synchronization -- no sleeps.
        """
        marker_user = {"userId": f"context-probe-{uuid.uuid4().hex[:8]}"}
        set_active_user(marker_user)
        try:
            self.assertEqual(dataset_store_module._scope_key(), marker_user["userId"])

            observed: Dict[str, str] = {}
            done = threading.Event()

            def worker() -> None:
                observed["scope"] = dataset_store_module._scope_key()
                done.set()

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            signaled = done.wait(timeout=5.0)
            thread.join(timeout=5.0)

            self.assertTrue(signaled, "Background thread did not signal completion in time.")
            self.assertEqual(observed["scope"], "anonymous")
            self.assertNotEqual(observed["scope"], marker_user["userId"])
        finally:
            set_active_user(None)

    def test_two_users_training_jobs_collide_in_the_shared_anonymous_results_scope(self) -> None:
        """PASSES TODAY. Traces the compounded, real-world impact through
        the actual production entry point: two DIFFERENT real authenticated
        users each create a real training job through the real HTTP router.
        `training_job_service.create()` (line 167) captures
        `RESULTS.current()` -- intended (per the plan) to bind each job to
        its launching user's own store -- but because active_user() is None
        inside the request handler body (see module docstring), that
        capture resolves to the SAME "anonymous" ResultStore for both users.
        User B's completed job silently overwrites User A's result.

        NOTE, for accuracy: the specific sub-symptom originally hypothesized
        in ATLAS_MODELING_STATE_ISOLATION_PLAN.md for
        DATASTORE.meta["active_training_job_id"] -- that the background
        thread's cleanup (lines 352-354) would pop the wrong scope, leaving
        a stale marker on the *launching user's real* scope -- does NOT
        reproduce as described. Verified directly: because the REQUEST
        thread (training_job_service.create(), line 176) is *also* unable
        to reach any real per-user scope, it sets that marker on
        "anonymous" too, and the background thread's later pop (also
        "anonymous") correctly clears the very key that was actually set.
        Both operations land on the same wrong bucket, so this one specific
        marker does not go stale -- a materially different (if equally
        broken) outcome than originally described, and reported as such
        rather than forcing the original claim to "pass."
        """
        client_a, user_a_id = _register("bg-collide-a")
        client_b, user_b_id = _register("bg-collide-b")
        self.assertNotEqual(user_a_id, user_b_id)

        _seed_governed_dataset_and_split("anonymous", "bg-v1", "bg-fm-v1", "bg-split-v1")
        create_a = client_a.post("/api/model/train/jobs", json=_training_job_payload("proj-bg-a", "bg-v1", "bg-fm-v1", "bg-split-v1", "user-a"))
        self.assertEqual(create_a.status_code, 200, create_a.text)
        job_a_id = create_a.json()["job_id"]
        final_a = _wait_for_terminal_job(client_a, job_a_id)
        self.assertEqual(final_a["overall_status"], "complete", final_a)

        # Confirm the *hypothesized* marker-staleness sub-symptom does NOT
        # occur (see the docstring note above) -- both set and clear land on
        # "anonymous", so it is correctly cleared there.
        self.assertIsNone(get_scoped_dataset_store("anonymous").meta.get("active_training_job_id"))

        # User A's result exists only in the shared "anonymous" bucket, not
        # under their own real userId.
        self.assertIsNotNone(get_scoped_result_store("anonymous").get_last_summary())
        self.assertIsNone(get_scoped_result_store(user_a_id).get_last_summary())

        # User B, working on a COMPLETELY different project, now trains too.
        _seed_governed_dataset_and_split("anonymous", "bg-v2", "bg-fm-v2", "bg-split-v2")
        create_b = client_b.post("/api/model/train/jobs", json=_training_job_payload("proj-bg-b", "bg-v2", "bg-fm-v2", "bg-split-v2", "user-b"))
        self.assertEqual(create_b.status_code, 200, create_b.text)
        job_b_id = create_b.json()["job_id"]
        final_b = _wait_for_terminal_job(client_b, job_b_id)
        self.assertEqual(final_b["overall_status"], "complete", final_b)

        # User A's own subsequent read of "their" last training result now
        # returns User B's project's result instead.
        last_for_a = client_a.get("/api/train/last")
        self.assertEqual(last_for_a.json()["summary"]["project_id"], "proj-bg-b")
        self.assertNotEqual(last_for_a.json()["summary"]["project_id"], "proj-bg-a")

    @unittest.expectedFailure
    def test_each_users_training_job_should_land_in_their_own_scope(self) -> None:
        """MIGRATION TARGET (Stage 6, plus the Depends()/ContextVar
        prerequisite fix). Desired future behavior: User A's own subsequent
        read of their last training result must reflect User A's own job,
        never User B's, regardless of what either user did afterward.
        """
        client_a, user_a_id = _register("bg-collide-target-a")
        client_b, _user_b_id = _register("bg-collide-target-b")

        _seed_governed_dataset_and_split("anonymous", "bg-t1", "bg-fm-t1", "bg-split-t1")
        create_a = client_a.post("/api/model/train/jobs", json=_training_job_payload("proj-bg-target-a", "bg-t1", "bg-fm-t1", "bg-split-t1", "user-a"))
        job_a_id = create_a.json()["job_id"]
        _wait_for_terminal_job(client_a, job_a_id)

        _seed_governed_dataset_and_split("anonymous", "bg-t2", "bg-fm-t2", "bg-split-t2")
        create_b = client_b.post("/api/model/train/jobs", json=_training_job_payload("proj-bg-target-b", "bg-t2", "bg-fm-t2", "bg-split-t2", "user-b"))
        job_b_id = create_b.json()["job_id"]
        _wait_for_terminal_job(client_b, job_b_id)

        last_for_a = client_a.get("/api/train/last")
        self.assertEqual(last_for_a.json()["summary"]["project_id"], "proj-bg-target-a")


class CheckpointRestoreTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """KNOWN LIMITATION -- targets Stage 6 (fix restart-checkpoint collapse)
    of ATLAS_MODELING_STATE_ISOLATION_PLAN.md.

    Root defect: save_checkpoint()/load_checkpoint() (server/core/
    session_checkpoint.py:42-107) read/write DATASTORE/RESULTS through the
    ambient-context proxy, snapshotting or restoring exactly one scope into
    one flat file. load_checkpoint() is called from
    @app.on_event("startup") (server/main.py:149-160), outside any request,
    so active_user() is None there and every restored value lands in the
    "anonymous" scope. These tests use set_active_user() directly (not HTTP)
    to control scope deterministically -- unaffected by the Depends()/
    ContextVar gap documented in the module docstring, since that gap is
    specific to dependency-to-handler propagation, not to direct same-thread
    calls like these.

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

    def test_checkpoint_save_is_a_single_scope_last_writer_wins_file(self) -> None:
        """PASSES TODAY -- reproduces session_checkpoint.py's single-document
        design: saving User B's state after User A's overwrites A's snapshot
        entirely. There is no per-scope section in the checkpoint file.
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
        self.assertNotIn("A-ONLY", raw_contents, "The checkpoint file must not retain User A's snapshot after User B's save overwrote it.")

    def test_restart_reload_restores_into_anonymous_not_any_real_user(self) -> None:
        """PASSES TODAY -- reproduces the restart-collapse defect precisely.

        Mechanism for "simulate process restart" (smallest reliable
        approach that exercises the real production functions rather than
        spawning a real subprocess): (1) save a real scope's state to an
        isolated checkpoint file, (2) clear the in-memory _DATASTORES/
        _RESULT_STORES dicts to reproduce what a fresh process actually
        starts with, (3) clear active_user() to reproduce
        @app.on_event("startup")'s lack of any request context, (4) call the
        real load_checkpoint().
        """
        user_b = {"userId": f"checkpoint-restart-b-{uuid.uuid4().hex[:8]}"}
        set_active_user(user_b)
        try:
            from server.core.dataset_store import DATASTORE

            DATASTORE.reset_all()
            DATASTORE.set_raw(pd.DataFrame({"marker": ["RESTART-B"]}))
            self.assertTrue(session_checkpoint_module.save_checkpoint())
        finally:
            set_active_user(None)

        # Step 2+3: simulate a fresh process with no request in flight.
        dataset_store_module._DATASTORES.clear()
        result_store_module._RESULT_STORES.clear()
        self.assertIsNone(active_user())

        # Step 4: the real startup path (server/main.py:149-160) calls this
        # with no request context.
        self.assertTrue(session_checkpoint_module.load_checkpoint())

        anonymous_df = get_scoped_dataset_store("anonymous").raw_df
        self.assertIsNotNone(anonymous_df)
        self.assertEqual(list(anonymous_df["marker"]), ["RESTART-B"])

        # The user whose data was actually saved gets nothing back under
        # their own identity -- ownership information is lost, not merely
        # relabeled.
        self.assertIsNone(get_scoped_dataset_store(user_b["userId"]).raw_df)

    @unittest.expectedFailure
    def test_restart_should_restore_each_users_own_scope(self) -> None:
        """MIGRATION TARGET (Stage 6).

        Desired future behavior: after a restart, User B's own scope (looked
        up by their real userId, exactly as a live request for that user
        would resolve it) must contain User B's own last-checkpointed state.
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

        dataset_store_module._DATASTORES.clear()
        result_store_module._RESULT_STORES.clear()
        session_checkpoint_module.load_checkpoint()

        restored = get_scoped_dataset_store(user_b["userId"]).raw_df
        self.assertIsNotNone(restored)
        self.assertEqual(list(restored["marker"]), ["RESTART-TARGET"])


class TrainingJobIsolationTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """KNOWN LIMITATION (security-relevant) -- targets Stage 5 (authorize and
    scope TRAINING_JOBS) of ATLAS_MODELING_STATE_ISOLATION_PLAN.md.

    Root defect: TRAINING_JOBS (server/training/training_job_service.py:539)
    is a bare module-level dict keyed only by job_id, never routed through
    any scoping mechanism at all. GET/POST .../jobs/{job_id} and .../cancel
    (server/training/trainer_router.py:39-52) perform authentication
    (Depends(require_user)) but no resource-level authorization -- any
    authenticated user who has a job_id can view or cancel it, regardless of
    who created it or which project it belongs to. This is independent of
    (and does not depend on) the DATASTORE/RESULTS ContextVar gap
    documented in the module docstring: TRAINING_JOBS's job_id-only lookup
    would have the same authorization gap even if that gap were fixed.
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

    def _create_real_job(self, label: str) -> tuple[TestClient, str, str]:
        client, user_id = _register(label)
        _seed_governed_dataset_and_split("anonymous", f"{label}-v1", f"{label}-fm-v1", f"{label}-split-v1")
        create = client.post(
            "/api/model/train/jobs",
            json=_training_job_payload(f"proj-{label}", f"{label}-v1", f"{label}-fm-v1", f"{label}-split-v1", label),
        )
        self.assertEqual(create.status_code, 200, create.text)
        return client, user_id, create.json()["job_id"]

    def test_job_record_has_project_id_but_no_verified_owner_identity_field(self) -> None:
        """PASSES TODAY. Answers investigation point 5 directly: the public
        job record carries project_id, but the only "who created this" field
        is `contract.user` -- a free-text string copied verbatim from the
        client-supplied request body, not a verified identity, and not
        usable for an authorization check.
        """
        client_a, _user_a_id, job_id = self._create_real_job("ownership-fields")
        job = _wait_for_terminal_job(client_a, job_id)

        self.assertIn("project_id", job)
        self.assertEqual(job["project_id"], "proj-ownership-fields")
        self.assertNotIn("owner_user_id", job)
        self.assertNotIn("user_id", job)
        self.assertIn("user", job["contract"])
        self.assertEqual(job["contract"]["user"], "ownership-fields")  # client-supplied, unverified

    def test_unrelated_authenticated_user_can_currently_view_another_users_job(self) -> None:
        """PASSES TODAY -- reproduces the authorization gap. Authentication
        only (a valid session) is required; resource-level ownership is
        never checked.
        """
        client_a, user_a_id, job_id = self._create_real_job("cross-view-a")
        client_b, user_b_id = _register("cross-view-b")
        self.assertNotEqual(user_a_id, user_b_id)

        response = client_b.get(f"/api/model/train/jobs/{job_id}")
        self.assertEqual(response.status_code, 200, response.text)
        # Not just "some 200" -- User B receives User A's job contract,
        # including dataset/feature-manifest identifiers they have no
        # relationship to.
        self.assertEqual(response.json()["contract"]["project_id"], "proj-cross-view-a")

    def test_unrelated_authenticated_user_can_currently_cancel_another_users_job(self) -> None:
        """PASSES TODAY -- reproduces the authorization gap for the
        destructive action specifically. Cancel is attempted immediately
        after creation (before waiting for completion) so the job is very
        likely still active; the core assertion (200, not 403/404) holds
        either way, since TRAINING_JOBS.cancel() never checks ownership
        regardless of job state.
        """
        client_a, user_a_id, job_id = self._create_real_job("cross-cancel-a")
        client_b, user_b_id = _register("cross-cancel-b")
        self.assertNotEqual(user_a_id, user_b_id)

        response = client_b.post(f"/api/model/train/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotEqual(response.status_code, 403)
        self.assertNotEqual(response.status_code, 404)

        # Regardless of timing, User A's own view of the job now reflects
        # whatever effect (if any) User B's unauthorized call had -- proving
        # it was accepted as a real action on User A's job, not a no-op.
        after = client_a.get(f"/api/model/train/jobs/{job_id}")
        self.assertEqual(after.status_code, 200)
        self.assertIn(after.json()["overall_status"], {"cancelled", "complete", "failed", "interrupted"})

    @unittest.expectedFailure
    def test_unrelated_user_should_be_denied_view_access_to_another_users_job(self) -> None:
        """MIGRATION TARGET (Stage 5).

        Desired future behavior: an authenticated user with no relationship
        to the job's project must receive 403 or 404, per
        ATLAS_MODELING_STATE_ISOLATION_PLAN.md Sec 8 (reusing
        SharingService.check_permission the same way the FND-001/FND-002
        work in this codebase already does for persistence routes and
        project access).
        """
        client_a, user_a_id, job_id = self._create_real_job("cross-view-target-a")
        client_b, user_b_id = _register("cross-view-target-b")
        self.assertNotEqual(user_a_id, user_b_id)

        response = client_b.get(f"/api/model/train/jobs/{job_id}")
        self.assertIn(response.status_code, {403, 404})

    @unittest.expectedFailure
    def test_unrelated_user_should_be_denied_cancel_access_to_another_users_job(self) -> None:
        """MIGRATION TARGET (Stage 5)."""
        client_a, user_a_id, job_id = self._create_real_job("cross-cancel-target-a")
        client_b, user_b_id = _register("cross-cancel-target-b")
        self.assertNotEqual(user_a_id, user_b_id)

        response = client_b.post(f"/api/model/train/jobs/{job_id}/cancel")
        self.assertIn(response.status_code, {403, 404})


class CollaboratorVisibilityTests(unittest.TestCase, _DatastoreDictIsolationMixin):
    """KNOWN LIMITATION -- targets Stage 4 (re-key RESULTS by project_id, not
    user_id) of ATLAS_MODELING_STATE_ISOLATION_PLAN.md.

    Original hypothesis (per the plan, written from code reading alone):
    RESULTS is scoped by user_id, so an *authorized* collaborator cannot see
    the project owner's committed result. Executed evidence shows the
    actual defect is broader: because every real request currently resolves
    to the SAME "anonymous" RESULTS scope (see the module docstring),
    GET /api/train/last currently exposes the same shared, most-recently-
    written training result to EVERY authenticated user -- including one
    with NO project relationship at all, not only to authorized
    collaborators who are being incorrectly denied. Both directions of this
    (authorized collaborator wrongly denied; unrelated stranger wrongly
    allowed) are proven below, and both are fixed the same way: keying
    RESULTS by project_id and gating it with SharingService.check_permission
    (plan Sec 8).
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

    def _create_project(self, client: TestClient, name: str) -> str:
        response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project"]["projectId"]

    def _share_project(self, owner_client: TestClient, project_id: str, principal_id: str, permission_level: str) -> None:
        response = owner_client.post(
            f"/api/sharing/resources/project/{project_id}/share",
            json={"principalType": "user", "principalId": principal_id, "permissionLevel": permission_level},
        )
        self.assertEqual(response.status_code, 200, response.text)

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

        project_id = self._create_project(owner_client, "Modeling State Authz Baseline Project")
        self._share_project(owner_client, project_id, collaborator_id, "edit")

        collab_check = collaborator_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertTrue(collab_check.json()["access"]["allowed"])

        stranger_check = stranger_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertFalse(stranger_check.json()["access"]["allowed"])

    def test_authorized_collaborator_currently_cannot_see_owners_committed_result(self) -> None:
        """PASSES TODAY -- reproduces the ORIGINAL hypothesis's direction:
        even a correctly-authorized collaborator gets nothing back, because
        GET /api/train/last never reads a project-scoped store at all.
        """
        owner_client, owner_id, collaborator_client, collaborator_id, project_id = self._setup_shared_project_with_owner_result(
            "collab-vis"
        )
        owner_view = owner_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(owner_view.status_code, 200)

        collaborator_view = collaborator_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(collaborator_view.status_code, 200)
        # Whatever comes back for the collaborator is NOT specifically
        # scoped to their authorized project -- see the next test for what
        # they actually see instead.
        self.assertIsNone(get_scoped_result_store(collaborator_id).get_last_summary())

    def test_unrelated_unauthorized_stranger_currently_sees_the_same_shared_result_anyway(self) -> None:
        """PASSES TODAY -- the broader, corrected finding: RESULTS visibility
        via GET /api/train/last has NOTHING to do with SharingService's
        authorization decision. A stranger with zero project relationship
        (proven denied by SharingService in the baseline test above) sees
        the exact same "anonymous"-scoped result the owner does, because
        that is the only RESULTS instance any real request can reach.
        """
        owner_client, owner_id, _collaborator_client, _collaborator_id, project_id = self._setup_shared_project_with_owner_result(
            "collab-vis-stranger"
        )
        stranger_client, stranger_id = _register("collab-vis-stranger-user")
        stranger_check = stranger_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertFalse(stranger_check.json()["access"]["allowed"], "This user must NOT have project access.")

        stranger_view = stranger_client.get("/api/train/last", params={"project_id": project_id})
        self.assertEqual(stranger_view.status_code, 200)
        self.assertIsNotNone(stranger_view.json()["summary"])
        self.assertEqual(stranger_view.json()["summary"]["marker"], "OWNER_RESULT")

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

        project_id = self._create_project(owner_client, f"Modeling State {label} Project")
        self._share_project(owner_client, project_id, collaborator_id, permission_level)

        access_check = collaborator_client.get(f"/api/sharing/access-check/project/{project_id}", params={"permission": "view"})
        self.assertEqual(access_check.status_code, 200)
        self.assertTrue(access_check.json()["access"]["allowed"], "Collaborator must have real, confirmed project access before this test proceeds.")

        # The owner's real HTTP request path (not an explicit-scope write)
        # is what actually populates the shared "anonymous" RESULTS bucket
        # every subsequent request reads -- matching the module docstring's
        # confirmed mechanism.
        get_scoped_result_store("anonymous").set_last_summary(
            {"marker": "OWNER_RESULT", "project_id": project_id, "training_job_id": "job-collab-vis-demo", "ranked": [{"key": "logreg"}]}
        )
        return owner_client, owner_id, collaborator_client, collaborator_id, project_id

    @unittest.expectedFailure
    def test_results_access_should_match_project_authorization_exactly(self) -> None:
        """MIGRATION TARGET (Stage 4).

        Desired future behavior: once RESULTS is keyed by project_id (not
        user_id) and gated by SharingService.check_permission the same way
        Stage 3 gates DATASTORE, RESULTS visibility must track project
        authorization exactly -- an authorized collaborator sees the
        project's real committed result, AND an unrelated stranger does
        not. This is intentionally a single combined assertion, not two
        separate ones: today, BOTH the collaborator and a stranger can see
        the shared "anonymous" result (see the two PASSES-TODAY tests
        above), so asserting "the collaborator can see it" in isolation
        would trivially -- and misleadingly -- already be true, without
        proving anything about correct authorization. Only the conjunction
        (collaborator: yes, stranger: no) is a meaningful target, and only
        that conjunction is actually false today.
        """
        _owner_client, _owner_id, collaborator_client, collaborator_id, project_id = self._setup_shared_project_with_owner_result(
            "collab-vis-target"
        )
        stranger_client, _stranger_id = _register("collab-vis-target-stranger")

        collaborator_view = collaborator_client.get("/api/train/last", params={"project_id": project_id})
        collaborator_sees_it = collaborator_view.status_code == 200 and (collaborator_view.json().get("summary") or {}).get("marker") == "OWNER_RESULT"

        stranger_view = stranger_client.get("/api/train/last", params={"project_id": project_id})
        stranger_is_denied = stranger_view.status_code in {403, 404}

        self.assertTrue(collaborator_sees_it, "Authorized collaborator must see the project's real result.")
        self.assertTrue(stranger_is_denied, "Unrelated stranger must be denied, not shown the same shared result.")


if __name__ == "__main__":
    unittest.main()

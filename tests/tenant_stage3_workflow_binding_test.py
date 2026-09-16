"""Synthetic project-authority regression probes; never opens science data."""
from copy import deepcopy
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast import stage3_model_jobs as jobs


def authority_fixture(monkeypatch):
    projects = {}
    for pid in ("project-a", "project-b"):
        development = {"rows": 8, "startDate": "2024-01-01", "endDate": "2024-01-08"}
        oot = {"rows": 2, "startDate": "2024-01-09", "endDate": "2024-01-10", "locked": True}
        auth = SimpleNamespace(project_id=pid, review_digest=pid + "-review", gold_manifest_sha=pid + "-gold", schema=SimpleNamespace(names=["feature"]))
        auth.source_manifest_sha = pid + "-source"
        auth.contextual_manifest_sha = pid + "-context"
        policies = {}
        for kind in ("OUTLIER", "IMPUTATION"):
            policies[kind] = {"policyId": pid + kind, "policyVersion": 7, "checksum": kind * 16,
                "projectId": pid, "status": "ADOPTED", "goldManifestSha": auth.gold_manifest_sha,
                "authorityReviewDigest": auth.review_digest, "development": development, "finalOot": oot,
                "fittingRule": {"fitScope": "TRAINING_ROWS_OF_EACH_CHRONOLOGICAL_FOLD_ONLY", "validationTransform": "PARAMETERS_FROM_CORRESPONDING_TRAINING_FOLD_ONLY", "finalOotParameterFittingProhibited": True, "targetOutcomeInputsProhibited": True}}
        refs = {name: {k: policies[kind][k] for k in ("policyId", "policyVersion", "checksum")} for name, kind in (("outlier", "OUTLIER"), ("missing", "IMPUTATION"))}
        feature = {"featureSetId": pid + "-features", "projectId": pid, "status": "REGISTERED", "checksum": pid + "-feature-hash", "authority": {"goldManifestSha": auth.gold_manifest_sha, "reviewDigest": auth.review_digest}, "development": development, "finalOot": oot, "orderedFeatures": ["feature"], "unavailableExclusions": [], "treatmentPolicies": refs}
        split = {"contractId": pid + "-split", "projectId": pid, "contractVersion": 8, "status": "REGISTERED", "goldManifestSha": auth.gold_manifest_sha, "authorityReviewDigest": auth.review_digest, "development": development, "finalOot": oot, "foldCount": 1, "selectedFeatureSetIds": [feature["featureSetId"]], "checksum": pid + "-split-hash", "contract": {"selectedFeatureSets": [{"featureSetId": feature["featureSetId"], "checksum": feature["checksum"]}], "folds": [{"foldNumber": 1, "trainStart": "2024-01-01", "trainEnd": "2024-01-04", "validationStart": "2024-01-05", "validationEnd": "2024-01-08", "trainRows": 4, "validationRows": 4}], "preprocessingScope": "FIT_INSIDE_EACH_TRAINING_FOLD_ONLY", "allBlockingGatesPass": True, "qualityGates": []}}
        projects[pid] = {"auth": auth, "policies": policies, "features": [feature], "splits": [split]}
    class Projects:
        def __init__(self, db): pass
        def get(self, pid): return {"project_name": pid} if pid in projects else None
    class Features:
        def __init__(self, db): pass
        def list_versions(self, pid, digest): return projects[pid]["features"]
    class Splits:
        def __init__(self, db): pass
        def list_versions(self, pid, digest): return projects[pid]["splits"]
    class Policies:
        def __init__(self, db): pass
        def list_versions(self, pid, kind, digest): return [projects[pid]["policies"][kind]]
    for name, cls in [("ProjectRepository", Projects), ("Stage3FeatureSetRepository", Features), ("Stage3SplitContractRepository", Splits), ("Stage3TreatmentRepository", Policies)]: monkeypatch.setattr(lab, name, cls)
    monkeypatch.setattr(lab.eda, "_resolve_authority", lambda db, pid: projects[pid]["auth"])
    monkeypatch.setattr(lab, "_transformation_groups", lambda *args: None)
    monkeypatch.setattr(lab.eda, "_scan", lambda *args, **kwargs: pytest.fail("No data may be scanned by authority resolution"))
    return projects


def test_two_projects_resolve_their_own_science_concurrently(monkeypatch):
    authority_fixture(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda pid: lab.resolve_model_lab_authority(None, pid), ["project-a", "project-b"] * 20))
    assert {v.project_id for v in values} == {"project-a", "project-b"}
    for v in values:
        assert v.split["contractId"] == v.project_id + "-split"
        assert v.feature_sets[0]["featureSetId"] == v.project_id + "-features"
        assert v.outlier_policy["policyId"] == v.project_id + "OUTLIER"


@pytest.mark.parametrize("kind", ["dataset", "split", "feature", "policy", "feature-checksum", "fold", "oot"])
def test_foreign_or_tampered_science_fails_closed(monkeypatch, kind):
    projects = authority_fixture(monkeypatch)
    a, b = projects["project-a"], projects["project-b"]
    if kind == "dataset": a["auth"].project_id = "project-b"
    elif kind == "split": a["splits"] = deepcopy(b["splits"])
    elif kind == "feature": a["features"] = deepcopy(b["features"])
    elif kind == "policy": a["policies"]["OUTLIER"] = deepcopy(b["policies"]["OUTLIER"])
    elif kind == "feature-checksum": a["features"][0]["checksum"] = "tampered"
    elif kind == "fold": a["splits"][0]["contract"]["folds"][0]["trainEnd"] = "2024-01-08"
    else: a["splits"][0]["finalOot"]["locked"] = False
    with pytest.raises(lab.Stage3ModelLaboratoryError): lab.resolve_model_lab_authority(None, "project-a")


def test_missing_split_truthful_blocker(monkeypatch):
    projects = authority_fixture(monkeypatch); projects["project-a"]["splits"] = []
    with pytest.raises(lab.Stage3ModelLaboratoryError) as caught: lab.resolve_model_lab_authority(None, "project-a")
    assert caught.value.code == "MODEL_LAB_SPLIT_MISSING"


def test_payload_project_cannot_override_authority(monkeypatch):
    authority_fixture(monkeypatch); resolved = lab.resolve_model_lab_authority(None, "project-a")
    with pytest.raises(lab.Stage3ModelLaboratoryError) as caught:
        lab._validate_run_request(resolved, {"projectId": "project-b", "authorityKey": resolved.authority_key})
    assert caught.value.code == "MODEL_LAB_PROJECT_IDENTITY_MISMATCH"


def test_copied_job_plan_is_rejected():
    with pytest.raises(lab.Stage3ModelLaboratoryError) as caught:
        jobs._decode_job({"project_id": "project-a", "parameters_json": {"projectId": "project-b"}})
    assert caught.value.code == "MODEL_DEVELOPMENT_JOB_PROJECT_MISMATCH"


def test_read_boundary_does_not_mask_tamper(monkeypatch):
    monkeypatch.setattr(lab, "project_workflow_blocked", lambda db, pid, exc: {"workflowBlocked": True, "projectId": pid})
    @lab.project_read_view
    def missing(db, pid): raise lab.Stage3ModelLaboratoryError("MODEL_LAB_SPLIT_MISSING", "Missing")
    @lab.project_read_view
    def tampered(db, pid): raise lab.Stage3ModelLaboratoryError("MODEL_LAB_SPLIT_AUTHORITY_MISMATCH", "Tampered")
    assert missing(None, "project-a") == {"workflowBlocked": True, "projectId": "project-a"}
    with pytest.raises(lab.Stage3ModelLaboratoryError): tampered(None, "project-a")


@pytest.mark.parametrize("status,allowed,draft,accepted", [("active", True, False, True), ("active", False, False, False), ("disabled", True, False, False), ("active", True, True, False)])
def test_execution_actor_and_draft_hold(monkeypatch, status, allowed, draft, accepted):
    authority_fixture(monkeypatch)
    resolved = lab.resolve_model_lab_authority(None, "project-a")
    from server.security import security_store
    from server.sharing.sharing_service import SharingService
    monkeypatch.setattr(security_store, "get_user", lambda uid: {"userId": uid, "status": status})
    observed = []
    def permission(self, user, resource, project, action):
        observed.append((user["userId"], project, action)); return {"allowed": allowed}
    monkeypatch.setattr(SharingService, "check_permission", permission)
    monkeypatch.setattr(lab.Stage3TreatmentRepository, "combined_spec_state", lambda self, pid, digest: {"latestDraft": {"status": "DRAFT"} if draft else None}, raising=False)
    if accepted:
        lab.require_model_execution_authority(None, resolved, "user-a")
        assert observed == [("user-a", "project-a", "edit")]
    else:
        with pytest.raises(lab.Stage3ModelLaboratoryError): lab.require_model_execution_authority(None, resolved, "user-a")


@pytest.mark.parametrize("tamper", [None, "manifest", "project", "version", "population", "registration", "source", "registration_status", "binding"])
def test_draft_page_uses_sealed_metadata_without_parquet(monkeypatch, tamper):
    import sqlite3, json
    from contextlib import contextmanager
    from server.sports_current_statcast import stage3_player_prior_artifact_store_v2 as store
    connection = sqlite3.connect(":memory:"); connection.row_factory = sqlite3.Row
    keys = ["project_id", "specification_status", "specification_version", "created_at", "dataset_version_id", "registration_id", "activation_revision", "source_dataset_id", "source_manifest_sha", "gold_manifest_sha", "contextual_manifest_sha", "authority_review_digest", "development_start_date", "development_end_date", "development_rows", "final_oot_start_date", "final_oot_end_date", "final_oot_rows", "manifest_json", "manifest_sha256"]
    connection.execute("CREATE TABLE stage3_feature_treatment_spec_versions (" + ",".join(key + " TEXT" for key in keys) + ")")
    connection.execute("CREATE TABLE active_modeling_dataset_versions (project_id TEXT, dataset_id TEXT, dataset_version_id TEXT, activation_revision INTEGER, activation_status TEXT, metadata_json TEXT)")
    connection.execute("CREATE TABLE project_dataset_links (project_id TEXT, dataset_id TEXT, link_status TEXT, metadata_json TEXT)")
    connection.execute("CREATE TABLE sports_dataset_registrations (registration_id TEXT, dataset_id TEXT, dataset_version_id TEXT, manifest_sha TEXT, validation_status TEXT)")
    identity = {"projectId": "project-a", "registrationId": "registration-a", "datasetVersionId": "version-a", "activationRevision": 4, "sourceDatasetId": "source-a", "sourceManifestSha": "a" * 64, "goldManifestSha": "b" * 64, "contextualManifestSha": "c" * 64, "reviewDigest": "d" * 64, "authorityKey": "authority-a"}
    manifest = {"projectAuthority": identity, "developmentBoundary": {"startDate": "2024-01-01", "endDate": "2024-01-08", "rows": 8}, "finalOotIdentity": {"startDate": "2024-01-09", "endDate": "2024-01-10", "rows": 2, "locked": True, "targetsAccessed": False}, "exceptions": []}
    digest = lab._sha(manifest)
    if tamper == "project": identity["projectId"] = "project-b"
    if tamper == "population": manifest["developmentBoundary"]["rows"] = 9
    if tamper == "manifest": digest = "0" * 64
    if tamper in {"project", "population"}: digest = lab._sha(manifest)
    values = ["project-a", "DRAFT", 1, "2024-01-01", "version-a", "registration-a", 4, "source-a", "a" * 64, "b" * 64, "c" * 64, "d" * 64, "2024-01-01", "2024-01-08", 8, "2024-01-09", "2024-01-10", 2, json.dumps(manifest), digest]
    connection.execute("INSERT INTO stage3_feature_treatment_spec_versions VALUES (" + ",".join("?" for _ in values) + ")", values)
    connection.execute("INSERT INTO active_modeling_dataset_versions VALUES (?,?,?,?,?,?)", ("project-a", "foreign-source" if tamper == "source" else "source-a", "version-b" if tamper == "version" else "version-a", 4, "active", json.dumps({"registrationId": "foreign-registration" if tamper == "binding" else "registration-a"})))
    connection.execute("INSERT INTO project_dataset_links VALUES (?,?,?,?)", ("project-a", "foreign-source" if tamper == "source" else "source-a", "active", "{}"))
    connection.execute("INSERT INTO sports_dataset_registrations VALUES (?,?,?,?,?)", ("foreign-registration" if tamper == "registration" else "registration-a", "source-a", "version-a", "a" * 64, "INVALID" if tamper == "registration_status" else "VALID"))
    class DB:
        @contextmanager
        def connection(self): yield connection
    class Projects:
        def __init__(self, db): pass
        def get(self, pid): return {"project_name": "Deliberate synthetic challenger"}
    monkeypatch.setattr(lab, "ProjectRepository", Projects)
    monkeypatch.setattr(lab.eda, "_resolve_authority", lambda *args: pytest.fail("A DRAFT page must not resolve row/Parquet authority"))
    monkeypatch.setattr(store, "load_current_bundle", lambda *args, **kwargs: None)
    try:
        if tamper:
            with pytest.raises(lab.Stage3ModelLaboratoryError): lab.model_laboratory_summary(DB(), "project-a")
        else:
            value = lab.model_laboratory_summary(DB(), "project-a")
            assert value["workflowBlocked"] is True
            assert value["authority"]["projectId"] == "project-a"
            assert value["population"]["developmentRows"] == 8
            assert value["population"]["finalOotRows"] == 2
            assert value["audit"]["goldPartitionsOpened"] == 0
            assert value["treatment"]["status"] == "DRAFT"
    finally: connection.close()


def test_unconfigured_project_is_blocked_without_parquet(monkeypatch):
    import sqlite3
    from contextlib import contextmanager
    connection = sqlite3.connect(":memory:"); connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE stage3_feature_treatment_spec_versions (project_id TEXT, specification_version INTEGER, created_at TEXT)")
    connection.execute("CREATE TABLE stage3_split_contract_versions (project_id TEXT, contract_status TEXT, contract_version INTEGER, created_at TEXT)")
    class DB:
        @contextmanager
        def connection(self): yield connection
    class Projects:
        def __init__(self, db): pass
        def get(self, pid): return {"project_name": "Empty synthetic project"}
    monkeypatch.setattr(lab, "ProjectRepository", Projects)
    monkeypatch.setattr(lab.eda, "_resolve_authority", lambda *args: pytest.fail("An unconfigured page must not open data partitions"))
    try:
        state = lab.model_laboratory_summary(DB(), "project-empty")
        assert state["workflowBlocked"] is True
        assert state["authority"]["projectId"] == "project-empty"
        assert state["population"]["developmentRows"] is None
        assert state["audit"]["goldPartitionsOpened"] == 0
    finally: connection.close()


def test_copied_game_scoring_job_request_is_rejected():
    from server.sports_current_statcast import stage3_game_scoring as games
    with pytest.raises(games.Stage3GameScoringError):
        games._decode_job({"project_id": "project-a", "parameters_json": '{"projectId":"project-b"}'})

from __future__ import annotations

import copy
import uuid
from pathlib import Path

import pytest

from server.persistence.db import Database
from server.sports_datasets.constants import (
    MANIFEST_SHA,
    PARTITION_AUTHORITY_SHA,
    PROJECT_ID,
    REGISTRATION_ID,
)
from server.sports_datasets.registry import SportsDatasetRegistry
from server.sports_identity_bridges.registry import SportsIdentityBridgeRegistry
from server.sports_modeling.registry import SportsPAResearchRegistry
from server.sports_phase4.dynamic_contract import (
    PHASE3_FEATURE_CONTRACT_SHA,
    PHASE3_FEATURE_VIEW_ID,
    PHASE3_RUN_ID,
    PHASE3_RUN_SHA,
)
from server.sports_phase4.registry import (
    PHASE3_EXPERIMENT_ID,
    PHASE3_FEATURE_CONTRACT_NAME,
    PHASE3_GRAPH_ID,
    SportsPhase4Registry,
)
from tests.sports_phase4_registry_test import _seed_parent_authorities


SCRATCH_ROOT = Path(__file__).resolve().parents[1] / ".tmp"


@pytest.fixture(autouse=True)
def _isolate_phase4_runtime_root(tmp_path, monkeypatch):
    """Keep these scope tests hermetic.

    ``public_dataset`` authority-gates optional Phase 4 runtime evidence (catcher
    readiness, E1/E2 features, the incremental-signal and severe-miss studies) and the
    Phase 5 simulation components (game replay, base-out transition, simulation input) and
    attaches whatever matches the active registration under the phase4/phase5 runtime roots.
    These tests assert the *exact* phase4 projection shape, so point both runtime roots at
    empty temp directories: without it a populated live ``.runtime`` tree would attach real
    evidence and perturb the equality checks. This changes no production semantics.
    """

    monkeypatch.setenv(
        "ASP_MODEL_STUDIO_PHASE4_RUNTIME_ROOT", str(tmp_path / "phase4-runtime-empty")
    )
    monkeypatch.setenv(
        "ASP_MODEL_STUDIO_PHASE5_RUNTIME_ROOT", str(tmp_path / "phase5-runtime-empty")
    )


def _phase3_public() -> dict[str, object]:
    return {
        "paBaseline": {
            "run": {
                "runId": PHASE3_RUN_ID,
                "runSha": PHASE3_RUN_SHA,
                "projectId": PROJECT_ID,
                "parent": {"registrationId": REGISTRATION_ID},
                "experiment": {"experimentId": PHASE3_EXPERIMENT_ID},
            },
            "featureView": {
                "featureViewId": PHASE3_FEATURE_VIEW_ID,
                "contractVersion": PHASE3_FEATURE_CONTRACT_NAME,
                "contractSha": PHASE3_FEATURE_CONTRACT_SHA,
            },
            "graph": {"graphId": PHASE3_GRAPH_ID},
            "decision": {"terminalStatus": "RESEARCH_BASELINE"},
        }
    }


def _phase4_public() -> dict[str, object]:
    return {
        "schemaVersion": "MLB_PHASE4_RESEARCH_STUDY_V1",
        "studyId": f"sports-phase4-study:sha256:{'a' * 64}",
        "projectId": PROJECT_ID,
        "dataset": {
            "registrationId": REGISTRATION_ID,
            "manifestSha": MANIFEST_SHA,
            "partitionAuthoritySha": PARTITION_AUTHORITY_SHA,
        },
        "phase3Baseline": {
            "runId": PHASE3_RUN_ID,
            "runSha": PHASE3_RUN_SHA,
            "experimentId": PHASE3_EXPERIMENT_ID,
            "featureContractName": PHASE3_FEATURE_CONTRACT_NAME,
            "featureContractSha": PHASE3_FEATURE_CONTRACT_SHA,
            "featureViewId": PHASE3_FEATURE_VIEW_ID,
            "graphId": PHASE3_GRAPH_ID,
            "status": "RESEARCH_BASELINE",
        },
    }


@pytest.fixture()
def dataset_registry(monkeypatch: pytest.MonkeyPatch) -> SportsDatasetRegistry:
    root = SCRATCH_ROOT / f"sports-dataset-phase4-scope-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    database = Database(root / "registry.db")
    database.initialize()
    _seed_parent_authorities(database)
    monkeypatch.setattr(
        SportsIdentityBridgeRegistry,
        "public_active",
        lambda self: None,
    )
    monkeypatch.setattr(
        SportsPAResearchRegistry,
        "public_active",
        lambda self: copy.deepcopy(_phase3_public()),
    )
    return SportsDatasetRegistry(database)


def _project(
    registry: SportsDatasetRegistry,
    monkeypatch: pytest.MonkeyPatch,
    phase4: dict[str, object],
) -> dict[str, object]:
    monkeypatch.setattr(
        SportsPhase4Registry,
        "public_active",
        lambda self: {"phase4": copy.deepcopy(phase4)},
    )
    registration = registry.get(REGISTRATION_ID)
    assert registration is not None
    return registry.public_dataset(registration)


def test_phase4_attaches_only_as_a_separate_exact_parent_child(
    dataset_registry: SportsDatasetRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phase4 = _phase4_public()
    public = _project(dataset_registry, monkeypatch, phase4)
    assert public["phase4"] == phase4
    assert public["paBaseline"] == _phase3_public()["paBaseline"]
    assert public["phase4"]["phase3Baseline"] is not public["paBaseline"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.__setitem__("projectId", "sports-project:wrong"),
        lambda value: value["dataset"].__setitem__("registrationId", "sports-dataset:wrong"),
        lambda value: value["dataset"].__setitem__("manifestSha", "f" * 64),
        lambda value: value["dataset"].__setitem__("partitionAuthoritySha", "f" * 64),
        lambda value: value["phase3Baseline"].__setitem__("runId", "sports-pa-run:wrong"),
        lambda value: value["phase3Baseline"].__setitem__("runSha", "f" * 64),
        lambda value: value["phase3Baseline"].__setitem__("experimentId", "mlb-pa-experiment:wrong"),
        lambda value: value["phase3Baseline"].__setitem__("featureContractSha", "f" * 64),
        lambda value: value["phase3Baseline"].__setitem__("graphId", "mlb-pa-model-graph:wrong"),
    ],
)
def test_phase4_scope_mismatch_is_not_projected(
    dataset_registry: SportsDatasetRegistry,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
) -> None:
    phase4 = _phase4_public()
    mutate(phase4)
    public = _project(dataset_registry, monkeypatch, phase4)
    assert "phase4" not in public
    assert public["paBaseline"] == _phase3_public()["paBaseline"]

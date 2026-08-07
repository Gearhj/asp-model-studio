from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid

import pytest

from scripts.run_bureau_metadata_isolated_services import REQUIRED_AUTHORITIES
from scripts.write_bureau_metadata_browser_reload_evidence import (
    BrowserEvidenceError,
    write_browser_reload_evidence,
)


TEST_AUTHORITY_ROOT = Path(
    os.environ.get("ATLAS_HERMETIC_ROOT")
    or os.environ.get("TEMP")
    or os.getcwd()
).resolve()


def _case_root(label: str) -> Path:
    root = (
        TEST_AUTHORITY_ROOT
        / "authorities"
        / "browser-reload-evidence-tests"
        / f"{label}-{uuid.uuid4().hex}"
    )
    root.mkdir(parents=True, exist_ok=False)
    return root


def _authority_map(case_root: Path) -> tuple[Path, Path]:
    base = case_root / "authorities"
    base.mkdir()
    rows: list[dict[str, object]] = []
    for name in REQUIRED_AUTHORITIES:
        authority = base / name
        authority.mkdir()
        rows.append(
            {
                "authority": name,
                "canonical_path": str(authority.resolve()),
                "classification": "isolated",
                "overlap_result": "distinct",
                "reparse_point": False,
            }
        )
    payload = {
        "schema_version": 1,
        "run_id": "browser-evidence-fixture",
        "base_root": str(base.resolve()),
        "repository_root": str(Path(__file__).resolve().parents[1]),
        "authorities": rows,
    }
    path = case_root / "isolated-authority-map.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, base / "test-output"


def _accepted_kwargs(authority_map: Path) -> dict[str, object]:
    return {
        "authority_map": authority_map,
        "run_id": "browser-run-01",
        "frontend_port": 49101,
        "backend_port": 49102,
        "attempts": 60,
        "successes": 60,
        "synthetic_user_count": 2,
        "synthetic_project_count": 5,
        "synthetic_provider_count": 2,
        "cross_user_contamination": 0,
        "cross_project_contamination": 0,
        "cross_provider_contamination": 0,
        "final_holdout_accessed": False,
        "training_started": False,
    }


def test_a_writer_module_is_safe_before_isolated_contract_import() -> None:
    assert not any(
        name == "server" or name.startswith("server.")
        for name in sys.modules
    )


def test_writes_validated_evidence_under_isolated_test_output() -> None:
    authority_map, evidence_root = _authority_map(_case_root("accepted"))
    path, payload = write_browser_reload_evidence(
        **_accepted_kwargs(authority_map),
    )

    assert path.is_relative_to(evidence_root.resolve())
    assert payload["authenticated_reload_successes"] == 60
    from scripts.run_bureau_metadata_operational_soak import (
        _load_frontend_reload_evidence,
    )

    loaded = _load_frontend_reload_evidence(
        path,
        minimum_reloads=60,
        allowed_evidence_root=evidence_root,
    )
    assert loaded["status"] == "verified"
    assert loaded["live_port_contacted"] is False
    assert payload["live_authority_accessed"] is False


@pytest.mark.parametrize(
    ("attempts", "successes"),
    ((59, 59), (60, 59)),
)
def test_rejects_incomplete_reload_coverage(
    attempts: int, successes: int
) -> None:
    authority_map, _evidence_root = _authority_map(_case_root("coverage"))
    values = _accepted_kwargs(authority_map)
    values.update({"attempts": attempts, "successes": successes})
    with pytest.raises(BrowserEvidenceError, match="minimums"):
        write_browser_reload_evidence(**values)


@pytest.mark.parametrize("port_pair", ((5174, 49122), (49121, 8001)))
def test_rejects_live_ports(port_pair: tuple[int, int]) -> None:
    authority_map, _evidence_root = _authority_map(_case_root("live-port"))
    values = _accepted_kwargs(authority_map)
    values.update({"frontend_port": port_pair[0], "backend_port": port_pair[1]})
    with pytest.raises(Exception, match="prohibited live service port"):
        write_browser_reload_evidence(**values)


@pytest.mark.parametrize(
    "contradiction",
    (
        {"cross_user_contamination": 1},
        {"cross_project_contamination": 1},
        {"cross_provider_contamination": 1},
        {"final_holdout_accessed": True},
        {"training_started": True},
    ),
)
def test_rejects_contamination_holdout_or_training(
    contradiction: dict[str, object],
) -> None:
    authority_map, _evidence_root = _authority_map(_case_root("contradiction"))
    values = _accepted_kwargs(authority_map)
    values.update(contradiction)
    with pytest.raises(BrowserEvidenceError, match="contradictory"):
        write_browser_reload_evidence(**values)

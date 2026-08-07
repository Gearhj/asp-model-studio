from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_bureau_metadata_integrated_closeout as closeout
from tests.hermetic_test_roots import temporary_test_root


@pytest.fixture
def tmp_path():
    """Keep synthetic closeout fixtures inside the launcher-owned authority."""

    with temporary_test_root(
        "bureau-integrated-closeout-",
        scope="bureau-integrated-closeout-fixtures",
    ) as root:
        yield root


def _settings(tmp_path: Path, **overrides):
    values = {
        "authority_map": tmp_path / "isolated-authority-map.json",
        "backend_port": 19081,
        "frontend_port": 19082,
        "duration_seconds": 0.2,
        "restart_cycle_count": 1,
        "user_count": 2,
        "project_count": 2,
        "catalog_version_count": 1,
        "bounded_operation_count": 2,
        "crosswalk_preview_count": 1,
        "decision_write_count": 2,
        "service_reload_count": 1,
        "unauthorized_attempt_count": 1,
        "conflict_trial_count": 1,
        "max_workers": 2,
        "heartbeat_seconds": 0.01,
        "headed_browser": False,
        "enforce_release_minimums": False,
    }
    values.update(overrides)
    return closeout.IntegratedCloseoutSettings(**values)


def test_release_minimums_cannot_be_bypassed_by_the_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(closeout, "_assert_ports", lambda *_args: None)
    scaled = _settings(tmp_path, enforce_release_minimums=True)
    with pytest.raises(closeout.IntegratedCloseoutError, match="release minimums"):
        scaled.validate()
    with pytest.raises(SystemExit):
        closeout._parser().parse_args(
            [
                "--authority-map",
                str(tmp_path / "isolated-authority-map.json"),
                "--backend-port",
                "19081",
                "--frontend-port",
                "19082",
                "--enforce-release-minimums=false",
            ]
        )


def test_scaled_short_duration_bypass_exists_only_on_constructed_test_settings(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(closeout, "_assert_ports", lambda *_args: None)
    settings = _settings(tmp_path)
    settings.validate()
    soak = closeout._soak_settings(
        settings,
        tmp_path / "synthetic-reload-evidence.json",
        authority_map=settings.authority_map,
    )
    assert soak.enforce_release_minimums is False
    assert soak.duration_seconds == pytest.approx(0.2)
    assert soak.user_count == 2
    assert soak.project_count == 2
    assert soak.service_reload_count == 1


def test_operational_authority_map_resolves_identical_direct_in_base_copy(
    tmp_path,
    monkeypatch,
):
    base = tmp_path / "isolated-base"
    safety = tmp_path / "safety-copy"
    base.mkdir()
    safety.mkdir()
    configured = safety / "isolated-authority-map.json"
    canonical = base / configured.name
    payload = b'{"classification":"synthetic-authority-map"}'
    configured.write_bytes(payload)
    canonical.write_bytes(payload)
    observed = []

    def validate(path):
        observed.append(path)
        return SimpleNamespace(
            authority_map_checksum=closeout.hashlib.sha256(payload).hexdigest()
        )

    monkeypatch.setattr(closeout, "_load_soak_authority_map", validate)

    resolved = closeout._resolve_operational_authority_map(
        configured,
        isolated_base=base,
    )

    assert resolved == canonical.resolve(strict=True)
    assert resolved.parent == base.resolve(strict=True)
    assert observed == [resolved]
    soak = closeout._soak_settings(
        _settings(tmp_path, authority_map=configured),
        tmp_path / "synthetic-reload-evidence.json",
        authority_map=resolved,
    )
    assert soak.authority_map == resolved


def test_operational_authority_map_fails_when_in_base_copy_is_missing(tmp_path):
    base = tmp_path / "isolated-base"
    safety = tmp_path / "safety-copy"
    base.mkdir()
    safety.mkdir()
    configured = safety / "isolated-authority-map.json"
    configured.write_bytes(b'{"classification":"synthetic-authority-map"}')

    with pytest.raises(closeout.IntegratedCloseoutError, match="unavailable"):
        closeout._resolve_operational_authority_map(
            configured,
            isolated_base=base,
        )


def test_operational_authority_map_fails_when_safety_copy_differs(tmp_path, monkeypatch):
    base = tmp_path / "isolated-base"
    safety = tmp_path / "safety-copy"
    base.mkdir()
    safety.mkdir()
    configured = safety / "isolated-authority-map.json"
    canonical = base / configured.name
    configured.write_bytes(b'{"revision":1}')
    canonical.write_bytes(b'{"revision":2}')
    operational_validation_called = False

    def validate(_path):
        nonlocal operational_validation_called
        operational_validation_called = True
        raise AssertionError("operational validation must not run after a byte mismatch")

    monkeypatch.setattr(closeout, "_load_soak_authority_map", validate)

    with pytest.raises(closeout.IntegratedCloseoutError, match="does not match"):
        closeout._resolve_operational_authority_map(
            configured,
            isolated_base=base,
        )
    assert operational_validation_called is False


def test_operational_authority_map_wraps_strict_soak_validation_failure(
    tmp_path,
    monkeypatch,
):
    base = tmp_path / "isolated-base"
    safety = tmp_path / "safety-copy"
    base.mkdir()
    safety.mkdir()
    configured = safety / "isolated-authority-map.json"
    canonical = base / configured.name
    payload = b'{"classification":"synthetic-authority-map"}'
    configured.write_bytes(payload)
    canonical.write_bytes(payload)

    def reject(_path):
        raise closeout.SoakConfigurationError("synthetic strict-validator rejection")

    monkeypatch.setattr(closeout, "_load_soak_authority_map", reject)

    with pytest.raises(closeout.IntegratedCloseoutError, match="operational validation"):
        closeout._resolve_operational_authority_map(
            configured,
            isolated_base=base,
        )


def test_missing_canonical_map_fails_before_run_scope_allocation(
    tmp_path,
    monkeypatch,
):
    base = tmp_path / "isolated-base"
    safety = tmp_path / "safety-copy"
    base.mkdir()
    safety.mkdir()
    configured = safety / "isolated-authority-map.json"
    configured.write_bytes(b'{"classification":"synthetic-authority-map"}')
    run_scope_allocated = False

    monkeypatch.setattr(closeout, "_assert_ports", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(closeout, "_port_is_open", lambda _port: False)
    monkeypatch.setattr(
        closeout,
        "_load_authority_map",
        lambda _path: (base.resolve(strict=True), {}),
    )

    def allocate(_roots):
        nonlocal run_scope_allocated
        run_scope_allocated = True
        raise AssertionError("run scopes must not be allocated before map preflight")

    monkeypatch.setattr(closeout, "_create_run_scopes", allocate)

    with pytest.raises(closeout.IntegratedCloseoutError, match="unavailable"):
        closeout._run_integrated_closeout_with_ports(
            _settings(tmp_path, authority_map=configured)
        )
    assert run_scope_allocated is False


def test_restart_schedule_distributes_every_actual_cycle_inside_one_window():
    schedule = closeout._restart_schedule(1_800, 10)
    assert len(schedule) == 10
    assert schedule == tuple(sorted(schedule))
    assert schedule[0] > 0
    assert schedule[-1] < 1_800
    assert len(set(schedule)) == 10


def test_timed_browser_phase_executes_sixty_authenticated_reloads_in_window():
    plan = closeout.BROWSER_PHASE_RELOAD_PLANS["timed-window"]
    assert plan.expected_authenticated_reloads >= 60
    phases = [
        {
            "inside_operational_window": False,
            "authenticated_reload_attempts": 26,
            "authenticated_reload_successes": 26,
        },
        {
            "inside_operational_window": True,
            "authenticated_reload_attempts": plan.expected_authenticated_reloads,
            "authenticated_reload_successes": plan.expected_authenticated_reloads,
        },
        {
            "inside_operational_window": False,
            "authenticated_reload_attempts": 26,
            "authenticated_reload_successes": 26,
        },
    ]
    assert closeout._reload_totals(
        phases,
        inside_operational_window_only=True,
    ) == (
        plan.expected_authenticated_reloads,
        plan.expected_authenticated_reloads,
    )


def test_browser_profile_cli_path_preserves_the_exact_authority(tmp_path):
    profile = tmp_path / "isolated-browser-profile"
    profile.mkdir()

    cli_path = closeout._browser_profile_cli_path(profile)

    assert cli_path.resolve(strict=True) == profile.resolve(strict=True)
    if os.name == "nt":
        assert len(str(cli_path)) <= closeout.MAX_WINDOWS_BROWSER_PROFILE_PHASE_LENGTH


def test_all_21_authorities_receive_one_unique_disjoint_run_child(tmp_path):
    roots = {}
    for authority in closeout.REQUIRED_AUTHORITIES:
        root = tmp_path / authority
        root.mkdir()
        roots[authority] = root
    run_id, scopes = closeout._create_run_scopes(roots)
    assert set(scopes) == set(closeout.REQUIRED_AUTHORITIES)
    assert len(scopes) == 21
    assert {scope.name for scope in scopes.values()} == {run_id}
    assert len({scope.resolve() for scope in scopes.values()}) == 21
    assert all(
        scope.parent == roots[authority].resolve()
        for authority, scope in scopes.items()
    )


def test_exact_recovery_gate_requires_catalog_entitlement_crosswalk_and_no_fallback():
    expected = {
        "run_id": "integrated-closeout-current-run",
        "catalog_version_id": "synthetic-catalog-version",
        "catalog_checksum": "a" * 64,
        "governance_id": "synthetic-governance",
        "revision": 3,
        "revision_checksum": "b" * 64,
    }
    payload = {
        "ok": True,
        "run_id": expected["run_id"],
        "catalog": {
            "catalog_version_id": expected["catalog_version_id"],
            "catalog_checksum": expected["catalog_checksum"],
            "integrity_status": "verified",
            "exact_identity_verified": True,
        },
        "entitlement": {
            "catalog_health_verified": True,
            "crosswalk_candidate_verified": True,
        },
        "crosswalk": {
            "governance_id": expected["governance_id"],
            "revision": expected["revision"],
            "revision_checksum": expected["revision_checksum"],
            "checksum_verified": True,
        },
        "no_first_or_latest_fallback": True,
    }
    result = closeout._validate_exact_recovery(payload, expected)
    assert result["exact_catalog_recovered"] is True
    assert result["exact_crosswalk_recovered"] is True
    assert result["catalog_entitlement_verified"] is True
    assert result["crosswalk_entitlement_verified"] is True

    contradictory = dict(payload)
    contradictory["no_first_or_latest_fallback"] = False
    with pytest.raises(closeout.IntegratedCloseoutError, match="contradictory"):
        closeout._validate_exact_recovery(contradictory, expected)


def test_current_run_reload_evidence_is_checksummed_and_rejects_live_ports(tmp_path):
    allowed = tmp_path / "test-output"
    run_scope = allowed / "production-auth-synthetic"
    run_scope.mkdir(parents=True)
    phase = {
        "phase": "timed-window",
        "run_id": "integrated-closeout-current-run",
        "inside_operational_window": True,
        "authenticated_reload_attempts": 10,
        "authenticated_reload_successes": 10,
        "synthetic_user_count": 2,
        "synthetic_project_count": 2,
        "synthetic_provider_count": 2,
        "cross_user_contamination": 0,
        "cross_project_contamination": 0,
        "cross_provider_contamination": 0,
    }
    evidence = closeout._write_reload_evidence(
        run_scope / "frontend-reload-evidence.json",
        run_id="integrated-closeout-current-run",
        frontend_port=19082,
        backend_port=19081,
        phases=[phase],
        allowed_evidence_root=allowed,
    )
    assert evidence["run_id"] == "integrated-closeout-current-run"
    assert evidence["evidence_checksum"]

    with pytest.raises(closeout.IntegratedCloseoutError, match="current integrated run"):
        closeout._write_reload_evidence(
            run_scope / "wrong-run-evidence.json",
            run_id="different-run",
            frontend_port=19082,
            backend_port=19081,
            phases=[phase],
            allowed_evidence_root=allowed,
        )

    with pytest.raises(Exception, match="live service port"):
        closeout._write_reload_evidence(
            run_scope / "live-port-evidence.json",
            run_id="integrated-closeout-current-run",
            frontend_port=closeout.LIVE_FRONTEND_PORT,
            backend_port=19081,
            phases=[phase],
            allowed_evidence_root=allowed,
        )


def test_progress_rows_and_combined_payload_have_stable_checksums(tmp_path):
    progress = closeout._ProgressEvidence(
        tmp_path / "progress.jsonl",
        "integrated-closeout-test",
        closeout.time.monotonic(),
    )
    progress.append("short_test_heartbeat", total_requests=2, unexpected_failures=0)
    row = closeout.json.loads((tmp_path / "progress.jsonl").read_text(encoding="utf-8"))
    checksum = row.pop("event_checksum")
    assert checksum == closeout._checksum(row)
    summary = {"run_id": "integrated-closeout-test", "passed": True}
    assert closeout._checksum(summary) == closeout._checksum(dict(reversed(tuple(summary.items()))))


def test_data_acquisition_integration_event_matrix_is_bounded_and_complete(tmp_path):
    event_path = tmp_path / closeout.INTEGRATION_EVENT_FILE
    rows = [
        ("binding_preview", 200),
        ("crosswalk_preview", 200),
        ("decision_write", 409),
        ("binding_link_retry", 200),
        ("semantic_batch", 200),
        ("catalog_search_or_lookup", 200),
        ("entitlement_revoke", 200),
        ("binding_preview", 422),
    ]
    event_path.write_text(
        "".join(
            closeout.json.dumps(
                {
                    "schema_version": "1.0",
                    "classification": "synthetic_bureau_metadata_integration_event",
                    "category": category,
                    "status": status,
                },
                sort_keys=True,
            )
            + "\n"
            for category, status in rows
        ),
        encoding="utf-8",
    )
    evidence = closeout._load_integration_event_counts(event_path)
    assert evidence["required_categories_present"] is True
    assert evidence["conflict_count"] == 1
    assert evidence["malformed_count"] == 1
    assert evidence["total_events"] == len(rows)
    assert evidence["evidence_checksum"]

    event_path.write_text(
        closeout.json.dumps(
            {
                "classification": "synthetic_bureau_metadata_integration_event",
                "category": "binding_preview",
                "status": 200,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(closeout.IntegratedCloseoutError, match="matrix is incomplete"):
        closeout._load_integration_event_counts(event_path)


def test_runtime_metric_delta_preserves_unavailable_measurements_as_null():
    available = closeout._runtime_metric_delta(
        {"available": True, "rss_bytes": 100, "handles": 8},
        {"available": True, "rss_bytes": 175, "handles": 10},
    )
    assert available["rss_delta_bytes"] == 75
    assert available["handle_delta"] == 2
    assert available["reported_unavailable_not_zero"] is False

    unavailable = closeout._runtime_metric_delta(
        {"available": False, "rss_bytes": None, "handles": None},
        {"available": False, "rss_bytes": None, "handles": None},
    )
    assert unavailable["rss_delta_bytes"] is None
    assert unavailable["handle_delta"] is None
    assert unavailable["reported_unavailable_not_zero"] is True


def test_integrated_harness_wires_the_production_da_surface_and_five_scenarios():
    harness_source = Path(closeout.__file__).read_text(encoding="utf-8")
    browser_source = (
        Path(closeout.__file__).resolve().parents[1]
        / "tests"
        / "bureauMetadataIntegration.production.acceptance.mjs"
    ).read_text(encoding="utf-8")
    build_source = (
        Path(closeout.__file__).resolve().parents[1]
        / "scripts"
        / "run_bureau_metadata_production_auth_acceptance.py"
    ).read_text(encoding="utf-8")
    backend_smoke_source = (
        Path(closeout.__file__).resolve().parents[1]
        / "tests"
        / "run_bureau_metadata_integration_backend_smoke.py"
    ).read_text(encoding="utf-8")
    entry_source = (
        Path(closeout.__file__).resolve().parents[1]
        / "tests"
        / "bureauMetadataIntegration.isolated.entry.tsx"
    ).read_text(encoding="utf-8")
    runtime_source = (
        Path(closeout.__file__).resolve().parents[1]
        / "tests"
        / "bureau_metadata_integration_runtime_app.py"
    ).read_text(encoding="utf-8")

    assert "tests.bureau_metadata_integration_runtime_app:app" in harness_source
    assert "bureauMetadataIntegration.production.acceptance.mjs" in harness_source
    assert "bureauMetadataIntegration.vite.config.ts" in build_source
    assert 'project_scenarios: ["A_exact"' in browser_source
    assert "canonical_eda_handoff_verified: true" in browser_source
    assert "final_holdout_accessed: false" in browser_source
    assert "training_started: false" in browser_source
    assert "BureauMetadataBindingPanel" in entry_source
    assert "BureauReviewPanel" in entry_source
    assert "synthetic-canonical-eda-handoff" in entry_source
    assert "special-value-feature-table" in browser_source
    assert "special-value-treatment-SYN000" in browser_source
    assert "review-special-value-codes-SYN000" in browser_source
    assert "bureau-semantic-source-details" in browser_source
    assert 'mapping_state: "approved_alias"' in browser_source
    assert 'mapping_state: "ambiguous_review_required"' in browser_source
    assert 'mapping_state: "rejected"' in browser_source
    assert "synthetic-contradiction-SYN000" in browser_source
    assert "bureau-metadata-expanded-code-level-metadata.png" in browser_source
    assert "bureau-metadata-canonical-eda-handoff.png" in browser_source
    assert "approved_institutional_alias" in runtime_source
    assert "multiple_possible_matches" in runtime_source
    assert "/api/data/bureau-detection" in runtime_source
    assert "/api/data/special-value-review" in runtime_source
    assert 'serviceWorkers: "block"' in browser_source
    assert 'violation("websocket_or_hmr")' in browser_source
    assert "reserve_dynamic_non_live_ports" in backend_smoke_source
    assert "_start_backend_cycle" in backend_smoke_source
    assert "_validate_exact_recovery" in backend_smoke_source
    assert "browser_started\": False" in backend_smoke_source
    assert "chromium" not in backend_smoke_source.casefold()
    assert "playwright" not in backend_smoke_source.casefold()

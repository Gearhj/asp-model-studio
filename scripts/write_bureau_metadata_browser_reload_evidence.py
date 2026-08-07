"""Persist checksummed isolated browser-reload evidence for the catalog soak.

This utility is intentionally narrow.  It accepts only aggregate results from
the current synthetic browser run, validates the existing isolated authority
map, and writes one evidence document beneath that map's test-output root.
It never reads browser storage and it cannot target the live ATLAS ports.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Sequence

from scripts.isolated_loopback_ports import validate_non_live_ports
from scripts.run_bureau_metadata_isolated_services import (
    _apply_preimport_pins,
    _create_run_scopes,
    _environment_pins,
    _load_authority_map,
)


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REQUIRED_AUTHENTICATED_RELOADS = 60


class BrowserEvidenceError(RuntimeError):
    """Fail-closed validation error with a non-sensitive message."""


def write_browser_reload_evidence(
    *,
    authority_map: Path,
    run_id: str,
    frontend_port: int,
    backend_port: int,
    attempts: int,
    successes: int,
    synthetic_user_count: int,
    synthetic_project_count: int,
    synthetic_provider_count: int,
    cross_user_contamination: int,
    cross_project_contamination: int,
    cross_provider_contamination: int,
    final_holdout_accessed: bool,
    training_started: bool,
) -> tuple[Path, dict[str, object]]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise BrowserEvidenceError("The synthetic browser run identifier is invalid.")
    if (
        attempts < REQUIRED_AUTHENTICATED_RELOADS
        or successes != attempts
        or min(
            synthetic_user_count,
            synthetic_project_count,
            synthetic_provider_count,
        )
        < 2
    ):
        raise BrowserEvidenceError("The browser acceptance minimums were not met.")
    if (
        min(
            cross_user_contamination,
            cross_project_contamination,
            cross_provider_contamination,
        )
        < 0
        or any(
            value != 0
            for value in (
                cross_user_contamination,
                cross_project_contamination,
                cross_provider_contamination,
            )
        )
        or final_holdout_accessed is not False
        or training_started is not False
    ):
        raise BrowserEvidenceError("The browser acceptance isolation result is contradictory.")
    try:
        validate_non_live_ports((frontend_port, backend_port))
    except Exception as exc:
        raise BrowserEvidenceError(
            "Frontend reload evidence references a prohibited live service port."
        ) from exc
    if any(
        name == "server"
        or name.startswith("server.")
        or name == "scripts.run_bureau_metadata_integrated_closeout"
        for name in sys.modules
    ):
        raise BrowserEvidenceError(
            "Browser reload evidence must run in a fresh isolated process."
        )

    base, roots = _load_authority_map(authority_map)
    isolation_run_id, scopes = _create_run_scopes(roots)
    pins = _environment_pins(
        base,
        scopes,
        run_id=isolation_run_id,
        backend_port=backend_port,
        frontend_port=frontend_port,
    )
    evidence_scope = scopes["test-output"] / "browser-reload-evidence"
    evidence_scope.mkdir(parents=False, exist_ok=False)
    evidence_path = evidence_scope / "frontend-reload-evidence.json"
    phase = {
        "run_id": run_id,
        "authenticated_reload_attempts": attempts,
        "authenticated_reload_successes": successes,
        "synthetic_user_count": synthetic_user_count,
        "synthetic_project_count": synthetic_project_count,
        "synthetic_provider_count": synthetic_provider_count,
        "cross_user_contamination": cross_user_contamination,
        "cross_project_contamination": cross_project_contamination,
        "cross_provider_contamination": cross_provider_contamination,
    }
    inherited_environment = os.environ.copy()
    try:
        _apply_preimport_pins(os.environ, pins)
        # Import the established checksum/loader contract only after every
        # mutable authority has been pinned to this isolated writer run.
        from scripts.run_bureau_metadata_integrated_closeout import (
            _write_reload_evidence,
        )

        payload = dict(
            _write_reload_evidence(
                evidence_path,
                run_id=run_id,
                frontend_port=frontend_port,
                backend_port=backend_port,
                phases=(phase,),
                allowed_evidence_root=scopes["test-output"],
            )
        )
    finally:
        os.environ.clear()
        os.environ.update(inherited_environment)
    return evidence_path.resolve(strict=True), payload


def _strict_bool(value: str) -> bool:
    normalized = str(value).strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise argparse.ArgumentTypeError("Expected true or false.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write validated synthetic browser reload evidence."
    )
    parser.add_argument("--authority-map", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--frontend-port", type=int, required=True)
    parser.add_argument("--backend-port", type=int, required=True)
    parser.add_argument("--attempts", type=int, required=True)
    parser.add_argument("--successes", type=int, required=True)
    parser.add_argument("--synthetic-user-count", type=int, required=True)
    parser.add_argument("--synthetic-project-count", type=int, required=True)
    parser.add_argument("--synthetic-provider-count", type=int, required=True)
    parser.add_argument("--cross-user-contamination", type=int, required=True)
    parser.add_argument("--cross-project-contamination", type=int, required=True)
    parser.add_argument("--cross-provider-contamination", type=int, required=True)
    parser.add_argument("--final-holdout-accessed", type=_strict_bool, required=True)
    parser.add_argument("--training-started", type=_strict_bool, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence_path, payload = write_browser_reload_evidence(
            authority_map=args.authority_map,
            run_id=args.run_id,
            frontend_port=args.frontend_port,
            backend_port=args.backend_port,
            attempts=args.attempts,
            successes=args.successes,
            synthetic_user_count=args.synthetic_user_count,
            synthetic_project_count=args.synthetic_project_count,
            synthetic_provider_count=args.synthetic_provider_count,
            cross_user_contamination=args.cross_user_contamination,
            cross_project_contamination=args.cross_project_contamination,
            cross_provider_contamination=args.cross_provider_contamination,
            final_holdout_accessed=args.final_holdout_accessed,
            training_started=args.training_started,
        )
    except Exception as exc:
        if isinstance(exc, BrowserEvidenceError):
            print("browser-reload-evidence failed: acceptance minimum", flush=True)
        else:
            print(
                f"browser-reload-evidence failed: {type(exc).__name__}",
                flush=True,
            )
        return 1
    print(
        json.dumps(
            {
                "evidence_path": str(evidence_path),
                "evidence_checksum": payload["evidence_checksum"],
                "authenticated_reload_successes": payload[
                    "authenticated_reload_successes"
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

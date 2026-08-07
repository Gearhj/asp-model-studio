"""Execute a short, explicitly non-release integrated runtime smoke.

This helper exists only to validate Windows process, listener, browser, and
teardown mechanics before the release CLI is allowed to run for 30 minutes.
It cannot produce release evidence because it constructs settings with the
release minimums disabled and labels its output accordingly.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_bureau_metadata_integrated_closeout import (
    IntegratedCloseoutSettings,
    run_integrated_closeout,
)
from scripts.isolated_loopback_ports import reserve_dynamic_non_live_ports


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-map", required=True, type=Path)
    parser.add_argument("--backend-port", default=0, type=int)
    parser.add_argument("--frontend-port", default=0, type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    reservations = None
    try:
        if args.backend_port == 0 and args.frontend_port == 0:
            reservations = reserve_dynamic_non_live_ports()
            backend_port = reservations.ports["backend"]
            frontend_port = reservations.ports["frontend"]
        elif args.backend_port == 0 or args.frontend_port == 0:
            raise ValueError(
                "Specify both isolated ports or allow both to be assigned dynamically."
            )
        else:
            backend_port = args.backend_port
            frontend_port = args.frontend_port
        result = run_integrated_closeout(
            IntegratedCloseoutSettings(
                authority_map=args.authority_map,
                backend_port=backend_port,
                frontend_port=frontend_port,
                duration_seconds=90.0,
                restart_cycle_count=2,
                user_count=2,
                project_count=2,
                catalog_version_count=1,
                bounded_operation_count=12,
                crosswalk_preview_count=4,
                decision_write_count=4,
                service_reload_count=1,
                unauthorized_attempt_count=2,
                conflict_trial_count=2,
                max_workers=2,
                heartbeat_seconds=2.0,
                headed_browser=True,
                enforce_release_minimums=False,
            ),
            port_reservations=reservations,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "synthetic_integrated_catalog_smoke",
                    "ok": False,
                    "failure_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        if reservations is not None:
            reservations.close()
    print(
        json.dumps(
            {
                "classification": "synthetic_integrated_catalog_smoke",
                "ok": bool(result.get("passed")),
                "run_id": result.get("run_id"),
                "actual_backend_restart_count": result.get(
                    "actual_backend_restart_count"
                ),
                "network_contact_guard": result.get("network_contact_guard"),
                "isolation": result.get("isolation"),
                "evidence_checksum": result.get("evidence_checksum"),
            },
            sort_keys=True,
        )
    )
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())

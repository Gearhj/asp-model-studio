"""Committed governed seeder for the Phase 7D.5A isolated gate (Workstream E).

Publishes a fresh Gen-3 v2 + Gen-2 v1 authority into an ISOLATED, throwaway runtime root through the ACTUAL
production publisher (``server.sports_modeling.gen3_publish.publish_object`` via ``tests._hermetic_gen3._seed_objects``)
— NEVER by copying the user's shared development ``.runtime``. Run as::

    ASP_MODEL_STUDIO_RUNTIME_ROOT=<abs throwaway path>  python -m tests._governed_runtime_seed

It fails closed unless the target root is an absolute path that neither IS nor overlaps the shared development
``.runtime`` and is not inside the repository tree, drops a ``.governed-synthetic-seed`` marker (so real-data tests
stand down), and writes a ``seed-inventory.json`` describing exactly what it published. After this, the governed
selection RUNS its hermetic / catalog-driven V2-evidence tests reproducibly from a fresh checkout + empty root.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_REAL_RUNTIME = (_REPO / ".runtime" / "asp-model-studio").resolve()


def _refuse(msg: str) -> "NoReturn":  # noqa: F821
    print("SEED-REFUSED " + msg, file=sys.stderr, flush=True)
    raise SystemExit(2)


def main() -> int:
    override = os.environ.get("ASP_MODEL_STUDIO_RUNTIME_ROOT")
    if not override:
        _refuse("ASP_MODEL_STUDIO_RUNTIME_ROOT must be set to an isolated throwaway root")
    p = Path(override)
    if not p.is_absolute():
        _refuse("runtime root must be an ABSOLUTE path")
    root = p.resolve()
    if root == _REAL_RUNTIME or _REAL_RUNTIME in root.parents or root in _REAL_RUNTIME.parents:
        _refuse("refusing to seed into / overlapping the shared development .runtime: " + str(root))
    if root == _REPO or _REPO in root.parents:
        _refuse("refusing to seed inside the repository tree: " + str(root))

    root.mkdir(parents=True, exist_ok=True)

    # Import AFTER the env is set so the import-time seam resolves the engine roots to the isolated root.
    from server.sports_cockpit.engine import RUNTIME_ROOT
    if RUNTIME_ROOT.resolve() != root:
        _refuse("engine did not resolve to the isolated root (got " + str(RUNTIME_ROOT) + ")")
    from server.sports_cockpit import gen3_authority as A
    if A.GEN3_ROOT.resolve().parents[1] != root:
        _refuse("gen3_authority did not resolve beneath the isolated root")

    from tests import _hermetic_gen3 as H
    handles = H._seed_objects(migrate=True)

    inventory = {
        "schema": "GOVERNED_SYNTHETIC_SEED_V1",
        "runtimeRoot": str(root),
        "publisher": "server.sports_modeling.gen3_publish.publish_object (via tests._hermetic_gen3._seed_objects)",
        "gen3Registration": str(handles["gen3Root"] / "registration.json"),
        "gen2Registration": str(handles["gen2Root"] / "registration.json"),
        "researchId": handles["researchId"],
        "advancedFeature": handles["advancedFeature"],
        "advancedFamily": handles["advancedFamily"],
        "note": ("synthetic hermetic Gen-3 v2 / Gen-2 v1 published fresh from committed code via the production "
                 "publisher; this is NOT real data and NOT the sealed 2025 corpus; real-data tests skip under it"),
    }
    (root / ".governed-synthetic-seed").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (root / "seed-inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print("SEED-OK " + str(root), flush=True)
    print("  gen3=" + inventory["gen3Registration"], flush=True)
    print("  gen2=" + inventory["gen2Registration"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

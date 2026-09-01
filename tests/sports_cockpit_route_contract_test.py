"""Frontend↔backend route contract for the PA Modeling Cockpit.

Guarantees that every ``/cockpit/...`` path the frontend calls resolves to a route mounted under
``/api`` in the assembled FastAPI app — in BOTH standalone and embedded (Step 6) mode, since both
use the same shared client (`src/lib/api.ts`) and the same `cockpitApi.ts`. This catches wiring
drift that would surface in the browser as a 404 (as observed live when a stale backend process
predates the cockpit router). It does not exercise heavy modeling — only route existence.
"""

from __future__ import annotations

import re
from pathlib import Path

from server.main import app

REPO = Path(__file__).resolve().parents[1]
COCKPIT_SRC = REPO / "src" / "sports" / "cockpit"

# Dynamic frontend paths built with template literals (not captured by the static scan).
DYNAMIC_FRONTEND_PATHS = [
    "/cockpit/profile/feature/{name}",
    "/cockpit/experiments/{experiment_id}",
    "/cockpit/segmentation/summary",  # called as ...summary?population=BATTERS
    "/cockpit/data-preview",  # called as ...data-preview?limit=25&sample=head (template literal)
]


def _mounted_cockpit_routes() -> set[str]:
    return {getattr(r, "path", "") for r in app.routes if getattr(r, "path", "").startswith("/api/cockpit")}


def _route_matcher(mounted: set[str]):
    # convert "/api/cockpit/experiments/{experiment_id}" to a regex
    patterns = [re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", p) + "$") for p in mounted]

    def matches(path: str) -> bool:
        full = "/api" + path
        return any(p.match(full) for p in patterns)

    return matches


def _frontend_static_paths() -> set[str]:
    paths: set[str] = set()
    for f in COCKPIT_SRC.glob("*.ts*"):
        text = f.read_text(encoding="utf-8")
        for m in re.findall(r'"(/cockpit/[a-zA-Z0-9/_.-]+)"', text):
            paths.add(m.split("?")[0])
    return paths


def test_backend_has_cockpit_routes_mounted():
    mounted = _mounted_cockpit_routes()
    # sanity: the router is registered (not a stale/absent app)
    assert "/api/cockpit/objective" in mounted, "cockpit router is not mounted under /api"
    assert len(mounted) >= 20, f"expected the full cockpit route surface, found {len(mounted)}"


def test_every_frontend_cockpit_path_resolves_to_a_mounted_route():
    mounted = _mounted_cockpit_routes()
    matches = _route_matcher(mounted)
    unresolved = []
    for path in sorted(_frontend_static_paths() | set(DYNAMIC_FRONTEND_PATHS)):
        if not matches(path):
            unresolved.append(path)
    assert not unresolved, f"frontend cockpit paths with no matching backend route (would 404): {unresolved}"


def test_core_15_step_cockpit_endpoints_present():
    # the endpoints backing the 15-step cockpit surface, incl. the one that 404'd live (objective)
    mounted = _mounted_cockpit_routes()
    matches = _route_matcher(mounted)
    for path in [
        "/cockpit/objective", "/cockpit/population", "/cockpit/profile", "/cockpit/outliers",
        "/cockpit/missing", "/cockpit/feature-catalog", "/cockpit/feature/kinds",
        "/cockpit/temporal-split", "/cockpit/model-families", "/cockpit/experiment/run",
        "/cockpit/experiments", "/cockpit/autopilot", "/cockpit/eligibility", "/cockpit/simulate",
        "/cockpit/segmentation/kmeans",
    ]:
        assert matches(path), f"cockpit endpoint not mounted: {path}"


def test_frontend_uses_single_shared_api_client():
    # embedded and standalone must not diverge into a second client
    api_client = (COCKPIT_SRC / "cockpitApi.ts").read_text(encoding="utf-8")
    assert 'from "../../lib/api"' in api_client, "cockpit must use the shared src/lib/api client"
    assert "localhost" not in api_client.lower() and "127.0.0.1" not in api_client, "no hard-coded backend host"

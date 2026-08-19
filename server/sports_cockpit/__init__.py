"""Interactive MLB plate-appearance modeling cockpit (Phase 6A).

A scientist-controlled workbench over the governed D3 MLB plate-appearance feature
view. Every metric surfaced here is computed from the real materialized feature view
and evaluated with the frozen ``server.sports_modeling`` evaluation authority — there is
no fabricated result path. The cockpit adds flexible feature selection, fold-local
outlier/missing policies, multiple model families, an automated Autopilot benchmark, and
a bounded whole-game simulation impact test that reuses the Phase 5 research simulator.
"""

from .engine import (
    COCKPIT_SCHEMA_VERSION,
    CockpitError,
    PA_CLASS_ORDER,
)

__all__ = [
    "COCKPIT_SCHEMA_VERSION",
    "CockpitError",
    "PA_CLASS_ORDER",
]

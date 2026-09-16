"""Governed Gold feature-building primitives.

The package is intentionally separate from the quarantined Silver publication and
from model fitting.  Its first primitive is the deterministic, fail-closed
Retrosheet-target to Statcast-Silver plate-appearance bridge.
"""

from .pa_bridge import (
    DEVELOPMENT_SEASONS,
    VALIDATION_SEASONS,
    PaBridgeIntegrityError,
    PaBridgeResult,
    bridge_plate_appearances,
    build_pa_bridge,
)

__all__ = [
    "DEVELOPMENT_SEASONS",
    "VALIDATION_SEASONS",
    "PaBridgeIntegrityError",
    "PaBridgeResult",
    "bridge_plate_appearances",
    "build_pa_bridge",
]

"""NBA Gen2 governed team-box research utilities."""

from .team_box_study import (
    ALIAS_TO_GEN1,
    BOX_METRICS,
    build_pregame_box_features,
    load_governed_population,
)

__all__ = [
    "ALIAS_TO_GEN1",
    "BOX_METRICS",
    "build_pregame_box_features",
    "load_governed_population",
]

from __future__ import annotations

import math
from typing import Any

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


def json_safe(value: Any) -> Any:
    """Recursively convert values that strict JSON cannot serialize."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if np is not None:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            numeric = float(value)
            return numeric if math.isfinite(numeric) else None
        if isinstance(value, np.ndarray):
            return [json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return value

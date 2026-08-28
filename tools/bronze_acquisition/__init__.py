"""Quarantined MLB advanced Bronze acquisition tooling.

STANDALONE. This package has NO import dependency on any ASP modeling, authority, registry, feature, or
research service. The legacy Phase 7B0 planners remain sealed to 2019-2024. A separate, explicitly
date-bounded Statcast extension path is authorized only for the current-data task through 2026-08-27.
Both paths land raw evidence under an external quarantined staging root, record checksummed Bronze
manifests, and are resumable. They perform no joining, feature engineering, target construction, or modeling.
"""

BRONZE_MANIFEST_CONTRACT = "MLB_ADVANCED_BRONZE_SOURCE_MANIFEST_V1"
MIN_YEAR = 2019
MAX_YEAR = 2024  # hard ceiling — 2025 is sealed, 2026 is untouched

# Explicit current-season authorization. This does not relax any legacy year planner or its tests.
CURRENT_STATCAST_MIN_DATE = "2025-03-01"
CURRENT_STATCAST_MAX_DATE = "2026-08-27"

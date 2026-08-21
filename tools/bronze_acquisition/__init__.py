"""Phase 7B0 — quarantined MLB advanced Bronze acquisition tooling.

STANDALONE. This package has NO import dependency on any ASP modeling, authority, registry, feature, or
research service. It downloads raw source evidence (Statcast, Retrosheet, Chadwick, Lahman) for 2019-2024
ONLY into an external quarantined staging root, records immutable Bronze manifests + checksums, and is
resumable. It performs NO integration, joining, feature engineering, target construction, or modeling, and
it refuses every 2025/2026 request.
"""

BRONZE_MANIFEST_CONTRACT = "MLB_ADVANCED_BRONZE_SOURCE_MANIFEST_V1"
MIN_YEAR = 2019
MAX_YEAR = 2024  # hard ceiling — 2025 is sealed, 2026 is untouched

"""Seam-aware runtime probes for the governed test selection (Phase 7D.5A / Workstream E).

Every ``HAS_*`` flag reflects whether the required artifact exists UNDER THE RESOLVED runtime root
(``server.sports_cockpit.engine.RUNTIME_ROOT``), which honors ``ASP_MODEL_STUDIO_RUNTIME_ROOT``. The old probes
hardcoded ``REPO/.runtime/...`` — a path that stays present even when the code-under-test has been relocated to an
isolated throwaway root — so under isolation they falsely reported "present" and the seam-resolved code then errored
on a missing registry. Gating on the RESOLVED root instead makes the selection reproducible:

* empty isolated root  -> HAS_* False -> the dependent tests SKIP cleanly (no spurious errors);
* seeded isolated root -> HAS_GEN3_V2 True (the committed governed seeder published a fresh synthetic authority via
  the production publisher) -> the hermetic / catalog-driven V2-evidence tests RUN and pass on structural and
  bit-for-bit reproducibility assertions;
* real development .runtime -> everything RUNS exactly as before.

``HAS_REAL_*`` additionally require the seed NOT to be synthetic (the seeder drops a ``.governed-synthetic-seed``
marker): tests that assert properties of the REAL published artifacts (real reconciliation numbers, real sealed
objects, real 7A sidecars, the large real Gen-3 v1 feature view) must NOT run against a small synthetic seed, so
they skip under it — while still running against the genuine development ``.runtime``.
"""
from __future__ import annotations

from pathlib import Path

from server.sports_cockpit.engine import RUNTIME_ROOT

_ROOT = Path(RUNTIME_ROOT)
_SM = _ROOT / "sports-modeling"

# The committed synthetic seeder drops this marker so real-data assertions know to stand down.
SYNTHETIC_SEED_MARKER = _ROOT / ".governed-synthetic-seed"
IS_SYNTHETIC_SEED = SYNTHETIC_SEED_MARKER.exists()

GEN3_V2_ROOT = _SM / "mlb-pa-gen3-v2"
GEN2_V1_ROOT = _SM / "mlb-pa-gen2-v1"
GEN3_V1_PARQUET = _SM / "mlb-pa-gen3-v1" / "mlb-pa-gen3-feature-view-v1.parquet"
GEN3_V1_RECON = _SM / "mlb-pa-gen3-v1" / "gen3-reconciliation.json"

# Coarse: a Gen-3 v2 authority is resolvable under the runtime root (a real one, OR the seeder's synthetic one).
HAS_GEN3_V2 = (GEN3_V2_ROOT / "registration.json").is_file()

# Real-data: the genuine published authority / view is present AND we are not running against a synthetic seed.
HAS_REAL_GEN3_V2 = HAS_GEN3_V2 and not IS_SYNTHETIC_SEED
HAS_REAL_GEN3_V1 = GEN3_V1_PARQUET.is_file() and not IS_SYNTHETIC_SEED

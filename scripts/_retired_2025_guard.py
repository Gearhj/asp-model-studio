"""Phase 7D.4 Gate 12 (B8) — hard-retirement guard for ordinary 2025-capable operational scripts.

Ordinary invocation exits BEFORE any path resolution / glob / Parquet open / label construction / model fit /
metric calculation. No self-grantable environment variable re-enables it; a future sealed administrative
capability would be a separate, unavailable service. Use the canonical replacement named in the message.
"""
from __future__ import annotations

import sys

CANONICAL_RESEARCH_ENTRY = "scripts/phase7b_research.py (research-only) + server.sports_cockpit.gen3_authority"


class Retired2025Error(SystemExit):
    """Raised (as a SystemExit) when a retired 2025-capable script is invoked ordinarily."""


def retire_2025(replacement: str = CANONICAL_RESEARCH_ENTRY) -> None:
    """Exit immediately, before any data resolution/open. Never consults an environment capability string."""
    msg = ("RETIRED (Phase 7D.4 Gate 12): this ordinary script could open or score the sealed 2025 season, so "
           "it exits before any data resolution/open. 2025 remains physically sealed and no environment "
           "variable re-enables this path. Canonical replacement: " + replacement)
    sys.stderr.write(msg + "\n")
    raise Retired2025Error(2)

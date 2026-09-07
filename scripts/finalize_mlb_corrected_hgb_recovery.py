"""Finalize only recovery-1; never enqueue, fit, alter the failed study, or open OOT."""
from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.finalize_mlb_corrected_hgb import RECOVERY_STUDY_DIRECTORY, finalize_study


if __name__ == "__main__":
    finalize_study(RECOVERY_STUDY_DIRECTORY)

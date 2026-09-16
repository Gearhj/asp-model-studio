"""Phase 7D.4 Gate 12 (completion) — the residual tracked-script estate is closed.

Beyond the 7 scripts retired earlier, every remaining tracked script that could locate/open/fit/score/evaluate/
surface the sealed 2025 season is hard-retired (exit 2 before any path resolution / glob / open), no
self-granting environment variable re-enables it, the residual ``final2025``-writing training/registration
modules are reachable ONLY through these now-retired scripts, and the approved research entry point is unbroken.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# The residual scripts newly hard-retired in this closure (8 residual run_mlb_* + 3 spent build/seal/migrate
# tools that physically open 2025 + the bare-path governed ablation that bypassed the canonical resolver).
NEWLY_RETIRED = [
    "run_mlb_catcher_readiness", "run_mlb_dynamic_player_state", "run_mlb_game_replay", "run_mlb_pa_baseline",
    "run_mlb_participation_usage", "run_mlb_pitch_sequence_features", "run_mlb_process_interactions",
    "run_mlb_severe_miss_forensics", "phase7_build_gen3", "phase7a_build_gen3", "phase7c_publish_gen2",
    "phase7a_governed_ablation",
]


def _run(script: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, "-m", f"scripts.{script}"], cwd=str(REPO), capture_output=True,
                          text=True, timeout=60, env=env)


@pytest.mark.parametrize("script", NEWLY_RETIRED)
def test_residual_2025_script_exits_before_any_open(script):
    r = _run(script)
    assert r.returncode == 2, f"{script} did not exit(2): rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "RETIRED (Phase 7D.4 Gate 12)" in (r.stderr + r.stdout)


def test_no_environment_variable_re_enables_a_retired_script():
    # A caller-supplied "capability" / dev-mode env cannot re-grant sealed-2025 access: the guard never reads env.
    grant = {"ASP_ARCHIVAL_AUDIT_CAPABILITY": "1", "ASP_MODEL_STUDIO_ALLOW_2025": "true",
             "ATLAS_LOCAL_DEV": "true", "ATLAS_ENABLE_DEV_USER_HEADER": "true", "ASP_ALLOW_SEALED": "1"}
    for script in ("run_mlb_pa_baseline", "phase7a_build_gen3", "phase7a_governed_ablation"):
        r = _run(script, grant)
        assert r.returncode == 2 and "RETIRED (Phase 7D.4 Gate 12)" in (r.stderr + r.stdout)


def test_residual_final2025_writers_are_only_reached_through_retired_scripts():
    # The only tracked scripts that drive the final2025-writing training/registration layer are now retired,
    # so no ordinary script execution can materialize/surface a 2025 metric.
    final2025_driving = {"run_mlb_pa_baseline", "run_mlb_participation_usage", "run_mlb_severe_miss_forensics"}
    assert final2025_driving <= set(NEWLY_RETIRED)


def test_research_entry_point_is_not_retired_and_still_runs():
    src = (REPO / "scripts/phase7b_research.py").read_text(encoding="utf-8")
    assert "retire_2025" not in src           # the research-only entry point is NOT retired
    r = _run("phase7b_research")               # runs (usage/refusal), never the Gate-12 retirement exit
    assert "RETIRED (Phase 7D.4 Gate 12)" not in (r.stderr + r.stdout)

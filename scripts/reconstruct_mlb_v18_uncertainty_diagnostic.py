"""Private, outcome-blind reconstruction of one scalar adapter change.

Never imports the consumer application or connects to any database/provider.
The selected position IDs and prices remain fixed. This is not a replay of
the selection/ranking path and does not authorize any policy change.
"""
from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-v18-operational-followup-20260918-v1")
EVIDENCE = Path(r"C:\Users\james\asp-model-studio\outputs\mlb-v18-wager-evidence-20260918-v1\model_evidence.jsonl")
POSITIONS = Path(r"C:\Users\james\aisp-analysis\wagering-record-20260918\positions.csv")
CONSUMER = Path(r"C:\Users\james\ai-sports-predictor")
PRODUCER = Path(r"C:\Users\james\asp-model-studio-source-mlb-v18-prop-capture")


def binding(path: Path):
    body = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}


def fraction(p, decimal, cap, multiplier):
    # Unrounded normalized counterpart of compute_position_stake. The actual
    # application rounds dollars before multiplying; this fraction cannot
    # reproduce an unknown sizing bankroll or unknown portfolio caps.
    return min(0.25 * max(0.0, (decimal * p - 1.0) / (decimal - 1.0)), cap, 1.0) * multiplier


def main():
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    ROOT = parser.parse_args().output_root.resolve()
    if (ROOT / "uncertainty_reconstruction.csv").exists():
        raise FileExistsError("Retain the original diagnostic; choose a new --output-root")
    ROOT.mkdir(parents=True, exist_ok=True)
    authority = {r["position_id"]: r for r in csv.DictReader(POSITIONS.open(encoding="utf-8-sig", newline="")) if r["controlling_engine"] == "MLB_V18_WHOLE_GAME"}
    evidence = [json.loads(line) for line in EVIDENCE.read_text(encoding="utf-8").splitlines()]
    selected = [r for r in evidence if r["population"] == "SELECTED_V18_POSITION"]
    assert len(selected) == len(authority) == 31
    assert {r["position_id"] for r in selected} == set(authority)
    rows = []
    for e in selected:
        a = authority[e["position_id"]]
        # Only identity and decision-time numerical fields are projected;
        # outcomes, final scores and realized profit are never referenced.
        p = float(e["model_selected_side_probability"])
        se = float(e["mc_home_win_se_recorded"])
        assert abs(se - math.sqrt(p * (1.0 - p) / int(e["simulation_count"]))) < 1e-14
        assert e["full_game_win_se_recorded"] is None
        assert float(a["uncertainty_adjustment_pts"]) == 0
        starter = float(a["starter_penalty_pts"]) / 100
        lineup = float(a["lineup_penalty_pts"]) / 100
        q = float(a["no_vig_p_selected_same_book"])
        decimal = float(a["locked_decimal_odds"])
        cap = float(a["position_cap_fraction"])
        multiplier = float(a["evidence_stake_multiplier"])
        observed_adj = float(a["p_win_adjusted"])
        old_p = max(0.0, p - starter - lineup)
        new_p = max(0.0, p - se - starter - lineup)
        old_edge, new_edge = round(old_p - q, 6), round(new_p - q, 6)
        old_ev, new_ev = round(old_p * decimal - 1, 6), round(new_p * decimal - 1, 6)
        assert abs(round(old_p, 6) - observed_adj) < 1e-12
        # Exported edge points are displayed to 0.001 percentage points;
        # exported market probability is rounded to six decimal places.
        assert abs(old_edge * 100 - float(a["adjusted_edge_pts"])) <= 0.00056
        qualified = new_edge >= 0.02 and new_ev > 0
        # Both tests remain unchanged even at the export's rounding bounds.
        edge_stable = (round(new_p - (q - 0.0000005), 6) >= .02) == (round(new_p - (q + .0000005), 6) >= .02)
        ev_stable = (round(new_p * (decimal - .0000005) - 1, 6) > 0) == (round(new_p * (decimal + .0000005) - 1, 6) > 0)
        assert edge_stable and ev_stable
        old_stake_p, new_stake_p = round(old_p, 6), round(new_p, 6)
        old_fraction = fraction(old_stake_p, decimal, cap, multiplier)
        new_fraction = fraction(new_stake_p, decimal, cap, multiplier) if qualified else 0.0
        old_kelly = .25 * max(0, (decimal * old_stake_p - 1) / (decimal - 1))
        new_kelly = .25 * max(0, (decimal * new_stake_p - 1) / (decimal - 1))
        if not qualified:
            dollar = 0.0
            status = "FIXED_ORIGINAL_SELECTION_FAILS_ECONOMIC_GATES_ZERO_STAKE"
        elif min(old_kelly, new_kelly) > cap + 0.000001:
            dollar = float(a["stake"])
            status = "UNCHANGED_IF_SAME_BANKROLL_AND_PORTFOLIO_CONTEXT_BOTH_POSITION_CAPPED"
        else:
            dollar = None
            status = "NOT_IDENTIFIABLE_WITHOUT_SIZING_BANKROLL_AND_CAP_CONTEXT"
        rows.append({
            "position_id": a["position_id"], "game_id": a["game_id"],
            "forecast_identity": a["forecast_identity"], "forecast_object_sha256": e["forecast_object_sha256"],
            "decision_timestamp_utc": a["decision_timestamp_utc"], "matchup": a["matchup"],
            "selected_side": a["selected_side"], "selected_team": a["selected_team"],
            "scenario": "RECONSTRUCTED_MAP_IMPORTED_MCSE_TO_EXISTING_SCALAR_NO_POLICY_CHANGE_EXECUTED",
            "raw_probability_exact_retained": p, "producer_mc_standard_error": se,
            "uncertainty_scope": "FINITE_SIMULATION_INTEGRATION_ERROR_ONLY_NOT_EPISTEMIC_UNCERTAINTY",
            "recorded_uncertainty_deduction": 0.0, "scenario_uncertainty_deduction": se,
            "starter_penalty": starter, "lineup_penalty": lineup,
            "no_vig_probability_export_six_decimals": q, "offered_decimal_export_six_decimals": decimal,
            "recorded_adjusted_probability": observed_adj, "scenario_adjusted_probability_rounded": new_stake_p,
            "recorded_adjusted_edge_points": float(a["adjusted_edge_pts"]),
            "scenario_adjusted_edge_points": new_edge * 100,
            "recorded_adjusted_ev_per_unit": float(a["ev_per_unit_controlling"]),
            "scenario_adjusted_ev_per_unit": new_ev,
            "scenario_edge_gate_pass": new_edge >= .02, "scenario_ev_gate_pass": new_ev > 0,
            "scenario_fixed_selection_economic_qualification": qualified,
            "qualification_stable_under_export_rounding_bounds": edge_stable and ev_stable,
            "other_recorded_gates": "HELD_FIXED_NOT_REPLAYED",
            "kelly_fraction_assumption": .25, "kelly_fraction_basis": "NAMED_QUARTER_KELLY_POLICY_AND_CURRENT_SOURCE_NOT_EXACT_EXPERIMENT_EXPORT",
            "evidence_multiplier_recorded": multiplier, "position_cap_fraction_recorded": cap,
            "recorded_stake_dollars": float(a["stake"]),
            "old_normalized_preportfolio_stake_fraction_unrounded": old_fraction,
            "scenario_normalized_preportfolio_stake_fraction_unrounded": new_fraction,
            "scenario_stake_dollars_conditional_if_identified": dollar,
            "scenario_stake_identification": status,
            "counterfactual_reselection": "NOT_ASSESSED_OTHER_SIDE_OR_BOOK_COULD_DIFFER",
            "counterfactual_bankroll_path": "NOT_REPLAYED_NO_REALIZED_PROFIT_CLAIM",
            "decision_time_code_deployment_identity": "NOT_RETAINED_IN_AUTHORITY_EXPORT_GIT_HISTORY_IS_NOT_DEPLOYMENT_PROOF",
        })
    rows.sort(key=lambda r: (r["decision_timestamp_utc"], r["position_id"]))
    table_path = ROOT / "uncertainty_reconstruction.csv"
    with table_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (ROOT / "uncertainty_reconstruction.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    sources = [
        CONSUMER / "server/app/shadow_import/mlb_v18_daily.py",
        CONSUMER / "server/app/services/v18_forecast_view.py",
        CONSUMER / "server/app/services/practical_policy.py",
        CONSUMER / "server/app/services/shadow_experiment_service.py",
        CONSUMER / "server/app/bankroll/service.py",
        PRODUCER / "server/sports_current_statcast/mlb_v18_current_publication.py",
        PRODUCER / "docs/MLB_V18_PROSPECTIVE_ACCEPTANCE_PROTOCOL.md",
    ]
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "RECONSTRUCTED_FIXED_SELECTION_ADAPTER_SCENARIO_NOT_AUTHORIZED_REPLACEMENT_POLICY",
        "rows": len(rows), "exact_raw_probability_and_mcse_binding_count": len(rows),
        "zero_recorded_uncertainty_deduction_count": len(rows),
        "scenario_fails_economic_gates_count": sum(not r["scenario_fixed_selection_economic_qualification"] for r in rows),
        "scenario_fails_edge_gate_count": sum(not r["scenario_edge_gate_pass"] for r in rows),
        "scenario_fails_ev_gate_count": sum(not r["scenario_ev_gate_pass"] for r in rows),
        "scenario_still_qualifies_count": sum(r["scenario_fixed_selection_economic_qualification"] for r in rows),
        "dollar_stake_identification_counts": {s: sum(r["scenario_stake_identification"] == s for r in rows) for s in sorted({r["scenario_stake_identification"] for r in rows})},
        "mcse_min_mean_max": [min(r["producer_mc_standard_error"] for r in rows), statistics.mean(r["producer_mc_standard_error"] for r in rows), max(r["producer_mc_standard_error"] for r in rows)],
        "baseline_adjusted_probability_reconciliation": "31_OF_31_EXACT_AT_RECORDED_SIX_DECIMAL_PRECISION",
        "all_economic_classifications_stable_under_export_rounding": True,
        "current_consumer_head_observed": "3e8d530c05e8ec7a5dae6d7adc3ff476e91068a8",
        "relevant_git_line_introductions": {
            "importer_mc_field_mapping": "5f5e2851 (2026-09-08)",
            "adapter_wrong_scalar_key": "30082ec6088c9a13f75eecb505d9b88c6b02ed7c (2026-09-11)",
            "policy_none_to_zero_and_stake_math": "9f1df7c2 (2026-08-31)",
            "account_sizing_basis": "d669bc08 (2026-09-12)",
        },
        "history_qualification": "Current relevant lines predate positions and unchanged blame supports code-path continuity; commits do not certify each running decision deployment.",
        "not_available_in_supplied_export": ["exact decision deployment identity", "exact sizing bankroll", "available capital at decision", "frozen experiment Kelly and exposure cap values", "same-game and daily used exposure", "alternate selection ranking under changed scalar"],
        "input_bindings": [binding(EVIDENCE), binding(POSITIONS)],
        "source_bindings": [binding(p) for p in sources],
        "script": binding(Path(__file__)),
        "output_bindings": [binding(table_path), binding(ROOT / "uncertainty_reconstruction.json")],
        "operations": {"consumer_writes": 0, "provider_calls": 0, "model_fits": 0, "protected_payload_reads": 0, "new_outcome_queries": 0, "production_or_policy_changes": 0},
    }
    (ROOT / "uncertainty_reconstruction_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k.endswith("count") or k in {"rows", "mcse_min_mean_max", "dollar_stake_identification_counts"}}, indent=2))


if __name__ == "__main__":
    main()

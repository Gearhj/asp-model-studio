"""Postscan PA casebook enrichment from gated, unchanged saved predictions.

No fits, inference, simulation, provider calls, chronology repair or AISP access.
Selections are explanatory additions, not independent statistical confirmation.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from scripts import diagnose_mlb_v18_pa_v1 as core

OUT = core.OUT
CONTEXT_FIELDS = [
    "batter_prior_missing", "pitcher_prior_missing", "batter_last100_pa_count",
    "pitcher_last250_bf_count", "matchup_platoon_advantage", "pitcher_gs_per_g",
    "pitcher_last250_fastball_usage", "context_inning", "context_outs_before",
    "context_base_mask_before", "batting_short_rest_indicator", "fielding_short_rest_indicator",
    "batting_travel_distance_miles", "pitcher_last250_velocity_missing",
    "batter_last100_whiff_missing", "batting_pregame_temperature_missing",
    "fielding_recent_bullpen_workload_missing",
]


def reference(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def save(path, obj):
    Path(path).write_text(json.dumps(core.native(obj), indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    original_paths = [OUT / n for n in (
        "pa-game-casebook.csv", "severe-pa-cases.csv", "game-pa-ledger.csv", "summary.json",
        "regimes.csv", "class-calibration.csv", "probability-bands.csv", "validation.json")]
    original_refs = [reference(p) for p in original_paths]
    original_games = pd.read_csv(OUT / "pa-game-casebook.csv")
    original_pa = pd.read_csv(OUT / "severe-pa-cases.csv")
    game_ledger = pd.read_csv(OUT / "game-pa-ledger.csv")
    lineage_path = OUT.parent / "lineage/pa-lineage.json"
    lineage = json.loads(lineage_path.read_bytes())
    folds = {int(f["foldNumber"]): {k: f[k] for k in (
        "foldNumber", "trainStart", "trainEnd", "validationStart", "validationEnd",
        "eligibleFittedTrainingRows", "savedV18OofRows", "estimator", "preprocessor",
        "priorFittedChecksum", "semanticFittedChecksum", "dimensions", "currentOperationalEstimator")}
        for f in lineage["folds"]}
    declared = {
        "status": "POSTSCAN_READABILITY_AND_CONTROL_REFINEMENT_NOT_INDEPENDENT_TEST",
        "game_rule": "Preserve original selections. Supplement top3 mean saved PA loss games with >=40 observed archive PAs; this threshold is not a completeness certificate.",
        "game_controls": "Reuse original same-fold ordinary/low-loss cases. If absent for a supplementary fold, use existing game ledger >=40-PA median/lower-quartile loss band +/-0.025, then closest PA-count/entropy, ties canonicalGameId.",
        "individual_rule": "Preserve original8 severe PAs; assign distinct same-fold/same-realized-class controls within q20-q30 log-loss band, then closest fixed saved context/exposure/entropy distance, ties canonicalPaId. Outcome-informed explanatory controls, not pregame eligibility or independent samples.",
        "distance": "Sum categorical mismatch penalties (prior flags, platoon, outs, base mask, rest) plus absolute last100 exposure/100, last250 exposure/250, inning/9, prior starter share, historical fastball usage and entropy/log(8) differences. Missing both=0; missing one=1.",
        "no_changes_to_primary_results": True,
    }
    save(OUT / "case-enrichment-selection.json", declared)

    # Exactly one reuse of the key-gated loader; no fitted object is loaded.
    df, p, q, y, observed, ll, llq, br, brq, protocol, accounting = core.load_data()
    entropy = -(p * np.log(np.clip(p, np.finfo(float).eps, 1))).sum(axis=1)
    positions = {str(key): int(i) for i, key in enumerate(df.canonicalPaId)}
    selected_games = original_games.canonicalGameId.drop_duplicates().tolist()
    large = game_ledger[game_ledger.pa_count >= 40].sort_values(
        ["pa_log_loss", "canonicalGameId"], ascending=[False, True]).head(3)
    expected = {("2025-03-29", "MIL", "NYY"), ("2025-05-17", "COL", "AZ"), ("2026-06-24", "CHC", "NYM")}
    assert {(r.game_date, r.awayTeamAbbrev, r.homeTeamAbbrev) for r in large.itertuples()} == expected
    additions = []
    for r in large.itertuples():
        if r.canonicalGameId not in selected_games:
            selected_games.append(r.canonicalGameId)
        additions.append({"game_id": r.canonicalGameId, "selection": "POSTSCAN_TOP3_PA_LOSS_AMONG_ARCHIVE_GAMES_WITH_AT_LEAST_40_PAS"})
        controls = original_games[(original_games.foldNumber == r.foldNumber) & original_games.selection.str.startswith("matched_")]
        if controls.empty:
            pool = game_ledger[(game_ledger.foldNumber == r.foldNumber) & (game_ledger.pa_count >= 40)
                               & ~game_ledger.canonicalGameId.isin(selected_games)].copy()
            for label, quantile in (("POSTSCAN_SAME_FOLD_ORDINARY", .5), ("POSTSCAN_SAME_FOLD_LOW_ERROR", .25)):
                goal = pool.pa_log_loss.quantile(quantile)
                band = pool[(pool.pa_log_loss - goal).abs() <= .025].copy()
                assert not band.empty
                band["distance"] = (band.pa_count-r.pa_count).abs()/r.pa_count + (band.predicted_entropy-r.predicted_entropy).abs()
                pick = band.sort_values(["distance", "canonicalGameId"]).iloc[0]
                selected_games.append(pick.canonicalGameId)
                additions.append({"game_id": pick.canonicalGameId, "matched_to": r.canonicalGameId,
                                  "selection": label, "distance": float(pick.distance), "loss_quantile_target": quantile})
                pool = pool[pool.canonicalGameId != pick.canonicalGameId]

    def context_summary(rows):
        result = {"available_rows": int(rows.contextAvailable.sum()), "archive_rows": len(rows), "fields": {}}
        for name in CONTEXT_FIELDS:
            values = pd.to_numeric(rows[name], errors="coerce")
            result["fields"][name] = {"observed_rows": int(values.notna().sum()), "missing_rows": int(values.isna().sum()),
                                      "mean": values.mean(), "min": values.min(), "max": values.max()}
        conditions = {
            "either_prior_missing": (rows.batter_prior_missing.eq(1) | rows.pitcher_prior_missing.eq(1)),
            "batter_rolling_below100": rows.batter_last100_pa_count.lt(100),
            "pitcher_rolling_below250": rows.pitcher_last250_bf_count.lt(250),
            "platoon_advantage": rows.matchup_platoon_advantage.eq(1),
            "prior_starter_share_at_least_half": rows.pitcher_gs_per_g.ge(.5),
            "fastball_usage_at_least_60pct": rows.pitcher_last250_fastball_usage.ge(.6),
            "inning1_3": rows.context_inning.between(1, 3), "inning4_6": rows.context_inning.between(4, 6),
            "inning7_plus": rows.context_inning.ge(7), "bases_occupied": rows.context_base_mask_before.gt(0),
            "batting_short_rest": rows.batting_short_rest_indicator.eq(1),
            "fielding_short_rest": rows.fielding_short_rest_indicator.eq(1),
        }
        # Missing source fields never silently become a false condition.
        sources = {"either_prior_missing": ["batter_prior_missing", "pitcher_prior_missing"],
                   "batter_rolling_below100": ["batter_last100_pa_count"], "pitcher_rolling_below250": ["pitcher_last250_bf_count"],
                   "platoon_advantage": ["matchup_platoon_advantage"], "prior_starter_share_at_least_half": ["pitcher_gs_per_g"],
                   "fastball_usage_at_least_60pct": ["pitcher_last250_fastball_usage"], "bases_occupied": ["context_base_mask_before"],
                   "batting_short_rest": ["batting_short_rest_indicator"], "fielding_short_rest": ["fielding_short_rest_indicator"]}
        result["shares"] = {}
        for name, condition in conditions.items():
            valid = rows.contextAvailable & rows[sources.get(name, ["context_inning"])].notna().all(axis=1)
            result["shares"][name] = {"numerator": int((condition & valid).sum()), "denominator": int(valid.sum()),
                                     "share": float(condition[valid].mean()) if valid.any() else None}
        return result

    games = []
    for game in selected_games:
        take = df.canonicalGameId.eq(game).to_numpy(); ids = np.flatnonzero(take); rows = df.loc[take]
        assert len(ids) > 0 and rows.foldNumber.nunique() == 1
        first = rows.iloc[0]; fold = int(first.foldNumber)
        old = original_games[original_games.canonicalGameId == game]
        game_additions = [r for r in additions if r["game_id"] == game]
        original = old.to_dict("records")
        classes = [{"class": name, "observed_count": int(observed[take, j].sum()), "observed_frequency": float(observed[take, j].mean()),
                    "v18_expected_count_over_recorded_pas": float(p[take,j].sum()), "v18_mean_probability": float(p[take,j].mean()),
                    "v18_predicted_minus_observed_frequency": float(p[take,j].mean()-observed[take,j].mean()),
                    "v14_expected_count_over_recorded_pas": float(q[take,j].sum()), "v14_mean_probability": float(q[take,j].mean()),
                    "v18_mean_loss_given_this_observed_class": float(ll[ids[y[ids] == j]].mean()) if (y[ids] == j).any() else None,
                    "v18_share_of_game_log_loss_sum": float(ll[ids[y[ids] == j]].sum()/ll[ids].sum())}
                   for j, name in enumerate(core.CLASSES)]
        games.append({"canonicalGameId": game, "game_date": first.game_date, "game_id_alias": first.game_id,
                      "away_team": first.awayTeamAbbrev, "home_team": first.homeTeamAbbrev, "fold": fold,
                      "forecast_identity": folds[fold], "reference_identity": {"saved_v14_hgb_oof_sha256": core.V14_SHA, "fold": fold, "exact_pa_game_fold_target_match": True},
                      "original_selections_preserved": original, "postscan_additions": game_additions,
                      "pa_count": len(ids), "distinct_batters": int(rows.batterCanonicalPlayerId.nunique()), "distinct_pitchers": int(rows.pitcherCanonicalPlayerId.nunique()),
                      "v18_mean_pa_log_loss": float(ll[ids].mean()), "v14_mean_pa_log_loss": float(llq[ids].mean()),
                      "v18_minus_v14_mean_pa_log_loss": float((ll[ids]-llq[ids]).mean()),
                      "v18_summed_brier": float(br[ids].mean()), "v14_summed_brier": float(brq[ids].mean()),
                      "mean_predicted_entropy": float(entropy[ids].mean()), "class_details": classes,
                      "saved_context": context_summary(rows), "timing_status": core.TIMING_STATUS,
                      "coverage_status": "ONE_PA_ARCHIVE_FRAGMENT_NOT_FULL_GAME_MISS" if len(ids)==1 else "OBSERVED_ARCHIVE_PA_COHORT_COMPLETENESS_NOT_CERTIFIED_BY_COUNT",
                      "whole_game_prediction": False, "predicted_runs": None, "final_runs": None,
                      "causal_status": "EXPLANATORY_HYPOTHESES_ONLY_OUTCOME_SELECTED_CASE_NOT_INDEPENDENT_TEST"})

    severe = original_pa[original_pa.selection.eq("top8_PA_log_loss")].copy()
    severe_indices = [positions[k] for k in severe.canonicalPaId]
    assert len(severe_indices) == 8 and set(y[severe_indices]) == {5} and set(df.foldNumber.iloc[severe_indices]) == {1}
    categorical = ["batter_prior_missing", "pitcher_prior_missing", "matchup_platoon_advantage",
                   "context_outs_before", "context_base_mask_before", "batting_short_rest_indicator"]
    continuous = {"batter_last100_pa_count": 100., "pitcher_last250_bf_count": 250., "context_inning": 9.,
                  "pitcher_gs_per_g": 1., "pitcher_last250_fastball_usage": 1.}
    used = set(severe_indices); matches = []

    def pa_detail(i):
        r = df.iloc[i]
        return {"canonicalPaId": r.canonicalPaId, "canonicalGameId": r.canonicalGameId, "game_date": r.game_date,
                "batter_id": r.batterCanonicalPlayerId, "pitcher_id": r.pitcherCanonicalPlayerId,
                "away_team": r.awayTeamAbbrev, "home_team": r.homeTeamAbbrev, "fold": int(r.foldNumber),
                "observed_class": core.CLASSES[y[i]], "v18_probability_of_observed_class": p[i,y[i]], "v14_probability_of_observed_class": q[i,y[i]],
                "v18_pa_log_loss": ll[i], "v14_pa_log_loss": llq[i], "predicted_entropy": entropy[i],
                "v18_probabilities": dict(zip(core.CLASSES,p[i])), "v14_probabilities": dict(zip(core.CLASSES,q[i])),
                "saved_context": r[CONTEXT_FIELDS].to_dict(), "timing_status": core.TIMING_STATUS}

    for target in severe_indices:
        base = np.flatnonzero((df.foldNumber.to_numpy() == df.foldNumber.iloc[target]) & (y == y[target]) & ~np.isin(np.arange(len(df)), severe_indices))
        lo, hi = np.quantile(ll[base], [.2, .3])
        pool = np.array([i for i in base if lo <= ll[i] <= hi and i not in used], dtype=int)
        assert len(pool)
        distances = np.abs(entropy[pool]-entropy[target])/np.log(8)
        for field in categorical + list(continuous):
            values = pd.to_numeric(df[field], errors="coerce").to_numpy(float)
            a, b = values[pool], values[target]
            both = np.isnan(a) & np.isnan(b); either = np.isnan(a) | np.isnan(b)
            part = (a != b).astype(float) if field in categorical else np.abs(a-b)/continuous[field]
            distances += np.where(both, 0., np.where(either, 1., part))
        order = np.lexsort((df.canonicalPaId.iloc[pool].to_numpy(), distances))
        best = int(pool[order[0]]); used.add(best)
        matches.append({"selection": "POSTSCAN_DISTINCT_SAME_FOLD_ACTUAL_CLASS_Q20_Q30_CONTEXT_MATCH",
                        "severe": pa_detail(target), "control": pa_detail(best), "distance": float(distances[order[0]]),
                        "eligible_loss_band": {"q20": float(lo), "q30": float(hi), "remaining_candidate_pas": len(pool)},
                        "matching_variables_observable": "Saved pre-PA context/exposure/probability; actual-class and loss-band restriction is outcome-informed explanatory selection only",
                        "forecast_identity": folds[int(df.foldNumber.iloc[target])]})
    assert len({r["control"]["canonicalPaId"] for r in matches}) == 8
    assert all(sum(c["observed_count"] for c in g["class_details"]) == g["pa_count"] for g in games)
    for game in games:
        for key in ("v18_expected_count_over_recorded_pas", "v14_expected_count_over_recorded_pas"):
            assert abs(sum(c[key] for c in game["class_details"])-game["pa_count"]) < 1e-10
        saved = game_ledger[game_ledger.canonicalGameId.eq(game["canonicalGameId"])].iloc[0]
        assert abs(game["v18_mean_pa_log_loss"]-saved.pa_log_loss) < 1e-12
    details = {"schemaVersion": "V18_PA_CASE_ENRICHMENT_V1", "selection_status": declared,
               "class_order": core.CLASSES, "games": games, "individual_severe_refined_control_pairs": matches,
               "original_individual_control_accounting": {"rows": int(original_pa.selection.ne("top8_PA_log_loss").sum()),
                   "distinct_pas": int(original_pa.loc[original_pa.selection.ne("top8_PA_log_loss"), "canonicalPaId"].nunique()),
                   "preserved_original_artifact": str((OUT/"severe-pa-cases.csv").resolve())},
               "limits": ["Expected class counts sum probabilities over observed PA membership, not a pregame whole-game forecast.",
                          "A >=40-PA threshold improves readability but cannot certify complete game coverage.",
                          "All cases were selected after observing loss; no causal or recurring-effect claim follows.",
                          "No source needed for park, weather, actual TTO, starter role or final runs was reconstructed."]}
    save(OUT / "case-details.json", details)

    lines = ["# PA casebook enrichment", "", "These are postscan explanatory additions. Original selections and primary metrics remain unchanged. Predicted class counts sum saved probabilities over the observed archive PAs; they are not pregame whole-game forecasts. No final runs were read or inferred.", "",
             "The two August 7, 2024 AZ–CLE doubleheader records contain only one PA each. Their extreme game-average/BIP_OUT errors are coverage artifacts, not full-game misses. They remain in the original casebook with that explicit qualification. The >=40-PA supplement below improves readability without certifying game completeness.", "",
             "|Date|Matchup|Fold|Archive PAs|V18 PA loss|V14 PA loss|Difference|", "|---|---|---:|---:|---:|---:|---:|"]
    for r in large.itertuples():
        g = next(x for x in games if x["canonicalGameId"] == r.canonicalGameId)
        lines.append(f"|{g['game_date']}|{g['away_team']}–{g['home_team']}|{g['fold']}|{g['pa_count']}|{g['v18_mean_pa_log_loss']:.6f}|{g['v14_mean_pa_log_loss']:.6f}|{g['v18_minus_v14_mean_pa_log_loss']:+.6f}|")
    for r in large.itertuples():
        g = next(x for x in games if x["canonicalGameId"] == r.canonicalGameId)
        deviations = sorted(g["class_details"], key=lambda c: abs(c["v18_predicted_minus_observed_frequency"]), reverse=True)[:3]
        detail = "; ".join(f"{c['class']}: {c['v18_expected_count_over_recorded_pas']:.2f} expected versus {c['observed_count']} observed ({100*c['v18_predicted_minus_observed_frequency']:+.2f} percentage points)" for c in deviations)
        shares = g["saved_context"]["shares"]
        lines += ["", f"{g['away_team']}–{g['home_team']} ({g['game_date']}): {detail}. Prior-missing exposure covers {shares['either_prior_missing']['numerator']}/{shares['either_prior_missing']['denominator']} PAs; low pitcher rolling exposure {shares['pitcher_rolling_below250']['numerator']}/{shares['pitcher_rolling_below250']['denominator']}. V14 also has high loss, so the realized outcome mix appears difficult for both saved estimators. These facts do not isolate whether inputs, priors, the PA estimator or other mechanisms caused the miss."]
    lines += ["", "Existing ordinary/low-error controls in folds 2 and 3 are retained with the original matching relationships. Fold 5 had no original controls; two same-fold examples selected from the existing game ledger are explicitly marked as postscan additions. All per-class probabilities, observed counts, V14 comparisons, context shares and exact fold estimator/preprocessor identities are in case-details.json.", "",
              "All eight individually most severe PAs are fold-1 triples. This is selection on a rare realized class, not eight independent demonstrations of a failure. The original eight lower-loss control rows repeated one PA; those rows are preserved. The refinement adds eight distinct same-fold, same-realized-class controls within the q20–q30 loss band, selected by fixed context/exposure/entropy distance.", "",
              "|Severe PA date|Severe P(triple)|Control date|Control P(triple)|Severe loss|Control loss|", "|---|---:|---|---:|---:|---:|"]
    for match in matches:
        a, b = match["severe"], match["control"]
        lines.append(f"|{a['game_date']}|{a['v18_probability_of_observed_class']:.6f}|{b['game_date']}|{b['v18_probability_of_observed_class']:.6f}|{a['v18_pa_log_loss']:.3f}|{b['v18_pa_log_loss']:.3f}|")
    lines += ["", "The distinct controls remain selected using actual class and observed loss; they are readability comparisons, not a new test or pregame eligibility rule. Historical training and feature timing remain uncertified, and fold-1 examples do not diagnose today's exact fold-5 estimator. No case-level causal explanation is established."]
    (OUT / "case-notes.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    current_refs = [reference(p) for p in original_paths]
    assert original_refs == current_refs, "Primary outputs must remain byte-identical, including loader validation"
    outputs = [OUT/n for n in ("case-details.json", "case-notes.md", "case-enrichment-selection.json")]
    save(OUT/"case-enrichment-input-manifest.json", {"script": reference(__file__),
         "command": r".\.venv\Scripts\python.exe scripts/enrich_mlb_v18_pa_cases_v1.py", "original_inputs": original_refs,
         "lineage": reference(lineage_path), "loader": reference(Path(core.__file__)), "loader_references": core.REFS,
         "physical_reads": core.READS, "outputs": [reference(p) for p in outputs], "primary_outputs_byte_identical": True,
         "validation": {"game_class_count_sums": len(games), "game_loss_reconciliations": len(games), "distinct_refined_controls": 8},
         "activities": {"gated_loader_calls": 1, "fits": 0, "inference": 0, "simulations": 0, "provider_calls": 0, "oot_outcome_reads": 0, "aisp_access": 0}})
    print(json.dumps({"games": len(games), "large_case_ids": large.canonicalGameId.tolist(), "distinct_controls": 8, "primary_outputs_byte_identical": True}))


if __name__ == "__main__":
    main()

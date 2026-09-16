"""Bounded frozen fold-5 doubles localization; no fit, inference or acquisition.

First run writes a gated Development-only row cache. Later report passes reuse
that cache. All tables are descriptive archived actual-state PA comparisons.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from scripts import followup_mlb_v18_doubles_v1 as prior
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask

OUT = ROOT / "outputs/mlb-v18-doubles-inning-duration-v1"
PARENT = prior.PARENT
BANDS = [0, .01, .025, .05, .10, .20, .30, .40, .50, .60, .80, 1.0000001]
GROUPS = ["1–3", "4–6", "7–9", "10+", "UNKNOWN"]
PRIMARY = "DOUBLE [0.05,0.1)"
LOWER = "DOUBLE [0.025,0.05)"


def ref(path):
    p = Path(path).resolve(); raw = p.read_bytes()
    return {"path": str(p), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def json_write(path, value):
    Path(path).write_text(json.dumps(prior.native(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def load_rows():
    cache = OUT / "analysis-rows.parquet"
    receipt_path = OUT / "row-cache-receipt.json"
    if cache.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert ref(cache) == receipt["cache"]
        return pd.read_parquet(cache), receipt
    old = json.loads((prior.OUT / "manifest.json").read_text(encoding="utf-8"))
    parent = ref(PARENT / "artifact-manifest.json")
    assert parent["sha256"] == old["parentManifestSha256"]
    assert old["fold5"]["estimator"]["sha256"] == "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b"
    ledger = pd.read_csv(PARENT / "pa/game-pa-ledger.csv", usecols=["canonicalGameId", "game_date", "foldNumber"])
    keys = prior.read_columns(prior.OOF, ["canonicalPaId", "canonicalGameId", "foldNumber"], "IDENTITY_BEFORE_OUTCOMES")
    assert keys.canonicalPaId.is_unique and all(final_oot_eligible_key_mask(keys.canonicalGameId))
    keys = keys.merge(ledger, on=["canonicalGameId", "foldNumber"], how="left", validate="many_to_one")
    assert keys.game_date.notna().all() and keys.game_date.between("2023-03-30", "2026-08-13").all()
    selected = keys.loc[keys.foldNumber.eq(5)].copy()
    assert len(selected) == 101264
    df = prior.read_columns(prior.OOF, ["canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex", *prior.PCOLS], "GATED_DEVELOPMENT_CHUNKS_FOLD5_ONLY_CALCULATIONS", fold5=True)
    df = df.merge(selected[["canonicalPaId", "game_date"]], on="canonicalPaId", validate="one_to_one")
    raw_path = prior.CACHE / "raw-development.parquet"
    rk = prior.read_columns(raw_path, ["canonicalPaId", "canonicalGameId", "game_date", "foldNumber"], "RAW_CONTEXT_IDENTITY_GATE", fold5=True)
    assert rk.canonicalPaId.is_unique and all(final_oot_eligible_key_mask(rk.canonicalGameId))
    assert rk.game_date.between("2026-05-02", "2026-08-13").all()
    columns = ["canonicalPaId", "foldNumber", "outcome", "observedClassIndex", "pitcherCanonicalPlayerId", "batterCanonicalPlayerId", "context_inning", "context_top_bottom", "context_outs_before", "context_base_mask_before", "batter_prior_missing", "pitcher_prior_missing"]
    raw = prior.read_columns(raw_path, columns, "GATED_RAW_STATE_LABEL_AND_IDENTITY", fold5=True)
    assert set(raw.canonicalPaId) == set(rk.canonicalPaId)
    raw = raw.rename(columns={"observedClassIndex": "raw_class_index"}).drop(columns="foldNumber")
    raw["original_context_joined"] = True
    df = df.merge(raw, on="canonicalPaId", how="left", validate="one_to_one")
    df["original_context_joined"] = df.original_context_joined.eq(True)
    p = df[prior.PCOLS].to_numpy(dtype=float)
    y = pd.to_numeric(df.observedClassIndex, errors="coerce").to_numpy(dtype=float)
    valid_y = np.isfinite(y) & (y == np.floor(y)) & (y >= 0) & (y < 8)
    checks = {"invalid_observed_class_rows": int((~valid_y).sum()), "nonfinite_probability_rows": int((~np.isfinite(p).all(axis=1)).sum()), "negative_probability_rows": int((p < 0).any(axis=1).sum()), "zero_sum_probability_rows": int((p.sum(axis=1) <= 0).sum()), "max_probability_sum_error": float(np.max(np.abs(p.sum(axis=1)-1))), "uniform_probability_rows": int(np.all(np.isclose(p, .125, atol=1e-14, rtol=0), axis=1).sum()), "one_hot_double_rows": int(((p[:, 4] == 1) & (np.delete(p, 4, axis=1) == 0).all(axis=1)).sum())}
    assert valid_y.all() and np.isfinite(p).all() and (p >= 0).all() and checks["max_probability_sum_error"] < 1e-12
    joined = df.original_context_joined
    label_indices = df.loc[joined, "outcome"].map({name: i for i, name in enumerate(prior.CLASSES)})
    checks["raw_unknown_outcome_rows"] = int(label_indices.isna().sum())
    checks["raw_outcome_to_index_mismatches"] = int((label_indices.to_numpy() != df.loc[joined, "raw_class_index"].to_numpy()).sum())
    checks["raw_saved_oof_class_mismatches"] = int((df.loc[joined, "raw_class_index"] != df.loc[joined, "observedClassIndex"]).sum())
    checks["raw_label_rows_checked"] = int(joined.sum())
    df["p_double"] = p[:, 4]
    df["observed_double"] = (y == 4).astype(int)
    df["residual_double"] = df.p_double - df.observed_double
    high = df.p_double.ge(.05) & df.p_double.lt(.10)
    low = df.p_double.ge(.025) & df.p_double.lt(.05)
    assert int(high.sum()) == 14375 and int(df.loc[high, "observed_double"].sum()) == 652
    assert int(low.sum()) == 86652 and int(df.loc[low, "observed_double"].sum()) == 3477
    assert int((high & ~joined).sum()) == 1029
    assert abs(df.loc[high, "p_double"].sum() - old["outcome_balance"]["DOUBLE 5–10%"][4]["predicted_count"]) < 1e-8
    assert abs(df.loc[low, "p_double"].sum() - old["outcome_balance"]["DOUBLE 2.5–5%"][4]["predicted_count"]) < 1e-8
    df.to_parquet(cache, index=False)
    receipt = {"schemaVersion": "MLB_V18_FOLD5_GATED_ROW_CACHE_V1", "createdAtUtc": datetime.now(timezone.utc).isoformat(), "cache": ref(cache), "parentManifest": parent, "doublesFollowupManifest": ref(prior.OUT / "manifest.json"), "fold5": old["fold5"], "rows": len(df), "checks": checks, "reads": prior.READS, "finalOotRead": False, "quarantineAppliedBeforeOutcomeAccess": True, "chronologyCertified": False, "fullOtherFoldAnalysis": False}
    json_write(receipt_path, receipt)
    return df, receipt


def contexts(df, lineage_path=None):
    df = df.copy()
    df["inning"] = pd.to_numeric(df.context_inning, errors="coerce")
    df["actual_role"] = "UNKNOWN"
    df["prior_bf"] = np.nan
    if lineage_path:
        extra = pd.read_parquet(lineage_path)
        assert extra.canonicalPaId.is_unique
        df = df.merge(extra, on="canonicalPaId", how="left", suffixes=("", "_lineage"), validate="one_to_one")
        assert df.canonicalGameId_lineage.notna().all()
        assert df.canonicalGameId.eq(df.canonicalGameId_lineage).all()
        for field in ["inning", "actual_role", "prior_bf"]:
            new = field + "_lineage"
            if new in df:
                if field == "inning":
                    both = df[field].notna() & df[new].notna()
                    assert np.all(df.loc[both, field].to_numpy() == df.loc[both, new].to_numpy())
                df[field] = df[new].where(df[new].notna(), df[field])
        df["actual_role"] = df.actual_role.fillna("UNKNOWN")
        assert df.actual_role.isin(["STARTER", "RELIEVER", "UNKNOWN"]).all()
        for original, recovered in [("context_outs_before", "outs_before"), ("context_base_mask_before", "base_mask_before"), ("pitcherCanonicalPlayerId", "pitcherCanonicalPlayerId_lineage")]:
            if recovered in df:
                both = df[original].notna() & df[recovered].notna()
                assert df.loc[both, original].eq(df.loc[both, recovered]).all(), original
                df[original] = df[recovered].where(df[recovered].notna(), df[original])
    inn = pd.to_numeric(df.inning, errors="coerce")
    assert ((inn.dropna() >= 1) & (inn.dropna() == np.floor(inn.dropna()))).all()
    df["inning_group"] = np.select([inn.between(1, 3), inn.between(4, 6), inn.between(7, 9), inn.ge(10)], GROUPS[:4], default="UNKNOWN")
    return df


def summarize(df, focus_groups=()):
    populations = {"ALL_FOLD5": np.ones(len(df), dtype=bool)}
    for lo, hi in zip(BANDS[:-1], BANDS[1:]):
        label = f"DOUBLE [{lo:g},{hi:g})"
        mask = df.p_double.ge(lo) & df.p_double.lt(hi)
        if mask.any(): populations[label] = mask.to_numpy()
    rows = []
    def add(section, population, mask, **labels):
        f = df.loc[mask]; n = len(f); expected = float(f.p_double.sum()); observed = int(f.observed_double.sum())
        denominator = float(df.loc[populations[population], "residual_double"].sum())
        row = {"section": section, "population": population, **labels, "PAs": n, "games": int(f.canonicalGameId.nunique()), "dates": int(f.game_date.nunique()), "expected_doubles": expected, "observed_doubles": observed, "predicted_per100": 100*expected/n if n else None, "observed_per100": 100*observed/n if n else None, "bias_pp": 100*(expected-observed)/n if n else None, "signed_excess": expected-observed, "population_signed_excess_denominator": denominator, "share_population_signed_excess_pct": 100*(expected-observed)/denominator if denominator else None, "original_context_unjoined_PAs": int((~f.original_context_joined).sum()), "inning_unknown_PAs": int(f.inning.isna().sum()), "role_unknown_PAs": int(f.actual_role.eq("UNKNOWN").sum()), "support": "SUPPORTED_DESCRIPTIVE" if n >= 1000 and f.canonicalGameId.nunique() >= 100 else "SPARSE_DESCRIPTIVE"}
        rows.append(row)
    for population, selected in populations.items():
        add("population", population, selected)
        for group in GROUPS:
            add("inning_group", population, selected & df.inning_group.eq(group).to_numpy(), inning_group=group)
        for role in ["STARTER", "RELIEVER", "UNKNOWN"]:
            add("role", population, selected & df.actual_role.eq(role).to_numpy(), role=role)
            for group in GROUPS:
                add("inning_role", population, selected & df.actual_role.eq(role).to_numpy() & df.inning_group.eq(group).to_numpy(), inning_group=group, role=role)
        for available in [True, False]:
            add("original_context_coverage", population, selected & df.original_context_joined.eq(available).to_numpy(), context_status="JOINED" if available else "UNJOINED_ORIGINAL")
        if population in ["ALL_FOLD5", LOWER, PRIMARY]:
            for inning in sorted(df.inning.dropna().unique()):
                add("individual_inning", population, selected & df.inning.eq(inning).to_numpy(), inning=str(int(inning)))
    assert len(focus_groups) <= 2
    for group in focus_groups:
        assert group in GROUPS[:4]
        parent = populations[PRIMARY] & df.inning_group.eq(group).to_numpy()
        for outs in [0, 1, 2, "UNKNOWN"]:
            m = df.context_outs_before.isna() if outs == "UNKNOWN" else df.context_outs_before.eq(outs)
            add("focused_outs", PRIMARY, parent & m.to_numpy(), inning_group=group, outs=str(outs))
        for bases in [0, 1, 2, 3, 4, 5, 6, 7, "UNKNOWN"]:
            m = df.context_base_mask_before.isna() if bases == "UNKNOWN" else df.context_base_mask_before.eq(bases)
            add("focused_bases", PRIMARY, parent & m.to_numpy(), inning_group=group, base_mask=str(bases))
        bf = pd.to_numeric(df.prior_bf, errors="coerce")
        for label, m in [("0–8", bf.between(0, 8)), ("9–17", bf.between(9, 17)), ("18–26", bf.between(18, 26)), ("27+", bf.ge(27)), ("UNKNOWN", bf.isna())]:
            add("focused_prior_bf", PRIMARY, parent & m.fillna(False).to_numpy(dtype=bool), inning_group=group, prior_bf_bin=label)
    table = pd.DataFrame(rows)
    # One reconciliation across mutually exclusive partitions; overlap is never summed.
    for population in populations:
        total = table[(table.section == "population") & (table.population == population)].iloc[0]
        for section in ["inning_group", "role", "inning_role", "original_context_coverage"]:
            part = table[(table.section == section) & (table.population == population)]
            assert part.PAs.sum() == total.PAs and part.observed_doubles.sum() == total.observed_doubles
            assert abs(part.expected_doubles.sum() - total.expected_doubles) < 1e-8
    for group in focus_groups:
        total = table[(table.section == "inning_group") & (table.population == PRIMARY) & (table.inning_group == group)].iloc[0]
        for section in ["focused_outs", "focused_bases", "focused_prior_bf"]:
            part = table[(table.section == section) & (table.inning_group == group)]
            assert part.PAs.sum() == total.PAs and part.observed_doubles.sum() == total.observed_doubles
            assert abs(part.expected_doubles.sum() - total.expected_doubles) < 1e-8
    return table


def plot(table):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.6), constrained_layout=True)
    for ax, population, title in zip(axes, ["ALL_FOLD5", LOWER, PRIMARY], ["All eligible fold-5 PAs", "Double probability 2.5–5%", "Double probability 5–10%"]):
        f = table[(table.section == "inning_group") & (table.population == population)].set_index("inning_group").reindex(GROUPS)
        x = np.arange(len(GROUPS))
        ax.plot(x, f.predicted_per100, "o-", color="#2563a0", label="Expected")
        ax.plot(x, f.observed_per100, "s-", color="#b34a31", label="Observed")
        ax.set_xticks(x, [f"{g}\nn={int(n):,}" + ("*" if 0 < n < 1000 else "") for g, n in zip(GROUPS, f.PAs)], fontsize=8)
        ax.set_title(title, fontsize=11)
        ax.set_ylim(bottom=0); ax.grid(axis="y", alpha=.2)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlabel("Pre-PA inning group · PA exposure")
    axes[0].set_ylabel("Doubles per 100 plate appearances")
    axes[0].legend(frameon=False)
    fig.suptitle("Frozen V18: expected and observed doubles on the same archived PA exposures\nHistorical actual-state diagnosis; training chronology uncertified · * fewer than 1,000 PAs", fontsize=12)
    fig.savefig(OUT / "doubles-by-inning.png", dpi=170, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineage", type=Path)
    parser.add_argument("--focus-inning-group", action="append", default=[])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    scope = {"population": "Frozen fold5 only, 101264 eligible Development PAs", "inningGroups": GROUPS, "probabilityBands": BANDS, "support": "At least1000 PAs and100 distinct games; descriptive, no inference threshold", "maximumFocusedConcentrations": 2, "priorBattersFacedBins": ["0–8", "9–17", "18–26", "27+"], "noRoleInferenceFromInning": True, "noOutcomeSelectedCutpoints": True, "modelFits": 0, "modelInference": 0, "sourceAcquisition": 0, "bootstrapRuns": 0}
    scope_path = OUT / "scope.json"
    if scope_path.exists(): assert json.loads(scope_path.read_text(encoding="utf-8")) == scope
    else: json_write(scope_path, scope)
    df, receipt = load_rows()
    df = contexts(df, args.lineage)
    table = summarize(df, args.focus_inning_group)
    table.to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
    plot(table)
    manifest = {"schemaVersion": "MLB_V18_DOUBLES_INNING_DURATION_V1", "createdAtUtc": datetime.now(timezone.utc).isoformat(), "branch": subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(), "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(), "scope": scope, "rowCacheReceipt": ref(OUT / "row-cache-receipt.json"), "lineage": ref(args.lineage) if args.lineage else None, "focusedInningGroups": args.focus_inning_group, "classChecks": receipt["checks"], "outputs": [ref(OUT / n) for n in ["results.csv", "doubles-by-inning.png"]], "script": ref(__file__), "partitionReconciliationPassed": True, "uncertaintyIntervalsCalculated": False, "finalOotRead": False, "historicalTrainingTimingUncertified": True}
    attribution = []
    for group in args.focus_inning_group:
        f = df.loc[df.p_double.ge(.05) & df.p_double.lt(.10) & df.inning_group.eq(group)]
        record = {"inningGroup": group, "PAs": len(f), "signedExcess": float(f.residual_double.sum())}
        for field in ["pitcherCanonicalPlayerId", "canonicalGameId"]:
            counts = f.groupby(field).size().sort_values(ascending=False)
            key = counts.index[0]
            record[field] = {"largestExposureIdentity": str(key), "PAs": int(counts.iloc[0]), "exposureSharePct": float(100*counts.iloc[0]/len(f)), "signedExcess": float(f.loc[f[field].eq(key), "residual_double"].sum())}
        attribution.append(record)
    manifest["focusedExposureConcentration"] = attribution
    manifest["sensitivityNeededForDominantIdentity"] = any(v[f]["exposureSharePct"] >= 10 for v in attribution for f in ["pitcherCanonicalPlayerId", "canonicalGameId"])
    json_write(OUT / "manifest.json", manifest)
    print(table[(table.section == "inning_group") & table.population.isin(["ALL_FOLD5", LOWER, PRIMARY])][["population", "inning_group", "PAs", "games", "expected_doubles", "observed_doubles", "predicted_per100", "observed_per100", "bias_pp", "signed_excess", "support"]].to_string(index=False))
    print(json.dumps({"classChecks": receipt["checks"], "manifest": ref(OUT / "manifest.json")}, indent=2))


if __name__ == "__main__":
    main()

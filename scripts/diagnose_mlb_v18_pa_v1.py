"""Saved-prediction diagnosis only. No estimator loading, inference, or fitting.

Run from the repository: .venv/Scripts/python.exe scripts/diagnose_mlb_v18_pa_v1.py
The physical column reader gates keys before it reads outcomes. Mixed source
objects are read for identity columns only, never hashed in their entirety.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import t as student_t

from server.sports_current_statcast.mlb_regime_baseline import AuthorizedByteReader, footer_metadata
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask, quarantine_ledger
from server.sports_modeling.metrics import per_row_log_loss, per_row_brier_score

OUT = ROOT / "outputs/mlb-v18-empirical-diagnosis-v1/pa"
CACHE = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache"
RUNTIME = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory"
V18_SHA = "b79a80398ef32a13589a8bb66f5e4e9c698b600195de5369886f7fc07f0dc215"
V14_SHA = "9ec1c7b4e5365d4b07300caf58fb12dfaa53947ae78a062dc302e55181d0686a"
CONTEXT = Path("C:/Users/james/asp-data-staging/mlb-current-statcast-context-gold-v2")
CONTEXT_SHA = "4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e"
CACHE_MANIFEST = CACHE / "baseline-reproduction-0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9.json"
TEAM = ROOT / "outputs/mlb-v19-current-state-specialists-v1/game-context/sha256/b94fa31772a6d79e5f8b80ec414e0ec8b41a2dcf36b65c3fae9dba0e47bcfd9a/game-context.parquet"
TIMING = ROOT / "outputs/mlb-v18-conditional-champion-v1/development-integrity/sha256/853fc330c98e56e987905980e06225190cbe8985c4c19f4c2b035c20dba2078f/pa-diagnostic-projection.parquet"
CLASSES = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"]
PCOLS = ["probability_" + c for c in CLASSES]
KEYS = ["canonicalPaId", "canonicalGameId", "game_id", "game_date", "season", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "datasetRole"]
BANDS = np.array([0, .01, .025, .05, .10, .20, .30, .40, .50, .60, .80, 1.0000001])
TIMING_STATUS = "EXPLORATORY_TIMING_UNCERTAIN"
READS: list[dict] = []
REFS: list[dict] = []


def ref(path, expected=None):
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    value = {"path": str(path.resolve()), "sha256": h.hexdigest(), "bytes": path.stat().st_size}
    if expected and value["sha256"] != expected:
        raise ValueError(f"Source checksum mismatch: {path}")
    REFS.append(value)
    return value


def json_read(path, expected=None):
    ref(path, expected)
    return json.loads(Path(path).read_bytes())


def physical_columns(path, columns, purpose):
    """Footer + requested column chunks; Arrow read-ahead gets zero padding."""
    path = Path(path)
    metadata, footer_start = footer_metadata(path)
    names = metadata.schema.to_arrow_schema().names
    if not set(columns) <= set(names):
        raise ValueError(f"Missing columns: {set(columns) - set(names)}")
    ranges = [(0, 4), (footer_start, path.stat().st_size)]
    for g in range(metadata.num_row_groups):
        row = metadata.row_group(g)
        for i in range(row.num_columns):
            col = row.column(i)
            if col.path_in_schema in columns:
                offsets = [col.data_page_offset]
                if col.has_dictionary_page:
                    offsets.append(col.dictionary_page_offset)
                start = min(offsets)
                ranges.append((start, start + col.total_compressed_size))
    with AuthorizedByteReader(path, ranges) as reader:
        frame = pq.ParquetFile(reader, pre_buffer=False).read(columns=columns, use_threads=False).to_pandas()
        physical_bytes = sum(b-a for a, b in reader.physical_reads)
    READS.append({"path": str(path.resolve()), "purpose": purpose, "columns": columns,
                  "rows": len(frame), "physicalBytesIncludingRepeatedMetadata": physical_bytes,
                  "onlyAllowlistedColumnChunksRead": True})
    return frame


def key_gate(frame, label):
    if frame.canonicalGameId.isna().any() or frame.canonicalPaId.isna().any():
        raise ValueError(label + ": missing identities")
    if not all(final_oot_eligible_key_mask(frame.canonicalGameId)):
        raise ValueError(label + ": quarantined game; no outcome read allowed")
    if "game_date" in frame and not frame.game_date.astype(str).between("2023-03-30", "2026-08-13").all():
        raise ValueError(label + ": outside Development; no outcome read allowed")
    if frame.canonicalPaId.duplicated().any():
        raise ValueError(label + ": duplicate PA")


def holm(pvalues):
    p = np.asarray(pvalues, dtype=float)
    result = np.full(len(p), np.nan)
    valid = np.where(np.isfinite(p))[0]
    order = valid[np.argsort(p[valid], kind="stable")]
    if len(order):
        result[order] = np.minimum(1, np.maximum.accumulate(p[order] * np.arange(len(order), 0, -1)))
    return result


def clustered(values, labels):
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    n = len(values)
    if not n:
        return np.full((values.shape[1], 4), np.nan)
    codes, unique = pd.factorize(labels, sort=False)
    k = len(unique)
    means = values.mean(axis=0)
    if k < 2:
        return np.column_stack([means, means*np.nan, means*np.nan, means*np.nan])
    counts = np.bincount(codes)
    sums = np.stack([np.bincount(codes, weights=values[:, j]) for j in range(values.shape[1])], axis=1)
    score = sums - counts[:, None] * means
    se = np.sqrt(k/(k-1) * np.sum(score*score, axis=0)) / n
    crit = student_t.ppf(.975, k-1)
    z = np.divide(np.abs(means), se, out=np.full_like(means, np.inf), where=se > 0)
    p = 2*student_t.sf(z, k-1)
    p[(se == 0) & (means == 0)] = 1
    return np.column_stack([means, means-crit*se, means+crit*se, p])


def bootstrap_ratio(values, frame, kind, seed=20260911, reps=2000):
    values = np.asarray(values)
    if values.ndim == 1:
        values = values[:, None]
    if kind == "game":
        labels = frame.canonicalGameId.astype(str)
        strata = np.zeros(len(frame), dtype=int)
    else:
        dates = pd.to_datetime(frame.game_date)
        # Fixed calendar blocks, consecutive four weeks anchored at season Jan 1.
        block = (dates.dt.dayofyear.to_numpy()-1)//28
        labels = frame.season.astype(str) + "-block-" + pd.Series(block, index=frame.index).astype(str)
        strata = frame.season.to_numpy()
    codes, unique = pd.factorize(labels, sort=True)
    k = len(unique)
    counts = np.bincount(codes)
    sums = np.stack([np.bincount(codes, weights=values[:, j]) for j in range(values.shape[1])], axis=1)
    first = np.unique(codes, return_index=True)[1]
    cluster_strata = np.asarray(strata)[first]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(0, reps, 64):
        size = min(64, reps-len(draws)*64)
        if size <= 0:
            break
        numer = np.zeros((size, values.shape[1]))
        denom = np.zeros(size)
        for stratum in np.unique(cluster_strata):
            ids = np.where(cluster_strata == stratum)[0]
            chosen = rng.choice(ids, (size, len(ids)), replace=True)
            numer += sums[chosen].sum(axis=1)
            denom += counts[chosen].sum(axis=1)
        draws.append(numer/denom[:, None])
    matrix = np.concatenate(draws)
    return {"clusters": k, "replicates": len(matrix), "lower": np.quantile(matrix, .025, axis=0).tolist(),
            "upper": np.quantile(matrix, .975, axis=0).tolist(),
            "temporalSupport": "DESCRIPTIVE_FEWER_THAN_EIGHT_BLOCKS" if kind != "game" and k < 8 else "SAMPLING_INTERVAL_ONLY_TIMING_UNCERTAIN"}


def native(obj):
    if isinstance(obj, dict):
        return {str(k): native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [native(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if np.isfinite(obj) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def dump(name, value):
    (OUT/name).write_text(json.dumps(native(value), indent=2, allow_nan=False)+"\n", encoding="utf-8")


def load_data():
    quarantine_ledger()
    protocol = ref(OUT.parent / "PROTOCOL.md")
    cache_manifest = json_read(CACHE_MANIFEST, CACHE_MANIFEST.stem.split("baseline-reproduction-")[1])
    context_manifest = json_read(CONTEXT/f"publications/sha256/{CONTEXT_SHA}/manifest.json", CONTEXT_SHA)
    frames = []
    for entry in context_manifest["partitions"]:
        path = CONTEXT / entry["relativePath"]
        if path.stat().st_size != entry["byteCount"]:
            raise ValueError("Source identity object size differs")
        identity = physical_columns(path, KEYS, "IDENTITY_ONLY_NO_OUTCOMES_INCLUDING_MIXED_OBJECT")
        # Permanent quarantine before date-filtering or any target access.
        eligible = np.array(final_oot_eligible_key_mask(identity.canonicalGameId))
        eligible &= identity.game_date.astype(str).between("2023-03-30", "2026-08-13").to_numpy()
        frames.append(identity.loc[eligible].copy())
    identity = pd.concat(frames, ignore_index=True)
    key_gate(identity, "full Development identity")
    if set(identity.datasetRole) != {"DEVELOPMENT_SELECTION"}:
        raise ValueError("Wrong identity population")
    identity = identity.set_index("canonicalPaId", verify_integrity=True)
    model_frames = []
    for sha, label in [(V18_SHA, "V18"), (V14_SHA, "V14")]:
        path = RUNTIME/f"objects/oof/sha256/{sha}.parquet"
        keys = physical_columns(path, ["canonicalPaId", "canonicalGameId", "foldNumber"], label+"_KEYS_BEFORE_OUTCOMES")
        meta = identity.reindex(keys.canonicalPaId)
        if meta.canonicalGameId.isna().any() or not np.array_equal(meta.canonicalGameId.to_numpy(), keys.canonicalGameId.to_numpy()):
            raise ValueError("OOF does not exactly join eligible Development identity")
        gated = keys.merge(meta.drop(columns="canonicalGameId").reset_index(), on="canonicalPaId", validate="one_to_one", sort=False)
        key_gate(gated, label)
        ref(path, sha)  # Whole-file hashing is safe only after complete key gate.
        predictions = physical_columns(path, ["canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex", *PCOLS], label+"_GATED_DEVELOPMENT_PREDICTIONS")
        predictions = predictions.merge(meta.drop(columns="canonicalGameId").reset_index(), on="canonicalPaId", validate="one_to_one", sort=False)
        model_frames.append(predictions)
    df, comparator = model_frames
    other = comparator.set_index("canonicalPaId", verify_integrity=True).reindex(df.canonicalPaId)
    for col in ("canonicalGameId", "foldNumber", "observedClassIndex"):
        if not np.array_equal(df[col].to_numpy(), other[col].to_numpy()):
            raise ValueError("Reference identity/fold/target mismatch")
    p = df[PCOLS].to_numpy(dtype=float)
    q = other[PCOLS].to_numpy(dtype=float)
    for matrix in (p, q):
        if not np.isfinite(matrix).all() or (matrix < 0).any() or not np.allclose(matrix.sum(axis=1), 1, atol=1e-12, rtol=0):
            raise ValueError("Invalid saved probabilities")
    raw_path = CACHE / "raw-development.parquet"
    raw_keys = physical_columns(raw_path, ["canonicalPaId", "canonicalGameId", "game_date"], "CONTEXT_KEY_GATE")
    key_gate(raw_keys, "context")
    raw_sha = ref(raw_path)["sha256"]
    if raw_sha not in json.dumps(cache_manifest):
        raise ValueError("Context cache hash absent from its immutable receipt")
    cols = footer_metadata(raw_path)[0].schema.to_arrow_schema().names
    excluded = set(KEYS + ["outcome", "observedClassIndex", "foldNumber"])
    # Read only the declared diagnostic contexts, not a wide model matrix.
    features = ["batter_prior_missing", "pitcher_prior_missing", "batter_prior_pa_count", "pitcher_prior_bf_count",
                "batter_last100_pa_count", "pitcher_last250_bf_count", "matchup_platoon_advantage",
                "matchup_pitcher_throws_left", "matchup_batter_bats_left", "matchup_batter_bats_switch",
                "batting_short_rest_indicator", "fielding_short_rest_indicator", "batting_travel_path_missing",
                "pitcher_last250_velocity_missing", "batter_last100_whiff_missing", "batting_pregame_temperature_missing",
                "fielding_recent_bullpen_workload_missing", "pitcher_gs_per_g", "pitcher_last250_fastball_usage",
                "batting_travel_distance_miles", "context_inning", "context_outs_before", "context_base_mask_before",
                "context_batting_score_diff_before", "context_top_bottom"]
    if not set(features) <= set(cols):
        raise ValueError("Declared context missing from cache schema")
    raw = physical_columns(raw_path, ["canonicalPaId", *features], "SAVED_CONTEXT_ONLY_NO_TARGETS").set_index("canonicalPaId", verify_integrity=True)
    aligned = raw.reindex(df.canonicalPaId)
    aligned.index = df.index
    df = pd.concat([df, aligned], axis=1)
    df["contextAvailable"] = df.canonicalPaId.isin(raw.index)
    team_cols = footer_metadata(TEAM)[0].schema.to_arrow_schema().names
    team = physical_columns(TEAM, team_cols, "TEAM_IDENTITY_ONLY")
    if not all(final_oot_eligible_key_mask(team.canonicalGameId)) or not team.game_date.astype(str).between("2023-03-30", "2026-08-13").all():
        raise ValueError("Team identity scope")
    ref(TEAM, "9a642b0f373ef27bb684f46304661929843e9d60bef8188d2341c6373790296d")
    team_cols = [c for c in team if c not in ["game_date", "game_id"]]
    df = df.merge(team[team_cols], on="canonicalGameId", how="left", validate="many_to_one", sort=False)
    timing = physical_columns(TIMING, footer_metadata(TIMING)[0].schema.to_arrow_schema().names, "EXISTING_TIMING_FLAGS_NO_TARGETS")
    key_gate(timing, "timing flags")
    ref(TIMING, "6c9fde5e36682d492379efadf229345139ac1c902b8831cf74f72a9010248a80")
    timing_cols = ["canonicalPaId", "candidateConservativeRowEligibility", "certifiedHistoricalMetricEligibility", "potentialKnownFeatureExposure", "timingStatus"]
    df = df.merge(timing[timing_cols], on="canonicalPaId", how="left", validate="one_to_one", sort=False)
    if df.certifiedHistoricalMetricEligibility.eq(True).any():
        raise ValueError("Unexpected new timing authority: review before analysis")
    df["week"] = pd.to_datetime(df.game_date).dt.strftime("%G-W%V")
    df["season"] = pd.to_datetime(df.game_date).dt.year
    y = df.observedClassIndex.to_numpy(dtype=int)
    observed = np.eye(8)[y]
    ll = -np.log(np.clip(p[np.arange(len(p)), y], np.finfo(float).eps, 1))
    llq = -np.log(np.clip(q[np.arange(len(p)), y], np.finfo(float).eps, 1))
    brier = ((p-observed)**2).sum(axis=1)
    brierq = ((q-observed)**2).sum(axis=1)
    validation = {"v18_log_loss_max_difference_from_existing_scorer": float(np.abs(ll-per_row_log_loss(y,p)).max()),
                  "v18_brier_max_difference_from_existing_scorer": float(np.abs(brier-per_row_brier_score(y,p)).max()),
                  "v14_log_loss_max_difference_from_existing_scorer": float(np.abs(llq-per_row_log_loss(y,q)).max()),
                  "minimum_probability_of_observed_class": float(p[np.arange(len(p)),y].min()),
                  "v18_pa_count": len(df), "aligned_reference_pa_count": len(other),
                  "probability_row_sum_max_error": float(np.abs(p.sum(axis=1)-1).max()),
                  "block_method": "FIXED_NONOVERLAPPING_28_DAY_BLOCKS_ANCHORED_JAN1_RESAMPLED_WITHIN_SEASON"}
    assert validation["v18_log_loss_max_difference_from_existing_scorer"] < 1e-12
    assert validation["v18_brier_max_difference_from_existing_scorer"] < 1e-12
    assert validation["v14_log_loss_max_difference_from_existing_scorer"] < 1e-12
    recovery = json_read(ROOT/"outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d.json")
    for label, values in [("corrected",ll),("baseline",llq)]:
        expected = recovery["matchingObservationComparison"][label]["multiclassLogLoss"]
        validation[label+"_log_loss_difference_from_saved_recovery"] = float(values.mean()-expected)
        assert abs(values.mean()-expected) < 1e-12
    dump("validation.json", validation)
    return df, p, q, y, observed, ll, llq, brier, brierq, protocol, {"v14OriginalPaCount": len(comparator), "v14OnlyHeldPaCount": len(comparator)-len(df), "contextMatchedPaCount": int(df.contextAvailable.sum()), "contextUnmatchedPaCount": int((~df.contextAvailable).sum())}


def groups_for(df, p):
    groups = []
    n = len(df)
    available = df.contextAvailable.to_numpy()
    def add(name, family, mask, definition, observable="HISTORICAL_PREGAME_CANDIDATE_UNCERTIFIED_CLOCKS"):
        groups.append({"regime": name, "family": family, "mask": np.asarray(mask, dtype=bool), "definition": definition, "observable": observable})
    add("all", "population", np.ones(n, bool), "All eligible V18 Development OOF predictions", "PRE_PA_CONDITIONAL_FORECAST")
    add("fold5_exact_estimator", "population", df.foldNumber == 5, "Fold 5 only, today's frozen estimator, historical conditional PAs", "PRE_PA_CONDITIONAL_FORECAST")
    add("context_unavailable", "coverage", ~available, "Eligible OOF with no saved context cache join", "NOT_AN_OBSERVABLE_REGIME")
    def binary(column, family=None):
        x = pd.to_numeric(df[column], errors="coerce")
        for val in [0, 1]:
            add(column+"="+str(val), family or column, available & (x == val), f"{column} == {val}")
        add(column+"=missing", family or column, available & x.isna(), f"{column} is missing")
    for c in ["batter_prior_missing", "pitcher_prior_missing", "matchup_platoon_advantage", "matchup_pitcher_throws_left", "matchup_batter_bats_left", "matchup_batter_bats_switch", "batting_short_rest_indicator", "fielding_short_rest_indicator", "batting_travel_path_missing", "pitcher_last250_velocity_missing", "batter_last100_whiff_missing", "batting_pregame_temperature_missing", "fielding_recent_bullpen_workload_missing"]:
        binary(c)
    for column, bound in [("batter_last100_pa_count", 100), ("pitcher_last250_bf_count", 250)]:
        x = pd.to_numeric(df[column], errors="coerce")
        for label, mask in [("zero", x == 0), ("low", (x > 0) & (x < bound)), ("established", x >= bound), ("missing", x.isna())]:
            add(column+"="+label, column, available & mask, f"{column}: {label}; established >= {bound}")
    specifications = [
        ("pitcher_gs_per_g", [("relief_leaning_prior", 0, .5), ("starter_leaning_prior", .5, np.inf)]),
        ("pitcher_last250_fastball_usage", [("below_40pct", -np.inf, .4), ("40_to_60pct", .4, .6), ("60pct_plus", .6, np.inf)]),
        ("batting_travel_distance_miles", [("under_500", -np.inf, 500), ("500_plus", 500, np.inf)]),
        ("context_inning", [("1_to_3", 1, 4), ("4_to_6", 4, 7), ("7_plus", 7, np.inf)]),
    ]
    for col, specs in specifications:
        x = pd.to_numeric(df[col], errors="coerce")
        obs = "OBSERVED_PRE_PA_STATE_NOT_KNOWN_AT_PREGAME" if col.startswith("context") else "HISTORICAL_PREGAME_CANDIDATE_UNCERTIFIED_CLOCKS"
        for label, lo, hi in specs:
            add(col+"="+label, col, available & (x >= lo) & (x < hi), f"{lo} <= {col} < {hi}", obs)
        add(col+"=missing", col, available & x.isna(), col+" missing", obs)
    for val in [0, 1, 2]:
        add("outs="+str(val), "PA_state", available & (df.context_outs_before == val), f"context_outs_before == {val}", "OBSERVED_PRE_PA_STATE_NOT_KNOWN_AT_PREGAME")
    for label, mask in [("empty", df.context_base_mask_before == 0), ("occupied", df.context_base_mask_before > 0)]:
        add("bases="+label, "PA_state", available & mask, "context_base_mask_before: "+label, "OBSERVED_PRE_PA_STATE_NOT_KNOWN_AT_PREGAME")
    for season in sorted(df.season.unique()):
        add("season="+str(season), "season", df.season == season, f"season == {season}")
    month = pd.to_datetime(df.game_date).dt.month
    for label, mask in [("March_April", month <= 4), ("May_June", month.between(5, 6)), ("July_August", month.between(7, 8)), ("September_October", month >= 9)]:
        add(label, "season_period", mask, "calendar months: "+label)
    maximum = p.max(axis=1)
    for lo, hi in [(0, .4), (.4, .5), (.5, .6), (.6, 1.00001)]:
        add(f"confidence={lo:.1f}-{min(hi,1):.1f}", "confidence", (maximum >= lo) & (maximum < hi), f"{lo} <= max class probability < {hi}", "AVAILABLE_AT_PA_FORECAST")
    cold = (df.batter_prior_missing == 1) | (df.pitcher_prior_missing == 1)
    low = (df.batter_last100_pa_count < 100) | (df.pitcher_last250_bf_count < 250)
    add("either_prior_missing", "prior_exposure", available & cold, "batter_prior_missing == 1 OR pitcher_prior_missing == 1")
    add("cold_x_low_rolling", "interaction", available & cold & low, "either prior missing AND either rolling count below target")
    add("platoon_x_low_pitcher_rolling", "interaction", available & (df.matchup_platoon_advantage == 1) & (df.pitcher_last250_bf_count < 250), "platoon advantage AND pitcher BF < 250")
    add("late_x_bases_occupied", "interaction", available & (df.context_inning >= 7) & (df.context_base_mask_before > 0), "inning >= 7 AND occupied bases", "OBSERVED_PRE_PA_STATE_NOT_KNOWN_AT_PREGAME")
    add("short_rest_x_long_travel", "interaction", available & (df.batting_short_rest_indicator == 1) & (df.batting_travel_distance_miles >= 500), "batting short rest AND travel >= 500 miles")
    return groups


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df, p, q, y, observed, ll, llq, brier, brierq, protocol, accounting = load_data()
    print("Eligibility and identities verified; saved PA scoring starts", flush=True)
    delta = ll-llq
    bias = p-observed
    entropy = -(p*np.log(np.clip(p, 1e-15, 1))).sum(axis=1)
    windows = {"all": np.ones(len(df), bool), "early_folds1_3": (df.foldNumber <= 3).to_numpy(), "later_folds4_5": (df.foldNumber >= 4).to_numpy(), **{f"fold{k}": (df.foldNumber == k).to_numpy() for k in range(1, 6)}}
    support_frame = df[["canonicalGameId", "game_date", "week", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "homeTeamId", "awayTeamId"]]
    def support(mask):
        f = support_frame.loc[mask]
        teams = pd.concat([f.homeTeamId, f.awayTeamId]).dropna()
        return {"pa_count": len(f), "games": f.canonicalGameId.nunique(), "dates": f.game_date.nunique(), "weeks": f.week.nunique(), "batters": f.batterCanonicalPlayerId.nunique(), "pitchers": f.pitcherCanonicalPlayerId.nunique(), "players": pd.concat([f.batterCanonicalPlayerId, f.pitcherCanonicalPlayerId]).nunique(), "teams": teams.nunique() if len(teams) else None, "team_identity_missing_pa": int(f.homeTeamId.isna().sum()), "first_date": f.game_date.min() if len(f) else None, "last_date": f.game_date.max() if len(f) else None}
    def scores(mask):
        mix = observed[mask].mean(axis=0)
        return {"v18_log_loss": ll[mask].mean(), "v14_log_loss": llq[mask].mean(), "delta_log_loss": delta[mask].mean(), "v18_brier": brier[mask].mean(), "v14_brier": brierq[mask].mean(), "accuracy": (p[mask].argmax(axis=1) == y[mask]).mean(), "predicted_entropy": entropy[mask].mean(), "observed_mix_entropy": -np.sum(mix*np.log(np.clip(mix, 1e-15, 1))), "average_max_probability": p[mask].max(axis=1).mean()}
    summary = {"generatedAtUtc": datetime.now(timezone.utc).isoformat(), "timingStatus": TIMING_STATUS, "noUntouchedHistoricalConfirmation": True, "protocol": protocol, "accounting": accounting, "windows": {}, "sealedFinalOotRemainingKeys": 13837, "sealedFinalOotPayloadRead": False, "permanentQuarantinedPredictionRowsRead": 0}
    class_rows, band_rows, regime_rows, temporal_rows = [], [], [], []
    for name, mask in windows.items():
        print("Summary window: "+name, flush=True)
        stats = clustered(np.column_stack([delta[mask], bias[mask]]), df.loc[mask, "canonicalGameId"])
        summary["windows"][name] = {**support(mask), **scores(mask), "delta_log_loss_game_cluster_ci95": stats[0, 1:3].tolist(), "class_bias_game_cluster_intervals": {c: stats[j+1].tolist() for j, c in enumerate(CLASSES)}}
        for j, c in enumerate(CLASSES):
            class_rows.append({"window": name, "class": c, **support(mask), "predicted": p[mask,j].mean(), "observed": observed[mask,j].mean(), "v14_predicted": q[mask,j].mean(), "bias": bias[mask,j].mean(), "v14_bias": (q[mask,j]-observed[mask,j]).mean(), "bias_ci_lower": stats[j+1,1], "bias_ci_upper": stats[j+1,2], "bias_p": stats[j+1,3], "timing_status": TIMING_STATUS})
            for lo, hi in zip(BANDS[:-1], BANDS[1:]):
                selected = mask & (p[:,j] >= lo) & (p[:,j] < hi)
                if not selected.any():
                    continue
                stat = clustered(bias[selected,j], df.loc[selected, "canonicalGameId"])[0]
                band_rows.append({"window": name, "class": c, "lower": lo, "upper": min(hi,1), **support(selected), "predicted": p[selected,j].mean(), "observed": observed[selected,j].mean(), "bias": stat[0], "bias_ci_lower": stat[1], "bias_ci_upper": stat[2], "p": stat[3]})
    groups = groups_for(df, p)
    empty = []
    for group_index, g in enumerate(groups):
        if group_index % 15 == 0:
            print(f"Declared regimes: {group_index}/{len(groups)}", flush=True)
        mask = g["mask"]
        if not mask.any():
            empty.append({k:v for k,v in g.items() if k != "mask"})
            continue
        sup = support(mask)
        stat = clustered(np.column_stack([delta[mask], bias[mask]]), df.loc[mask, "canonicalGameId"])
        row = {k:v for k,v in g.items() if k != "mask"}
        row.update({**sup, **scores(mask), "delta_ci_lower": stat[0,1], "delta_ci_upper": stat[0,2], "delta_p": stat[0,3], "timing_status": TIMING_STATUS})
        for j, c in enumerate(CLASSES):
            row[f"bias_{c}"] = stat[j+1,0]
            row[f"bias_p_{c}"] = stat[j+1,3]
            row[f"bias_lower_{c}"] = stat[j+1,1]
            row[f"bias_upper_{c}"] = stat[j+1,2]
            row[f"predicted_{c}"] = p[mask,j].mean()
            row[f"observed_{c}"] = observed[mask,j].mean()
        for win, wmask in windows.items():
            if win == "all":
                continue
            m = mask & wmask
            if not m.any():
                continue
            s = scores(m)
            st = clustered(np.column_stack([delta[m], bias[m]]), df.loc[m, "canonicalGameId"])
            tr = {"regime": g["regime"], "window": win, **support(m), **s, "delta_ci_lower": st[0,1], "delta_ci_upper": st[0,2]}
            for j, c in enumerate(CLASSES):
                tr[f"bias_{c}"] = st[j+1,0]
                tr[f"bias_lower_{c}"] = st[j+1,1]
                tr[f"bias_upper_{c}"] = st[j+1,2]
            temporal_rows.append(tr)
            row[win+"_pa_count"] = int(m.sum())
            row[win+"_games"] = tr["games"]
            row[win+"_weeks"] = tr["weeks"]
            row[win+"_delta_log_loss"] = s["delta_log_loss"]
            row[win+"_BIP_OUT_bias"] = bias[m,6].mean()
        signs = [np.sign(row.get(w+"_delta_log_loss", np.nan)) for w in ["early_folds1_3", "fold4", "fold5"]]
        if sup["pa_count"] < 1000 or sup["games"] < 100 or sup["weeks"] < 8:
            row["finding_status"] = "INSUFFICIENT_SUPPORT"
        elif not all(np.isfinite(signs)) or any(row.get(w+"_pa_count",0) < 1000 or row.get(w+"_games",0) < 100 or row.get(w+"_weeks",0) < 8 for w in ["early_folds1_3", "fold4", "fold5"]):
            row["finding_status"] = "INSUFFICIENT_TEMPORAL_SUPPORT"
        elif len(set(signs)) > 1:
            row["finding_status"] = "UNSTABLE_REVERSED_REFERENCE_DIFFERENCE"
        else:
            row["finding_status"] = "EXPLORATORY_LEAD"
        regime_rows.append(row)
    regimes = pd.DataFrame(regime_rows)
    regimes["delta_p_holm"] = holm(regimes.delta_p)
    all_bias_p = regimes[["bias_p_"+c for c in CLASSES]].to_numpy()
    adjusted = holm(all_bias_p.ravel()).reshape(all_bias_p.shape)
    for j,c in enumerate(CLASSES):
        regimes["bias_p_holm_"+c] = adjusted[:,j]
    class_df = pd.DataFrame(class_rows)
    class_df["bias_p_holm_all_windows"] = holm(class_df.bias_p)
    bands_df = pd.DataFrame(band_rows)
    bands_df["p_holm_all_bands_windows"] = holm(bands_df.p)
    regimes.to_csv(OUT/"regimes.csv", index=False)
    pd.DataFrame(temporal_rows).to_csv(OUT/"regime-temporal-results.csv", index=False)
    class_df.to_csv(OUT/"class-calibration.csv", index=False)
    bands_df.to_csv(OUT/"probability-bands.csv", index=False)
    dump("unsupported-empty-regimes.json", empty)
    print(f"Scored {len(df):,} PAs; {len(regimes)} nonempty declared regimes", flush=True)

    # Predetermined sensitivity families; no fitted diagnostic regression.
    chosen = ["all", "fold5_exact_estimator", "either_prior_missing", "batter_prior_missing=1", "pitcher_prior_missing=1", "batter_last100_pa_count=low", "pitcher_last250_bf_count=low", "confidence=0.6-1.0", "late_x_bases_occupied", "short_rest_x_long_travel"]
    sensitivities, bootstrap = [], {}
    for g in groups:
        mask = g["mask"]
        if g["regime"] not in chosen or mask.sum() < 2:
            continue
        f = df.loc[mask, ["canonicalGameId", "game_date", "season", "homeTeamId", "awayTeamId"]]
        v = np.column_stack([delta[mask], bias[mask]])
        bootstrap[g["regime"]] = {"columns": ["delta_log_loss", *["bias_"+c for c in CLASSES]], "game": bootstrap_ratio(v, f, "game"), "four_week": bootstrap_ratio(v, f, "four_week")}
        removes = [("none", None, mask)]
        for col in ["batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "game_date"]:
            dominant = df.loc[mask,col].value_counts().index[0]
            removes.append(("drop_dominant_"+col, str(dominant), mask & (df[col] != dominant).to_numpy()))
        team_counts = pd.concat([f.homeTeamId, f.awayTeamId]).dropna().value_counts()
        if len(team_counts):
            dominant = team_counts.index[0]
            # Keep only known-team rows in this sensitivity, so missing identities cannot hide dominance.
            m = mask & df.homeTeamId.notna().to_numpy() & (df.homeTeamId != dominant).to_numpy() & (df.awayTeamId != dominant).to_numpy()
            removes.append(("known_teams_drop_dominant_team", str(dominant), m))
        m = mask & df.candidateConservativeRowEligibility.eq(True).to_numpy(dtype=bool)
        removes.append(("existing_conservative_timing_keys_ESTIMATOR_STILL_UNCERTAIN", None, m))
        for label, value, m in removes:
            if not m.any():
                continue
            row = {"regime": g["regime"], "sensitivity": label, "removed_identity": value, **support(m), **scores(m)}
            for j,c in enumerate(CLASSES):
                row["bias_"+c] = bias[m,j].mean()
            sensitivities.append(row)
    dump("bootstrap-intervals.json", bootstrap)
    pd.DataFrame(sensitivities).to_csv(OUT/"sensitivities.csv", index=False)

    # All-game PA ledger and deterministic severe/control selection.
    game_frame = df[["canonicalGameId", "game_date", "game_id", "foldNumber", "homeTeamId", "awayTeamId"]].copy()
    for c in ["homeTeamAbbrev", "awayTeamAbbrev", "homeTeamRetrosheetCode", "awayTeamRetrosheetCode"]:
        if c in df:
            game_frame[c] = df[c]
    game_frame["pa_log_loss"] = ll
    game_frame["v14_pa_log_loss"] = llq
    game_frame["predicted_entropy"] = entropy
    game_frame["bip_predicted"] = p[:,6]
    game_frame["bip_observed"] = observed[:,6]
    game_frame["pa_count"] = 1
    game_frame["either_prior_missing_share"] = ((df.batter_prior_missing == 1) | (df.pitcher_prior_missing == 1)).where(df.contextAvailable).astype(float)
    game_frame["low_batter_rolling_share"] = (df.batter_last100_pa_count < 100).where(df.contextAvailable).astype(float)
    game_frame["low_pitcher_rolling_share"] = (df.pitcher_last250_bf_count < 250).where(df.contextAvailable).astype(float)
    game_frame["platoon_advantage_share"] = pd.to_numeric(df.matchup_platoon_advantage, errors="coerce")
    game_frame["late_inning_share"] = (df.context_inning >= 7).where(df.contextAvailable).astype(float)
    game_frame["occupied_bases_share"] = (df.context_base_mask_before > 0).where(df.contextAvailable).astype(float)
    game_frame["batting_short_rest_share"] = pd.to_numeric(df.batting_short_rest_indicator, errors="coerce")
    game_frame["context_available_share"] = df.contextAvailable.astype(float)
    aggs = {c:"first" for c in game_frame if c != "canonicalGameId"}
    for c in ["pa_log_loss", "v14_pa_log_loss", "predicted_entropy", "bip_predicted", "bip_observed"]:
        aggs[c] = "mean"
    for c in game_frame:
        if c.endswith("_share"):
            aggs[c] = "mean"
    aggs["pa_count"] = "sum"
    games = game_frame.groupby("canonicalGameId", sort=True).agg(aggs).reset_index()
    games["bip_bias"] = games.bip_predicted-games.bip_observed
    games["bip_abs_bias"] = games.bip_bias.abs()
    games["delta_pa_log_loss"] = games.pa_log_loss-games.v14_pa_log_loss
    games.to_csv(OUT/"game-pa-ledger.csv", index=False)
    severe_ll = games.sort_values(["pa_log_loss", "canonicalGameId"], ascending=[False,True]).head(3)
    severe_bip = games.sort_values(["bip_abs_bias", "canonicalGameId"], ascending=[False,True]).head(3)
    cases = []
    for reason, selected in [("top3_mean_PA_log_loss", severe_ll), ("top3_abs_BIP_OUT_frequency_error", severe_bip)]:
        for _, row in selected.iterrows():
            cases.append({"selection": reason, **row.to_dict(), "whole_game_prediction": False, "predicted_runs": None, "final_runs": None})
    for _, target in severe_ll.iterrows():
        pool = games[(games.foldNumber == target.foldNumber) & (~games.canonicalGameId.isin([r["canonicalGameId"] for r in cases]))].copy()
        for label, quantile in [("matched_ordinary", .5), ("matched_successful", .25)]:
            goal = float(pool.pa_log_loss.quantile(quantile))
            # Restrict outcome rank, then match observable count/entropy without fitting.
            band = pool[np.abs(pool.pa_log_loss-goal) <= .025].copy()
            if band.empty:
                band = pool.copy()
            band["match_distance"] = np.abs(band.pa_count-target.pa_count)/max(1,target.pa_count) + np.abs(band.predicted_entropy-target.predicted_entropy)
            match = band.sort_values(["match_distance", "canonicalGameId"]).iloc[0]
            cases.append({"selection": label, "matched_to": target.canonicalGameId, **match.to_dict(), "whole_game_prediction": False, "predicted_runs": None, "final_runs": None})
    pd.DataFrame(cases).to_csv(OUT/"pa-game-casebook.csv", index=False)
    severe_ids = np.argsort(-ll, kind="stable")[:8]
    control_ids = []
    for idx in severe_ids:
        pool = np.where((df.foldNumber.to_numpy() == df.foldNumber.iloc[idx]) & (y == y[idx]) & (~np.isin(np.arange(len(df)), severe_ids)))[0]
        target = np.quantile(ll[pool], .25)
        control_ids.append(int(pool[np.argmin(np.abs(ll[pool]-target))]))
    context_columns = ["batter_prior_missing", "pitcher_prior_missing", "batter_last100_pa_count", "pitcher_last250_bf_count", "matchup_platoon_advantage", "pitcher_gs_per_g", "context_inning", "context_outs_before", "context_base_mask_before", "batting_short_rest_indicator"]
    pa_cases = df.iloc[np.r_[severe_ids, control_ids]][["canonicalPaId", "canonicalGameId", "game_date", "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "foldNumber", "observedClassIndex", *context_columns]].copy()
    pa_cases["selection"] = ["top8_PA_log_loss"]*8 + ["same_fold_actual_class_lower_quartile_loss_control"]*8
    pa_cases["matched_to"] = [None]*8 + df.canonicalPaId.iloc[severe_ids].tolist()
    ids = pa_cases.index.to_numpy()
    pa_cases["observed_class"] = [CLASSES[i] for i in y[ids]]
    pa_cases["probability_of_actual"] = p[ids,y[ids]]
    pa_cases["log_loss"] = ll[ids]
    for j,c in enumerate(CLASSES):
        pa_cases["probability_"+c] = p[ids,j]
    pa_cases.to_csv(OUT/"severe-pa-cases.csv", index=False)
    summary["searchAccounting"] = {"nonemptyPredefinedRegimes": len(regimes), "emptyPredefinedRegimes": len(empty), "groupLossTestFamily": len(regimes), "groupClassBiasTestFamily": len(regimes)*8, "probabilityBandTests": len(bands_df)}
    summary["lossQuantiles"] = {str(v):float(np.quantile(ll,v)) for v in [0,.01,.05,.25,.5,.75,.9,.95,.99,.999,1]}
    summary["paLossAtLeast3"] = int((ll >= 3).sum())
    summary["paLossAtLeast5"] = int((ll >= 5).sum())
    summary["teamIdentityUnavailableGames"] = df.loc[df.homeTeamId.isna(),"canonicalGameId"].nunique()
    summary["casebookInterpretation"] = "PA-game summaries are conditional PA diagnostics, not winner/run forecast errors. Final runs not accessed for these rows."
    dump("summary.json", summary)
    dump("input-manifest.json", {"references": REFS, "physicalReads": READS, "modelFits": 0, "inferenceCalls": 0, "simulations": 0, "ootPayloadReads": 0})
    make_plots(class_df, bands_df, pd.DataFrame(temporal_rows), ll, p, y, entropy)
    print(json.dumps(native({"all":summary["windows"]["all"], "accounting":accounting}), indent=2), flush=True)


def make_plots(classes, bands, temporal, ll, p, y, entropy):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 140, "savefig.facecolor":"white"})
    fig, axes = plt.subplots(2,4, figsize=(15,7), constrained_layout=True)
    for j,c in enumerate(CLASSES):
        ax = axes.flat[j]
        for win, color, label in [("early_folds1_3", "#2166ac", "Folds 1–3"), ("fold4", "#c78324", "Fold 4"), ("fold5", "#b2182b", "Fold 5")]:
            b = bands[(bands.window == win) & (bands["class"] == c) & (bands.pa_count >= 500)]
            ax.plot(b.predicted, b.observed, "o-", markersize=3, color=color, label=label)
        ax.plot([0,1],[0,1],"--",color="#888",linewidth=.8)
        relevant = bands[(bands["class"] == c) & (bands.pa_count >= 500)]
        top = min(1, max(.04, float(relevant[["predicted","observed"]].max().max())*1.15))
        ax.set(xlim=(0,top), ylim=(0,top), title=c, xlabel="Mean predicted probability", ylabel="Observed frequency")
    axes.flat[0].legend(fontsize=8)
    fig.suptitle("V18 saved PA calibration: fixed bands with ≥500 PAs\nHistorical timing uncertain; later folds are temporal checks, not untouched confirmation", fontsize=14)
    fig.savefig(OUT/"pa-calibration.png")
    plt.close(fig)
    f = classes[classes.window.str.match(r"fold[1-5]$")].pivot(index="class", columns="window", values="bias").reindex(CLASSES)*100
    fig, ax = plt.subplots(figsize=(10,5.5), constrained_layout=True)
    limit = max(1, np.abs(f.to_numpy()).max())
    im = ax.imshow(f, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    for i in range(8):
        for j in range(5):
            ax.text(j,i,f"{f.iloc[i,j]:+.2f}",ha="center",va="center",color="white" if abs(f.iloc[i,j])>.65*limit else "black")
    ax.set_xticks(range(5), f.columns)
    ax.set_yticks(range(8), CLASSES)
    ax.set_title("Predicted minus observed class frequency, percentage points\nPositive = overprediction; each column is a different fitted V18 fold")
    fig.colorbar(im,ax=ax,label="Percentage points")
    fig.savefig(OUT/"pa-class-bias-by-fold.png")
    plt.close(fig)
    fig, axes = plt.subplots(1,2, figsize=(12,4.8), constrained_layout=True)
    ordered = np.sort(ll)
    axes[0].plot(ordered, np.arange(1,len(ll)+1)/len(ll), color="#2166ac")
    axes[0].set(xlabel="PA log loss (natural-log units)", ylabel="Empirical cumulative fraction", title="Full empirical PA error distribution", xlim=(0,np.quantile(ll,.9995)))
    maxp = p.max(axis=1)
    confidence = []
    for lo,hi in [(0,.4),(.4,.5),(.5,.6),(.6,1.00001)]:
        m=(maxp>=lo)&(maxp<hi)
        confidence.append((maxp[m].mean(), (p[m].argmax(axis=1)==y[m]).mean(), int(m.sum())))
    axes[1].plot([0,1],[0,1],"--",color="#999")
    axes[1].plot([v[0] for v in confidence],[v[1] for v in confidence],"o-",color="#b2182b")
    for x,z,n in confidence:
        axes[1].annotate(f"n={n:,}",(x,z),xytext=(0,8),textcoords="offset points",fontsize=8)
    axes[1].set(xlabel="Mean maximum PA class probability", ylabel="Observed top-class accuracy", title="Confidence versus success, full Development OOF", xlim=(.25,.85),ylim=(.25,.85))
    fig.suptitle("Saved-prediction diagnostics; all historical timing remains exploratory",fontsize=13)
    fig.savefig(OUT/"pa-error-and-confidence.png")
    plt.close(fig)


if __name__ == "__main__":
    main()

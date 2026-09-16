"""Package the completed frozen assessment; no new sampling or model selection."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import reference,json_bytes,verified_bytes


def pct(x):
    return f'{100*x:.2f}%'


def write_report(root):
    if (root/'index.json').exists():
        index=json.loads((root/'index.json').read_bytes())
        for b in index['artifacts']+index['code']:
            verified_bytes(b)
        return reference(root/'index.json')
    d=json.loads((root/'assessment.json').read_bytes())
    method=json.loads((root/'method-freeze.json').read_bytes())
    counter=json.loads((root/'count-accounting-verification.json').read_bytes())
    preservation=json.loads((root/'final-preservation-verification.json').read_bytes())
    reproduce=json.loads((root/'reproduction-verification.json').read_bytes())
    assert counter['allChecksPassed'] and preservation['allBoundBytesUnchanged']
    a,b=d['groups']['all']['benchmark'],d['groups']['all']['paired']
    es=d['pairedUncertainty']['metrics']['energy']
    tr=d['supportTransformations']['paired']
    stages=tr['average_by_stage']
    changes=tr['final_minus_latent']
    example=json.loads((root/'totals-demonstration.json').read_bytes())
    popbytes=sum(p.stat().st_size for p in (root/'assessment').glob('*/*-joint-counts.parquet'))
    popcells=sum(x['jointCells'] for x in counter['seasonArms'])
    text=[
        '# NBA Gen 1 paired final-score distribution — completed research assessment', '',
        '**Recommendation: needs a specific close-score support correction before consumer use.** Retain this executable paired-residual baseline for further research. Pairing improves measured joint and marginal distribution scores, but the minimum-distance support rule places excessive probability on one-point finishes. No new model, calibration or publication is promoted.', '',
        f'One matched comparison covers **{b["games"]:,} games**, 2020–21 through 2025–26, with **10,000 draws per game per arm**. All seasons are reused historical evidence. The first 200 games lack the frozen minimum of 200 earlier OOF donors and remain unsupported. The 2019–20 season supplies initial point-model training, not in-sample residual donors. Neutral-site exclusions and original point-model cohorts remain unchanged.', '',
        'These are new retrospective research populations built from original season-forward corrected Ridge predictions. Every residual is actual HOME/AWAY minus its saved chronological out-of-fold prediction. The six fitted training boundaries precede their donor games; each target uses only strictly earlier-date donors. Same-date donors and targets are excluded. No all-history refit is applied retrospectively. Original acquisition lineage and finalized-record reconstruction qualifications remain attached: unobserved historical publication times and revision vintages are not reconstructed. The corrected feature specification was chosen using already-inspected Development evidence, so chronological fitting does not restore an untouched test.', '',
        f'The method was frozen at **{method["frozenAtUtc"]}**: `{method["engine"]}`. It subtracts the two means of the expanding earlier-donor bank, samples complete residual pairs, and adds corrected Ridge expectations. The simple benchmark permutes the sampled AWAY residual vector, preserving both exact pre-support marginal samples but removing their dependence in expectation. Both arms use the same Ridge points, 10,000 draws and score-support rule. There are no residual-scale/window searches or fitted calibration changes.', '',
        'Scores already include overtime. The support treatment projects each latent pair onto the nearest nonnegative, unequal integer score pair. After nearest coordinate rounding, a tie goes to the nearest valid one-coordinate ±1 neighbor; only equal distances (absolute tolerance 1e-12) use a symmetric seeded choice. It neither appends overtime nor discards draws or caps the upper tail. The original overtime-dependent simulator remains unchanged and unassessed.', '',
        '**Matched proper scores** — lower is better; Δ is paired minus benchmark. Energy and CRPS are in points; binary Brier is `(pHome − actualHomeWin)²`; final tie probability is zero.', '',
        '| Metric | Permuted benchmark | Paired residual | Δ [95% calendar-week interval] |',
        '|---|---:|---:|---:|']
    for label,key in [('Joint energy','energy'),('Total CRPS','total_crps'),('Margin CRPS','margin_crps'),('Winner log loss','log_loss'),('Binary Brier','binary_brier'),('Total MAE','total_mae'),('Margin MAE','margin_mae')]:
        x=d['pairedUncertainty']['metrics'][key]
        text.append(f'| {label} | {a[key]:.6f} | {b[key]:.6f} | {x["difference"]:+.6f} [{x["interval95"][0]:+.6f}, {x["interval95"][1]:+.6f}] |')
    text += ['',f'Joint energy improves by {100*(a["energy"]-b["energy"])/a["energy"]:.3f}% and improves in every season below. Winner-score intervals include zero, so recurring winner improvement is not established. Expected-score errors are effectively unchanged. Intervals use 2,000 paired bootstrap resamples across {d["pairedUncertainty"]["calendarWeeks"]} ISO calendar weeks, seed 731201; they describe game-level historical variation, not model/source uncertainty or proof of prospective gain.', '',
        '| Season | Games | Benchmark energy | Paired energy | Paired total CRPS | Paired margin CRPS |', '|---|---:|---:|---:|---:|---:|']
    for y in range(2021,2027):
        x=d['groups'][f'season_{y}']
        p=x['paired']
        text.append(f'| {y-1}–{str(y)[-2:]} | {p["games"]:,} | {x["benchmark"]["energy"]:.4f} | {p["energy"]:.4f} | {p["total_crps"]:.4f} | {p["margin_crps"]:.4f} |')
    text += ['', '**Central interval coverage and mean width** — equal-tail inverted-CDF quantiles, inclusive endpoints; widths are points. Full home/away results are retained in `assessment.json` and `results-table.csv`.', '',
        '| Distribution / nominal | Benchmark coverage / width | Paired coverage / width |', '|---|---:|---:|']
    for v in ('total','margin'):
        for q in (50,80,90):
            k=f'{v}_{q}'
            text.append(f'| {v.title()} {q}% | {pct(a[k+"_coverage"])} / {a[k+"_width"]:.2f} | {pct(b[k+"_coverage"])} / {b[k+"_width"]:.2f} |')
    text += ['', 'Pairing corrects much of the benchmark’s narrow total range and overly wide margin range. This is aggregate coverage, not certification of every conditional game or sportsbook line.', '',
        '| Predeclared group | Games | Paired energy Δ | Paired total 80% coverage | Paired margin 80% coverage |', '|---|---:|---:|---:|---:|']
    for name,label in [('ordinary_rest','Both ordinary rest supported'),('unavailable_rest','Unavailable rest'),('season_openers','Either team season opener')]:
        x=d['groups'][name]
        p=x['paired']
        text.append(f'| {label} | {p["games"]:,} | {p["energy"]-x["benchmark"]["energy"]:+.4f} | {pct(p["total_80_coverage"])} | {pct(p["margin_80_coverage"])} |')
    text += ['', 'The 79 opener and 81 unavailable-rest games overlap heavily; they are small descriptive groups, not independent confirmations. Winner log loss worsens slightly on both groups. No unsupported rest values were invented and no subgroup-specific correction was fitted.', '',
        f'**Tails:** Development froze low totals at ≤193 and high totals at ≥258. High totals occur in {pct(d["actualTailFrequencies"]["high"])} of games versus paired {pct(b["model_implied_high_total_frequency"])} and benchmark {pct(a["model_implied_high_total_frequency"])}. Low totals occur in {pct(d["actualTailFrequencies"]["low"])} versus paired {pct(b["model_implied_low_total_frequency"])} and benchmark {pct(a["model_implied_low_total_frequency"])}; the paired low tail is too heavy in aggregate. Observations fall below the paired 1st percentile in {pct(b["total_outside0.01"])} and above its 99th in {pct(b["total_outside0.99"])}. In 2025–26, the upper-95% exceedance rate is {pct(d["groups"]["season_2026"]["paired"]["total_outside0.95"])}. Tail-selected group tables are descriptive and cannot be read as unconditional interval coverage tests. Empirical donors preserve retained extremes but do not model unobserved tails beyond donor support.', '',
        f'**Support effects:** No negative latent draws occurred. Rounded ties occur in {pct(stages["rounded"]["tie_fraction"])} of paired draws, all retained and resolved. One-point mass moves from {pct(stages["rounded"]["one_point_fraction"])} after rounding to **{pct(b["one_point_probability"])}**, versus **{pct(b["actual_one_point_frequency"])} observed**. The rule amplifies a pre-existing excess near-zero margin mass; it does not explain all of it. No latent winner sign or home-win probability changed in these sampled populations. The final-minus-latent mean changes are HOME {changes["home_mean"]["mean_game_change"]:+.6f}, AWAY {changes["away_mean"]["mean_game_change"]:+.6f}, total {changes["total_mean"]["mean_game_change"]:+.6f} points. Maximum absolute per-game changes are HOME {changes["home_mean"]["maximum_absolute_game_change"]:.4f}, AWAY {changes["away_mean"]["maximum_absolute_game_change"]:.4f}, total {changes["total_mean"]["maximum_absolute_game_change"]:.4f}. Thus means are not claimed unchanged.', '',
        f'Total 1st/99th percentile shifts remain below one point in every game (maximum {changes["total_q0.01"]["maximum_absolute_game_change"]:.4f}/{changes["total_q0.99"]["maximum_absolute_game_change"]:.4f}). Integer support raises average low/high threshold probabilities by {100*changes["total_low_fraction"]["mean_game_change"]:.3f}/{100*changes["total_high_fraction"]["mean_game_change"]:.3f} percentage points versus the continuous samples. `support-effects.parquet` retains all four stage summaries and tails, including both arms. Full-bank centering preserves the Ridge means only before finite sampling and support; finite sample means remain separate quantities.', '',
        f'**Separate Elo output:** Joint-derived and Elo winner picks disagree on {d["jointVersusSeparateElo"]["picksDisagree"]:,}/{b["games"]:,} games; two joint probabilities are exactly 0.5. Mean absolute probability difference is {100*d["jointVersusSeparateElo"]["meanAbsoluteProbabilityDifference"]:.2f} percentage points. These outputs are not forced to agree and do not replace published Elo. Reliability bins are retained, including sparse extreme bins; no calibration was fitted.', '',
        f'**Illustrative totals query:** HOU at OKC, {example["game_date"]}, `{example["game_id"]}`, chosen by earliest eligible 2025–26 metadata before scoring. The new retrospective population has expected HOME {example["jointExpectedHome"]:.4f}, AWAY {example["jointExpectedAway"]:.4f}; total 80% range {example["central80TotalInterval"]}. Joint HOME-win probability is {example["jointDerivedHomeWinProbability"]:.4f}; the separate saved Elo probability is {example["eloHomeWinProbabilitySeparateOutput"]:.6f}. These are illustrative lines, not recorded market prices.', '',
        '| Line | Over win | Push | Under win | Draws |', '|---|---:|---:|---:|---:|']
    for x in example['queries']:
        text.append(f'| {x["line"]:g} | {x["over"]["win"]:.4f} | {x["over"]["push"]:.4f} | {x["under"]["win"]:.4f} | {x["drawCount"]:,} |')
    text += ['', 'Probability units are fractions from 0 to 1. Over wins when total > line, pushes at equality, loses below; Under reverses win/loss. Full final totals include overtime. Expected net return per unit stake is `pWin*(decimalOdds-1)-pLoss`; fair decimal odds are `1+pLoss/pWin` when pWin>0. There are no recorded prices or profitability claims. Correct probability accounting is not proof of calibrated exact push mass.', '',
        f'**Retention and verification:** {counter["populations"]:,} full populations retain {counter["retainedDraws"]:,} draws as {popcells:,} unique joint cells across 12 files ({popbytes:,} physical bytes). Joint count compression is lossless; it preserves the pairs and all scoring tails, not draw order. Seeds and ordered-draw hashes reproduce that order. All game/arm counts, means, winner mass and joint digests reconcile after rereading the saved files. Twelve targeted game/arm replays reproduce exact ordered draws and proper scores. Eighteen synthetic checks cover chronology, support, probability accounting and exact energy-score parity. These software checks are separate from the 7,009 observed-game assessment units.', '',
        'The conditional paired-sampler MCSE is simulation precision only (mean winner MCSE about 0.00463). Benchmark MCSE fields are iid-reference approximations because permutation induces dependence; they are not used for improvement claims. The original 123 bound artifacts/dirty files remain byte-identical, including the published BOS–DET point/Elo forecast with drawCount=0. An initial storage-range accessor typo stopped execution before any population was saved; its original runner and additive repair receipt are retained. No statistical setting changed.', '',
        '**Next correction:** Address the excess near-zero/one-point mass with one Development-only discrete-support treatment while keeping Ridge and residual pairing fixed. This assignment does not fit it, open a prospective study, integrate AISP, or add work to Claude. Aggregate range improvements justify preserving the research baseline; they do not justify promoting its exact-score probabilities.', '',
        '**Reproduce a retained example without writing or republishing anything:**', '',
        '```powershell', '.venv/Scripts/python.exe scripts/replay_nba_gen1_joint_residual.py --game-id nba-espn:game:401809243 --line 225.5', '```', '',
        'The one-time study commands were `run_nba_gen1_joint_residual.py freeze`, `run`, `report`, `verify`, followed by `verify_nba_gen1_joint_counts.py`. Completed artifacts are immutable; the replay command above is repeatable. Source/model bindings are in `residual-provenance.json`; the method is in `method-freeze.json`; all proper scores, groups and uncertainty are in `assessment.json`; `index.json` binds physical bytes. No provider requests, model fitting, new forecasts, consumer imports or operating authority changes occurred.', '']
    raw='\n'.join(text).encode('utf-8')
    (root/'REPORT.md').write_bytes(raw)
    save={'schema':'NBA_GEN1_JOINT_RESIDUAL_RESEARCH_INDEX_V1','createdAtUtc':datetime.now(timezone.utc).isoformat(),
        'researchOnly':True,'forecastPublication':False,'consumerIntegration':False,'verdict':'NEEDS_SPECIFIC_CLOSE_SCORE_SUPPORT_CORRECTION_BEFORE_CONSUMER_USE',
        'artifacts':[reference(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='index.json'],
        'code':[reference(p) for p in sorted((ROOT/'scripts').glob('*nba_gen1_joint*.py'))]+[reference(ROOT/'server/sports_nba_gen1'/n) for n in ('joint_residual.py','joint_residual_scoring.py')]}
    (root/'index.json').write_bytes(json_bytes(save))
    return reference(root/'index.json')


if __name__=='__main__':
    print(json.dumps(write_report(ROOT/'outputs/nba-gen1-joint-residual-v1'),indent=2))

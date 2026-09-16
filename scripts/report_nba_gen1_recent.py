"""Report saved recent-study evidence; no new source requests or model fits."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import reference, verified_bytes

OUT=ROOT/'outputs/nba-gen1-recent-v1'


def main():
    target=OUT/'REPORT.md'
    if target.exists():
        print(json.dumps({'status':'REUSED_REPORT','report':reference(target)},indent=2))
        return
    decl=json.loads(verified_bytes(json.loads((OUT/'declaration.json').read_bytes())['declaration']))
    source=json.loads((OUT/'acquisition.json').read_bytes())
    results={stage:json.loads((OUT/stage/'assessment.json').read_bytes()) for stage in ('development','validation','holdout')}
    choice=json.loads((OUT/'validation/selection.json').read_bytes())
    refit=json.loads((OUT/'post-assessment-refit/receipt.json').read_bytes())
    audit=json.loads((OUT/'holdout/feature-audit.json').read_bytes())
    rows=[r for stage in results.values() for r in stage['bySeason']]
    by={(r['seasonEnd'],r['modelId']):r for r in rows}
    lines=[
        '# NBA Gen 1 recent research model: 2019–20 through 2024–25',
        '',
        '**Recent data were acquired, the league/Elo benchmarks were assessed, and both Ridge and HGB were fitted. The locked Validation choice is Ridge alpha 100 for expected scores, retaining the unchanged chronological Elo winner-probability channel.** It improves total and margin error in the final 2024–25 Category-A holdout. This is a reduced score/date research baseline with a documented early-fold numerical limitation; it is not a validated joint-distribution model or funded/production release.',
        '',
        'The source is Neil Paine’s published NBA Elo data archive, updated from FiveThirtyEight. The selected immutable April 14, 2025 export supplies game dates, season, mirrored teams/scores, neutral/playoff flags and explicit is_home orientation. Its data-repository MIT license permits reuse; Neil Paine’s notice and upstream FiveThirtyEight attribution/CC BY notice are retained. No API-client license is being used as a substitute for data rights. The previously completed FiveThirtyEight approval was not reopened.',
        '',
        f'One dataset GET downloaded **{source["datasetBytesThisAssignment"]:,} bytes, $0**. Across this assignment and the completed historical pilot: **2 dataset requests, {source["datasetBytesCumulativeWithPriorPilot"]:,} bytes, $0**. The previous allowance was not reset. This pinned asset’s one-call allowance is exhausted and reruns use cached bytes. Source-review documentation accounting is separate: seven retained metadata/document GETs (23,700 bytes), one HEAD probe, and browser response sizes not fully retained. No account, trial, provider key, vendor contact, sportsbook credits or spending.',
        '',
        f'Actual capture: **{source["acquiredAtUtc"]}**. Physical source SHA-256 `{source["original"]["sha256"]}`. The publisher file commit is April 14, 2025; it is not a per-game historical information-availability timestamp. [Source review and terms](SOURCE_REVIEW.md), [bounded acquisition receipt](acquisition.json). The later FiveThirtyEight download route currently returns HTML; the admitted archive was the usable newer alternative. No 2025–26 rows exist in this source.',
        '',
        '| Season | Frozen role | Real regular games | Eligible home/away targets | Neutral history only |',
        '|---|---|---:|---:|---:|',
    ]
    for row in decl['population']:
        lines.append(f'| {row["season"]} | {row["role"]} | {row["regularGames"]:,} | {row["orientedTargets"]:,} | {row["neutralRegularHistoryOnly"]} |')
    lines += [
        '',
        '**7,059 real regular-season games** were admitted. Of these, 6,952 have source home/away orientation; 968 initial-fit targets are unscored, leaving **5,984 distinct assessment games**. The 107 neutral regular-season games remain in score/Elo history with zero home advantage and are excluded from home/away targets. The COVID-era shortened seasons retain their actual source populations; no games are invented.',
        '',
        'The blank playoff field includes play-in games and NBA Cup finals. Primary NBA calendar cutoffs exclude play-ins/postseason before score access. The 2023-12-09 IND/LAL and 2024-12-17 MIL/OKC Cup finals provide **dates only** for rest/density; their scores are never interpreted or included in ratings, rolling scores or assessment. [Scope classification](scope-classification.json), [identity reconciliation](holdout/reconciliation.json).',
        '',
        'Every admitted game has exactly two reciprocal source rows and consistent mirrored scores. Constructed source keys use season/date/unordered team pair; they are not asserted official NBA game IDs. The 30 team codes remain stable across these six seasons. An identity-only overlap check agrees on 7,133 old explicit-home games after documented CHA→CHO and NOH→NOP franchise aliases. It did not reopen prior pilot outcomes or assessment.',
        '',
        'Roles and selection rules were frozen from metadata before numerical scores were parsed. All three stages retain pre-access executable hashes. Development uses expanding prior-season fits; Validation receives models fitted before its season; the final holdout receives four already frozen benchmark/finalist models. The old 2014–15 holdout remains an inspected pilot result and is never reused for tuning. [Declaration](declaration.json).',
        '',
        'This is **Category A: reconstructed historical development/assessment from finalized records acquired today**. Source publication vintages and original schedule/score revision availability are missing. Recorded dates establish ordering, not proof that the finalized facts were known then. B (certified historical information availability) and C (genuine future pregame capture) are not claimed. No historical publication clock is invented.',
        '',
        'The implemented reduced contract has **78 score/date-derived numeric features**, not the original 65 box-feature model. It reuses chronological Elo, shrunk prior/current scoring and allowance, support, regular-season gaps and calendar density, adding earlier margin/total moments and variability. Last 20 earlier games and 10 pseudo-games of prior shrinkage are fixed. All target/same-day/later results are excluded; source Elo/pre/post ratings and probabilities are ignored. Possessions, shooting efficiency, rebounds, turnovers, injuries, players and odds are not fabricated.',
        '',
        'Regular-season games supply score/rating histories. Cup dates augment only rest/density. Postseason/preseason dates do not enter these gap features, so they are **gaps since admitted regular-season/context games, not certified all-competition rest**. This distinction is material to the first Ridge fold’s numerical limitation below.',
        '',
        '| Assessment season | N | League log loss / Brier | Elo log loss / Brier | League margin / total MAE | Elo margin / total MAE |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for year in range(2021,2026):
        a,b=by[year,'league'],by[year,'elo']
        lines.append(f'| {year-1}–{str(year)[2:]} | {a["games"]:,} | {a["log_loss"]:.5f} / {a["binary_brier"]:.5f} | {b["log_loss"]:.5f} / {b["binary_brier"]:.5f} | {a["margin_mae"]:.3f} / {a["total_mae"]:.3f} | {b["margin_mae"]:.3f} / {b["total_mae"]:.3f} |')
    lines += [
        '',
        'Binary NBA Brier is `(pHomeWin − I(home win))²`. Away probability is `1 − pHomeWin`, final tie probability 0. Elo beats league winner log loss and Brier in every assessed season. **Every Ridge/HGB point arm keeps exactly the same Elo winner probability and winner picks. Their identical winner scores are by construction and do not demonstrate a winner-probability improvement from the point models.** No distribution-based winner link or calibration was added.',
        '',
        'Development compared only Ridge alpha 10/100 and HGB L2 10/50 with the existing fixed settings. Imputation/scaling stay within each earlier-season training fold; HGB has no random validation split or early stopping. Development selected alpha 100 and L2=50 within their families. Validation selects by mean team-score MSE, requiring at least 1% improvement and at most 2% degradation in either margin or total MAE; near-equal qualifying families prefer Ridge. This proper point-mean gate is separately identified; the original full joint-energy gate remains unassessed.',
        '',
        '| Season | Elo margin / total MAE | Ridge α100 margin / total MAE | HGB L2=50 margin / total MAE | Elo / Ridge / HGB team-score MSE |',
        '|---|---:|---:|---:|---:|',
    ]
    for year in range(2021,2026):
        e,r,h=[by[year,name] for name in ('elo','ridge_a100','hgb_l2_50')]
        lines.append(f'| {year-1}–{str(year)[2:]} | {e["margin_mae"]:.3f} / {e["total_mae"]:.3f} | {r["margin_mae"]:.3f} / {r["total_mae"]:.3f} | {h["margin_mae"]:.3f} / {h["total_mae"]:.3f} | {e["team_score_mse"]:.3f} / {r["team_score_mse"]:.3f} / {h["team_score_mse"]:.3f} |')
    lines += [
        '',
        'Team-score MSE is `mean((home_error² + away_error²)/2)`, equivalent to `mean((margin_error² + total_error²)/4)`. MAEs are points. All candidate rows stay in their original common cohorts, including poor predictions. Full alpha 10 / L2=10 results and home/away errors remain in the stage reports: [Development](development/assessment.json), [Validation](validation/assessment.json), [final holdout](holdout/assessment.json).',
        '',
        '| Holdout candidate minus Elo | Margin MAE Δ [95%] | Total MAE Δ [95%] | Team-score MSE Δ [95%] |',
        '|---|---:|---:|---:|',
    ]
    for name in ('ridge_a100','hgb_l2_50'):
        intervals=results['holdout']['pairedVersusElo'][name]['metrics']
        cells=[]
        for metric in ('margin_mae','total_mae','team_score_mse'):
            value=intervals[metric]
            cells.append(f'{value["difference"]:+.3f} [{value["interval95"][0]:+.3f}, {value["interval95"][1]:+.3f}]')
        lines.append('| '+name+' | '+' | '.join(cells)+' |')
    lines += [
        '',
        'Negative differences favor the candidate. Existing uncertainty uses 2,000 paired calendar-week block bootstrap replicates, seed 731201. Observed games are assessment units; neither source-vintage uncertainty nor current-era transportability is bounded by these intervals. No simulation sampling precision is being presented as predictive certainty.',
        '',
        '**Research baseline decision:** retain the Validation-selected **Ridge alpha 100 expected-score channel with chronological Elo win probabilities**, alongside the unrestricted Elo point benchmark. Ridge reduces Validation team-score MSE 13.6% and holdout MSE 9.5%; holdout total MAE improves 1.052 points and margin MAE 0.148 points. HGB improves totals less and has slightly worse margins. This is a measured recent point-score gain, not a new winner-model gain or a full distribution champion.',
        '',
        '**Material limitation:** pooled Development MSE for Ridge alpha 100 is 188.538 versus Elo 150.747. Its 2020–21 fit produced nine nonpositive team-score expectations, minimum −138.182. The first, LAC at LAL on 2020-12-22, follows 130/129-day admitted regular-season gaps versus training ranges 0–8 / 0–9; retained Ridge coefficients contribute −87.030/−25.377 HOME points relative to the training-mean feature vector. This demonstrates extreme linear extrapolation in that case, not an orientation/scaler mismatch. All nine predictions remain unchanged in scoring. The alpha 10 variant had twelve nonpositive expectations in that same initial assessment season. All later assessed seasons and all league/Elo/HGB forecasts had positive expectations; Ridge’s Validation range is 98.129–134.694 and holdout 97.762–127.334. This is evidence of poor first-fold/long-gap support, not justification to clip predictions, change thresholds after holdout or claim unrestricted early-season robustness. [Bounded numerical-risk receipt](ridge-development-numerical-risk.json).',
        '',
        'The first-fold risk is attached to the research artifact. Before any later Ridge shadow export, finite positive means and adequate feature/history support must be verified; any unsupported output must remain unavailable. A broader offseason/calendar-treatment correction would require a separately declared comparison on data beyond the already inspected seasons, not silent repair of these receipts. Coefficients in the fitted artifacts describe conditional associations, not causal basketball effects.',
        '',
        f'After the one-time holdout receipt was saved, the locked Ridge/Elo configuration was **refitted on 6,952 oriented games through 2025-04-13** under a separate identity. [Refit receipt](post-assessment-refit/receipt.json). Ridge artifact SHA-256 `{refit["models"]["ridge_a100"]["artifact"]["sha256"]}`; Elo reference artifact `{refit["models"]["elo"]["artifact"]["sha256"]}`. Refitting does not revise selection, historical predictions or their clocks.',
        '',
        'Genuine paired season-forward HOME/AWAY residuals are retained with each model/game in the prediction parquets. They are finalized-record Category-A residuals, not prospective draws. The existing joint simulator still lacks its required overtime-period evidence. It was not run or modified; no tied draws were dropped, overtime adjustment applied, joint-energy/CRPS/interval score computed or validated joint forecast claimed.',
        '',
        '**Exact remaining dependency for a genuine future forecast:** the selected export ends with the 2024–25 regular season. A permitted 2025–26 result update plus an actual upcoming NBA schedule/game identity and evidence captured before that game’s cutoff is still required to establish current histories. Historical reconstruction cannot substitute for those captures. A full joint-score package additionally needs the unchanged simulator’s overtime evidence; boxes are optional for this reduced point model but necessary for the separate possession/efficiency feature model. No current source request, schedule, AISP import or display confirmation is fabricated. No future forecast was published.',
        '',
        'Reproduce from the repository root; completed stage receipts are reused without new source requests or holdout assessment:',
        '',
        '```powershell',
        '.venv/Scripts/python.exe -B scripts/acquire_nba_gen1_recent.py',
        '.venv/Scripts/python.exe -B scripts/declare_nba_gen1_recent.py',
        '.venv/Scripts/python.exe -B scripts/run_nba_gen1_recent.py --stage development',
        '.venv/Scripts/python.exe -B scripts/run_nba_gen1_recent.py --stage validation',
        '.venv/Scripts/python.exe -B scripts/run_nba_gen1_recent.py --stage holdout',
        '.venv/Scripts/python.exe -B scripts/verify_nba_gen1_recent.py',
        '```',
        '',
        'A numerical reproduction in a separate output folder must copy the declaration pointer and its original immutable bindings, reuse the same source bytes and preserve the actual repeat clocks. It is a reproduction of an inspected assessment, not a new holdout. Partial-stage folders intentionally refuse silent overwrite.',
        '',
        '**Verification:** 28 focused software checks (17 source/features, 8 model/preprocessor, 3 selector) are separate from forecast evidence. Reloading 26 assessed artifacts reproduced all 31,012 stored model-game numerical rows exactly, including bad Development values. All probabilities reconcile, target/date exclusions and frozen stage ordering pass, and the two later refit artifacts are retained. Prior pilot/source attribution and the 8 inherited dirty files remain unchanged. [Verification receipt](verification.json).',
        '',
        'NBA remains research-only and unfunded. No MLB/NFL operations, existing model artifacts, accounts, policy, sportsbook credits, scheduler or Claude live-score UI was changed. No purchase, trial or vendor contact occurred.',
        '',
        'Attribution: NBA data archive published by Neil Paine, updated from FiveThirtyEight; retain [Neil Paine’s MIT notice](source-review/neil-paine-LICENSE.txt) and original FiveThirtyEight/Basketball-Reference attribution and CC BY4.0 notice. ASP Model Studio reconciles source rows, applies declared scope, reconstructs chronological features and fits independent research models. No publisher endorsement is implied.',
        '',
    ]
    target.write_text('\n'.join(lines),encoding='utf-8',newline='\n')
    print(json.dumps({'report':reference(target)},indent=2))


if __name__=='__main__':
    main()

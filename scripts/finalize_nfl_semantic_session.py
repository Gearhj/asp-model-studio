"""Assemble the delivered session report from completed, checksum-verified results.

No fitting, source scans or network requests. Mutable discovery files point at
the immutable inputs and addressed report; earlier addressed reports survive.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.sports_nfl_m1.research_benchmarks import immutable_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/nfl-semantic-session-v1"


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified(path, digest):
    if sha(path) != digest:
        raise ValueError(f"Result checksum mismatch: {path}")
    return read(path)


def link(path, label=None):
    resolved = Path(path).resolve().as_posix()
    return f"[{label or Path(path).name}](<{resolved}>)"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|", *("| " + " | ".join(map(str, row)) + " |" for row in rows)])


def main():
    ptr = read(ROOT / "outputs/nfl-semantic-lab-v1/CURRENT.json")
    result = verified(ptr["resultPath"], ptr["resultSha256"])
    report_ptr = read(ROOT / "outputs/nfl-semantic-lab-v1/reporting/CURRENT.json")
    reporting = verified(report_ptr["supplementPath"], report_ptr["supplementSha256"])
    if reporting["parentResultSha256"] != ptr["resultSha256"]:
        raise ValueError("Reporting supplement parent mismatch")
    bench_ptr = read(ROOT / "outputs/nfl-research-benchmarks-v1/current.json")
    bench = verified(bench_ptr["path"], bench_ptr["sha256"])
    sim_ptr = read(ROOT / "outputs/nfl-labs-simulation-v1/CURRENT.json")
    drive = verified(sim_ptr["driveHandoffPath"], sim_ptr["driveHandoffSha256"])
    drive_fit = verified(drive["fitReceipt"]["path"], drive["fitReceipt"]["sha256"])
    mlb_ptr = read(ROOT / "outputs/mlb-v18-cold-start-reconciliation-v1/CURRENT.json")
    verified(mlb_ptr["path"], mlb_ptr["sha256"])
    policy_path = ROOT / "outputs/nfl-semantic-lab-v1/policy-supplements/sha256/ad3f1e57106f58b76b835cb7cd3912c26d357e05fd85f9495dbccd9367edd6d6/feature-treatment-policy.json"
    policy = read(policy_path)
    models = result["results"]
    all_metrics = table(
        ["Pipeline", "Raw LL", "Calibrated LL", "Raw Brier (sum 3)", "Margin MAE", "Total MAE", "Weeks 1–4 raw / calibrated LL", "Weeks 1–2 raw / calibrated LL"],
        [[r["pipelineId"], f'{r["metrics"]["raw"]["multiclassLogLoss"]:.6f}', f'{r["metrics"]["calibrated"]["multiclassLogLoss"]:.6f}', f'{r["metrics"]["raw"]["multiclassBrier"]:.6f}', f'{r["metrics"]["raw"]["marginMae"]:.4f}', f'{r["metrics"]["raw"]["totalMae"]:.4f}',
          " / ".join(f'{r["subgroups"]["WEEKS_1_4"][p]["multiclassLogLoss"]:.6f}' for p in ("raw", "calibrated")),
          " / ".join(f'{r["subgroups"]["WEEKS_1_2"][p]["multiclassLogLoss"]:.6f}' for p in ("raw", "calibrated"))] for r in models])
    paired = table(["Pipeline", "Calibrated minus M1", "95% season/week interval", "Weeks 1–4 raw minus M1", "95% interval"],
        [[name, f'{p["calibrated"]["candidateMinusM1LogLoss"]:+.6f}', str([round(x, 6) for x in p["calibrated"]["clusterBootstrap95Ci"]]), f'{p["weeks1to4"]["candidateMinusM1LogLoss"]:+.6f}', str([round(x, 6) for x in p["weeks1to4"]["clusterBootstrap95Ci"]])] for name,p in result["pairedAgainstM1"].items()])
    market_rows = bench["historicalMarketReference"]
    market = table(["Model", "Matched decisive games", "Conditional two-way LL", "Difference versus market", "95% season/week interval"],
        [[r["modelId"], r["events"], f'{r["twoWayConditionalLogLoss"]:.6f}', f'{r["pairedLogLossMinusMarket"]["pairedMean"]:+.6f}', str([round(x, 6) for x in r["pairedLogLossMinusMarket"]["interval95"]])] for r in market_rows if "modelId" in r])
    artifacts = table(["Fitted fixed recipe", "Expanded columns", "SHA-256", "Artifact"],
        [[f["pipelineId"], f["expandedColumns"], f["sha256"], link(f["path"])] for f in result["fittedArtifacts"]])
    root_attempts = ROOT / "outputs/nfl-semantic-lab-v1/runs"
    accounting = []
    for logfile in sorted(root_attempts.glob("*/fit-accounting.jsonl")):
        events = [json.loads(line) for line in logfile.read_text().splitlines()]
        accounting.append({"attempt": logfile.parent.name, **{key: sum(e.get("event") == key for e in events) for key in ("ESTIMATOR_FIT_START", "ESTIMATOR_FIT_COMPLETE", "OUTER_FOLD_COMPLETE", "DYNAMIC_PARAMETER_FIT", "CALIBRATOR_FIT_START")}})
    account_table = table(["Attempt", "Estimator starts", "Estimator completions", "Completed outer folds", "Dynamic fits", "Logged final calibrator starts"], [[a["attempt"], a["ESTIMATOR_FIT_START"], a["ESTIMATOR_FIT_COMPLETE"], a["OUTER_FOLD_COMPLETE"], a["DYNAMIC_PARAMETER_FIT"], a["CALIBRATOR_FIT_START"]] for a in accounting])
    report = f"""# NFL semantic laboratory and football simulation delivery

Implemented semantic NFL preprocessing, completed six targeted XGBoost/HGB designs plus a dynamic score baseline and two bounded tuning studies, persisted reloadable finalist systems, added matched model/market benchmarks, published actual M1 score-distribution supplements and a distinct fitted drive research engine, and integrated old/new evidence in Model Studio. M1 is retained. All new evidence is research-only and unpromoted.

## What baseball's cold-start state actually was

The 240-feature specification contains 64 no-history entries. Accepted V18 selects 218 source fields plus 55 prior outputs, giving 273 pre-categorical inputs. All 21 prior treatments execute in the five verified preprocessing artifacts. Ordinary prior median/mode fallback was **zero recorded**. The 56 governed WHIP population-prior fallbacks are valid and distinct from the held population.

The held 56 Development PAs (51 OOF) have observed zero exposure, prior_missing=false, undefined raw rates and zero companion event counts—not missing component observations. V1 does not authorize that zero-opportunity prior state; the hold remains unchanged. Saved either-player cold-start PAs: 83,174, log loss 1.481061; complementary flag-negative PAs: 418,365, log loss 1.473303. These are overlapping observational subgroups, not proof of treatment uplift. V14's older gaps are not V18's current status. See {link(mlb_ptr['reportPath'], 'full saved-evidence reconciliation')} and {link(mlb_ptr['path'], 'row-level reconciliation JSON')}.

## Exact NFL targets and distributions

One completed game is one observation. Source final home_score and away_score become float64 home_points and away_points, including overtime. M1 fits two independent squared-error score regressors; margin and total are derived, not its fitted targets. Margin = home minus away; total = home plus away. AWAY_WIN/TIE/HOME_WIN probabilities come from the joint distribution.

The legacy law adds paired, centered training-period residuals to score means, clips at zero and stochastically integerizes. Its dependence and actual persisted score masses are preserved. This law is not a sequential football scoring engine and can assign implausible low scores. Regressor means and Monte Carlo expectations need not equal after clipping. Separate probability calibration does not imply a calibrated joint simulation. Postseason scores include overtime with explicit game_type; preseason is excluded from this Development experiment. See {link(OUT / 'NFL_TARGET_CONTRACT_V1.json', 'executable target contract')}.

Operational M1 includes 2025 training (cutoff 2026-02-08); it is not the unbiased historical comparator. All comparisons here use compatible saved fold-refitted recipe OOF. No sealed 2025 source rows were opened for this session.

## Implemented feature treatment

The catalog has {len(policy['rows'])} entries: 197 registered M1 inputs, 12 added lagged-personnel inputs, and 91 proposed entries. Of the registered inputs, 196 have executable decisions; roof is excluded because historical open/closed status lacks proven pregame availability. C1 uses 196 active source inputs; C2 and C3 use 208. These counts are distinct from expanded columns below. There is no generic-median branch in new recipes.

C1 reconstructs strictly prior-date team histories, preserving zero completed games separately from undefined opportunity rates. Continuous signed EPA/game-average rates use normal-normal approximations with valid-game counts, four prior-equivalent games, eight-game half-life and 0.65 offseason retention. Rates are not falsely called binomial counts. C2 adds prior-game passer mixtures weighted by previous team usage, player EPA/count history, uncertainty and team-change history; these are not assertions of the target game's known starter. C3 applies training-only simple exposure/experience peer pooling. Team-relative QB adjustment limits double counting of embedded passing strength. Native missingness remains explicit for unavailable rates; the two validation examples are known-zero red-zone opportunity, not measured rates of zero.

The league center uses the most recent three training seasons as an era adjustment. Both teams' offense/defense inputs inform the matchup learner, but a separate opponent-normalized historical EPA or strength-of-schedule estimator was not implemented. The C1 package also includes roof exclusion and extra uncertainty/state columns, so its effect is not a causally isolated prior correction.

Draft, actual rookie/backup/start-change, injury and contemporaneous weather inputs remain unsupported where their pregame authority is absent. Current roster availability does not repair injury absence. Historical release-vintage uncertainty remains documented. Proposed source rows are not falsely counted as model inputs.

{artifacts}

Workbook: {link(OUT / 'NFL_Feature_Treatment_Specification.xlsx')}. Machine policy: {link(policy_path)} (SHA-256 `{sha(policy_path)}`). Editable reviewer decisions are separate from executable/fitted authority. Source coverage, early-season missingness, units, join keys, prior assumptions, state semantics and implementation locations are recorded per feature.

## Did early-season forecasts improve?

**No consistent early-season improvement was established.** C2 and C3 XGBoost calibrated Weeks 1–4 loss is worse than M1 by +0.005565 and +0.008175. C1 XGBoost is nearly unchanged at 0.693572 versus M1 0.693660. Full-season calibrated C3 improves its point estimate to 0.661772 versus 0.665318, but its paired interval includes zero. The best tuned C3 point estimate is 0.661452, difference -0.003866, interval [-0.012094, +0.004296]; it also does not establish advancement. M1 remains retained.

These are exploratory Development comparisons on 1,408 identical validation games across seasons 2020–2024, drawn from 6,991 Development games (1999–2024). Weeks 1–4 contain 319 games; Weeks 1–2 contain 160; 80 games involve a zero-current-season-history team. The lagged-passer low-exposure proxy has only eight games and is descriptive, not an identified rookie/backup effect. Same-date outcomes never enter another target-date forecast. Priors and model fitting are fold-local; the first calibration year remains raw because no earlier OOF exists, and later calibration uses only earlier seasons.

{all_metrics}

Lower log loss is better. Brier is the sum of squared errors across all three classes. MAE units are points. New candidates use 2,000 paired-residual draws per evaluation event. Full and early-season score-interval coverage, calibration error, subgroup sizes and per-fold diagnostics are in {link(ptr['resultPath'], 'complete model results')}. Raw distribution 90% intervals and separately calibrated probability metrics must not be conflated.

{paired}

Intervals resample season/week blocks and are exploratory after model/design selection. A favorable point estimate alone does not establish improvement. C2-minus-C1 and C3-minus-C2 paired effects are recorded separately in results, with common candidate simulation draws. The older baseline random streams differ. No whole-package result is attributed solely to QB information, pooling or calibration. The two tuning studies each use two predeclared configurations within chronological outer-training periods; they are not a repeated broad sweep.

{link(report_ptr['supplementPath'], 'Reporting supplement')} adds raw/calibrated early-season paired intervals, five-block low-exposure instability labels, expanded-column counts and actual branch counts: 3,520 prior-only, 244,286 blended, two unresolved-native rate cells per complete candidate validation ledger. The eight-game personnel proxy is descriptive and unstable. Its 44 completed chronological calibration fits are counted from executed fold receipts, not invented fit-start telemetry.

## Matched model and sportsbook evidence

Class A: saved fold-refitted M1/HGB, the transparent dynamic baseline and every new candidate are evaluated on the same 1,408 games. The pinned FiveThirtyEight historical Elo reconstruction matches 269 games in 2020, of which 268 are decisive. Exact as-published timestamps are unverified. It is a historical model reference, not a current sportsbook comparison. nfelo is not imported because permitted historical prediction vintages and repository licensing remain unresolved.

Class B: all 1,408 games match historical moneylines/spreads/totals. Four realized ties are excluded only from the two-way tie-void analytical moneyline comparison, leaving 1,404. Proportional no-vig removes bookmaker margin; model home probability is pHome/(pHome+pAway), leaving the original tie forecast untouched. Market two-way log loss is {market_rows[0]['twoWayLogLoss']:.6f}. Positive nflverse spread means expected home winning margin; totals use final scores including OT. There are 32 spread pushes and 18 total pushes. Bookmaker identity, quote time and book-specific settlement terms are unverified, so this is **not an executable backtest or wagering edge**.

{market}

Class C: zero of 1,408 events has an authorized timestamp-matched quote. The implemented join requires canonical event, bookmaker, original timezone-aware observedAtUtc, both prices, settlement contract, frozen forecast cutoff and kickoff. It excludes quotes after cutoff and non-pregame forecasts; it selects the latest eligible quote per event/book. Missing coverage and the exact bounded export request appear in {link(bench_ptr['path'], 'benchmark scoreboard')}. Do not purchase historical access. Already entitled quotes or future permitted pre-cutoff collection are needed for this evidence class.

## Actual simulations delivered to Claude

The separate immutable NFL_LABS_CONTRACT_V1 interface preserves old exact three-file forecast bundles. Sixteen M1 supplements recover the exact empirical 10,000-draw joint score distributions, not invented sequences; original generation order is not claimed. Home/away/tie probabilities and score summaries reconcile exactly. No M1 drive paths are fabricated.

Drive engine `{drive['engineId']}` is a distinct uncalibrated research model. It fits multinomial drive outcomes using field position, time, score differential, possession side and prior offense/defense strength, then samples paired empirical progression/duration conditional on outcome and starting field band. Validation: {drive_fit['evaluation']['validationDriveCount']:,} drives from {drive_fit['evaluation']['validationGameCount']} games in 2024; conditional drive log loss {drive_fit['evaluation']['conditionalDriveLogLoss']:.6f}, unconditional {drive_fit['evaluation']['unconditionalDriveLogLoss']:.6f}. This is observed-drive-state validation, **not pregame game-forecast calibration**.

Final fitting uses 42,205 drives from seasons 2018–2024; the cutoff includes the 2024 postseason ending 2025-02-09, not protected season 2025. There are {drive['artifactCount']} current drive/scenario supplements across {drive['baseEventCount']} events, each with 1,000 completed simulations and six distinct persisted representative games. BASE and a 0.95 drive-duration sensitivity are separately identified. This pace sensitivity is not a claim of a known tactical intervention. No QB/player/route/tackle identities or within-drive physical paths are invented.

The V2 correction uses only the actual starting kickoff to establish touchback evidence (247 corrected flags; 8 ambiguous and 94 unknown kickoff records excluded from that bank). V1 objects/receipts are preserved. Regulation ties, overtime entry and final ties are separate. Current regular-season overtime includes the 10-minute cap and both-possession opportunity subject to time; postseason continuation is explicitly unsupported. Current kickoff uses the standard 35-yard touchback assumption, with the landing-zone exception, onside kicks and detailed penalty/timeout strategy unsupported. Source/rule assumptions are explicit.

Drive team context remains 2024 history discounted across two offseasons. These are current-created **stale-input mechanics simulations**, not freshly informed 2026 QB/injury forecasts. Metadata successors use the actual registered source retrieval cutoff 2026-08-29T13:34:33.063899+00:00, with historicalEvidenceThroughDate=2025-02-09 separately labeled GAME_DATE precision. They preserve every numerical V2 forecast identity, population and path; retrieval time does not imply fresh team evidence. New semantic candidate production has zero forecasts and 16 explicit skips: no permitted 2025 initialization/current semantic-state authority. Caller-supplied authorization booleans are not accepted as authority. The frozen publisher is exercised on a clearly labeled historical deterministic fixture only, with zero mismatch.

Coordination contract: `C:\\Users\\james\\asp-model-exchange\\contracts\\NFL_LABS_CONTRACT_V1.json`.
Discovery pointer: `C:\\Users\\james\\asp-model-exchange\\nfl-labs-simulation-supplements\\current.json`.
Drive handoff: {link(sim_ptr['driveHandoffPath'])}; SHA-256 `{sim_ptr['driveHandoffSha256']}`.

**Exact Claude instruction:** Read NFL_LABS_CONTRACT_V1.json and the separate nfl-labs-simulation-supplements/current.json. Verify each immutable artifact and manifest checksum/byte count. Import the 16 unchanged M1 score-distribution supplements and 32 current V2 drive/scenario supplements. Keep M1 scores separate from the independent drive engine and BASE separate from pace sensitivity. Display stale source dates and unsupported scenarios. Do not execute models, modify old three-file bundles, promote a track or grant wagering authority.

## Runtime, preservation and verification

{account_table}

These are actual receipts, not scheduled fit slots. Each score system has separate home/away estimators plus training-only residual-calibration fits. The first attempt stopped at Windows joblib CreateFile WinError 5; its receipts and completed work remain intact. The supported Windows recovery used a new code-addressed identity after correcting undefined-opportunity handling. Final calibrator starts in the table are explicitly logged; chronological OOF calibration fits are also performed and separately accounted in the session verification receipt. Dynamic parameter estimation is not called an XGBoost/HGB estimator fit. Completed main run elapsed time: {result['elapsedSeconds']:.1f} seconds. Drive fitting has two fits per version, four total including preserved V1; no broad grid.

Focused verification covers prior-date availability, native undefined-rate handling, frozen reload, original score reproduction, drive accounting/kickoff clocks, import checksums, timestamp-quote joins and project-authorized UI artifact links. Fourteen distinct focused tests and one relevant TypeScript/Vite build passed. No entire repository suite was run. {link(OUT / 'SESSION_VERIFICATION.json', 'Session verification receipt')} records actual counts and final browser evidence. The signed-in browser showed 35 result rows (24 prior + nine new + two reused baselines) and 228 verified artifact links. The representative artifact endpoint returned HTTP 200, but direct JSON navigation was blocked by the in-app client (net::ERR_BLOCKED_BY_CLIENT); its download/view completion is not claimed. Local artifact links remain supplied. No AISP writes, paid provider requests, official model/policy/position changes or sealed OOT reads occurred.

## Visible results and next action

[Model Studio NFL laboratory](http://127.0.0.1:5274/workflows/nfl?projectId=sports-project-nfl-overnight-model-lab-v1#nfl-laboratory) contains the previous 22 screens plus two tuning results and the new semantic results, definitions, raw/calibrated comparison chart, early-season filtering and verified artifact downloads. Gen 1/V2.1 and V18 remain separate and unchanged.

Next: Claude can import the simulation supplements now. Before a genuinely current semantic candidate forecast, obtain a separately authorized, checksummed operational prior/current-state packet that does not reopen sealed evaluation data. Before any market-edge claim, obtain entitled timestamped prices with bookmaker/settlement metadata and freeze the evaluation rule. The present Development evidence does not promote a challenger.

## Primary method/source references

- [nflverse release timing](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html): injury interruption after 2024, and differing release timing across source families.
- [nflverse schedule dictionary](https://nflreadr.nflverse.com/articles/dictionary_schedules.html): target fields, schedule time and spread signs.
- [FiveThirtyEight historical Elo implementation](https://github.com/fivethirtyeight/nfl-elo-game): pinned historical reconstruction, not timestamped prospective predictions.
- [PFF Bayesian QB discussion](https://www.pff.com/news/nfl-2020-quarterback-rankings): conceptual prior/uncertainty reference; no proprietary grades ingested.
- [nfelo QB reference](https://github.com/greerreNFL/nfeloqb) and [market-informed nfelo ratings](https://www.nfeloapp.com/nfl-power-ratings/): reviewed, not unlicensed copied predictors.
- [Historical odds access](https://the-odds-api.com/historical-odds-data/): paid history not requested.
- [Official NFL playing rules]({drive_fit['rules']['sourceUrl']}): regulation and overtime rules used by the independent research engine, with unsupported exceptions disclosed above.
- [Sportradar Custom Bet](https://docs.sportradar.com/uof/custombet-cb/intro): simulation-based dependence/pricing concept, not a disclosed reproducible cold-start model.
"""
    report_bytes = report.encode("utf-8")
    report_sha = hashlib.sha256(report_bytes).hexdigest()
    report_path = OUT / "sha256" / report_sha / "REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        if report_path.read_bytes() != report_bytes:
            raise ValueError("Report collision")
    else:
        with report_path.open("xb") as stream:
            stream.write(report_bytes)
    artifact_paths = [report_path, OUT / "NFL_Feature_Treatment_Specification.xlsx", OUT / "NFL_TARGET_CONTRACT_V1.json", OUT / "SESSION_VERIFICATION.json", policy_path, Path(ptr["resultPath"]), Path(report_ptr["supplementPath"]), Path(bench_ptr["path"]), Path(mlb_ptr["path"]), Path(sim_ptr["driveHandoffPath"])]
    manifest = {"contract": "NFL_SEMANTIC_SESSION_DELIVERY_V1", "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False, "executionAllowedInAISP": False, "modelRetained": "NFL_M1_XGBOOST", "sealedFinalOotAccessed": False, "report": str(report_path), "files": [{"path": str(p.resolve()), "sha256": sha(p), "byteCount": p.stat().st_size} for p in artifact_paths], "attemptAccounting": accounting}
    manifest_path, digest = immutable_json(OUT, "delivery-manifest.json", manifest)
    (OUT / "CURRENT.json").write_text(json.dumps({"reportPath": str(report_path), "reportSha256": report_sha, "manifestPath": str(manifest_path), "manifestSha256": digest}, indent=2))
    print(json.dumps({"reportPath": str(report_path), "reportSha256": report_sha, "manifestPath": str(manifest_path), "manifestSha256": digest}, indent=2))


if __name__ == "__main__":
    main()

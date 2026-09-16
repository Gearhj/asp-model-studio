# Phase 7B2 Gold V1 feature and fixed-model experiment

## A. Starting Git state

- Repository: `C:\Users\james\asp-model-studio`
- Source branch/HEAD: `phase7b1-full-corpus-retrosheet-completion` at `9b3e513cefff7d17288f0f90536a505808fce4de`
- Working branch: `phase7b2-gold-v1-modeling`
- Main remained `924db29511f93909f9d785855bfa056775443690`.
- Initial worktree contained only the preserved untracked Codex report.
- Silver authority: `C:\Users\james\asp-data-staging\mlb-silver-v1\silver-table-registry.json`, with the 13 Phase 7B1 current logical registrations unchanged.
- No remote was changed and nothing was pushed.

## B. Silver-to-Gold connection

The bridge is outcome-blind and deterministic. It resolves exact Retrosheet game authority to canonical Silver games, exact Chadwick UUID authority to canonical Silver players, then uses the source-supported key `(canonicalGameId, batterCanonicalPlayerId, pitcherCanonicalPlayerId, inning, topBottom)`. A within-key source occurrence is used only when target and Silver group counts are equal. It never uses `outcome`, `paEvent`, or another result field to force a match.

The 550 rows requiring occurrence resolution were uniquely paired after the equal-count rule. Post-ordinal ambiguity, duplicate target authority, duplicate Silver authority, and target/Silver date mismatches were all zero.

## C. PA bridge counts

| Population | Governed target | Exact match | Excluded | Occurrence-resolved | Ambiguous |
|---|---:|---:|---:|---:|---:|
| Development, 2021–2023 | 547,835 | 536,102 | 11,733 | 418 | 0 |
| Validation, 2024 | 182,449 | 180,711 | 1,738 | 132 | 0 |
| Total | 730,284 | 716,813 | 13,471 | 550 | 0 |

Per season, matched/excluded rows are 178,522/3,230 (2021), 175,508/6,471 (2022), 182,072/2,032 (2023), and 180,711/1,738 (2024). Exclusions are fully reconciled: 13,337 `KEY_GROUP_COUNT_MISMATCH` rows and 134 `GAME_IDENTITY_UNMAPPED` rows. Unresolved batter and pitcher identities are zero. The exclusion rate is 1.84462483088771% overall and 0.952594971745529% in validation.

## D. Gold V1 feature inventory

`gold_mlb_pa_v1` contains 716,813 rows and exactly 48 ordered features:

- 22 existing governed Gen3 base features, byte-preserved as the prefix;
- 8 batter-history features using all-prior and last-100-PA state;
- 12 pitcher-history features using all-prior and last-250-BF state;
- 6 pre-PA handedness and platoon features.

Phase 7B1 Silver V1 does not carry governed exit velocity, launch angle, or barrel evidence. Exit-velocity, hard-hit, and barrel features were therefore omitted rather than inferred or zero-filled. The full per-feature source, calculation, window, cutoff, and missing-value contract is in `docs/phase7b2_gold_feature_spec.json`.

## E. Point-in-time evidence

Historical state uses the strict rule `source.gameDate < target.game_date`. The target PA, every same-day PA (including doubleheaders), later PAs, and later games are excluded. Current-PA handedness is pre-event context only. The focused future-row mutation test demonstrated bit-identical earlier features when the current day and future rows were changed. A separate deterministic shuffle/repeat check produced identical feature values.

The input resolver accepts Silver history only from 2019–2024 and modeling targets only from 2021–2024. Requests for 2025/2026 are rejected before a data opener is called. No 2025 or 2026 object was resolved or opened in this run.

## F. Gold rows and feature quality

Gold rows by season are 178,522 (2021), 175,508 (2022), 182,072 (2023), and 180,711 (2024). Both canonical PA keys have zero duplicates.

- Batter prior-history coverage: 99.76479221219481%; unseen-batter rows: 1,686; last-100 insufficient rate: 6.525551294410119%.
- Pitcher prior-history coverage: 98.97699958008574%; unseen-pitcher rows: 7,333; last-250 insufficient rate: 20.26246733806446%.
- Rows with both batter and pitcher unseen: 23.
- Advanced-feature missingness is zero for counts/flags/handedness indicators. Rate missingness is 0.235–0.240% for batter rates and 1.023–1.038% for pitcher rates/velocity, explicitly represented and imputed from the development fold only.
- Median prior history is 1,001 PA for batters and 716 BF for pitchers. Median bounded windows are the full 100 PA and 250 BF.

## G. Models executed

The fixed suite fit sequentially on 536,102 matched 2021–2023 rows and scored 180,711 matched 2024 rows. Completed models were the development-frequency null, fixed base Logistic, fixed Gold Logistic, fixed HistGradientBoosting, fixed Extra Trees, the two predefined partial-history Logistic ablations, and the simple unweighted ensemble. XGBoost was already installed and was attempted with the fixed configuration; its returned float probabilities failed the repository's strict row-sum validator, so it was recorded as failed and excluded from the ensemble. No weights were optimized on 2024.

## H. 2024 model leaderboard

| Rank | Model | Features | Log loss | Brier | ECE | Accuracy | Macro-F1 | Fit s | Score s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | Gold Logistic | 48 | 1.4778808498644482 | 0.7040277515790683 | 0.001438315874177647 | 0.4534035006170073 | 0.09332003157919234 | 183.13831740012392 | 0.4126940998248756 |
| 2 | Unweighted ensemble | 48 | 1.4779544518091083 | 0.7036986090480917 | 0.006579158912545163 | 0.45380192683345233 | 0.08665558815142652 | 0 | 0.051317399833351374 |
| 3 | Base + pitcher Logistic | 34 | 1.4803905170806546 | 0.705140677785472 | 0.002388424648007112 | 0.45281139498979034 | 0.08880085897106783 | 189.1409519999288 | 0.3407405000180006 |
| 4 | Base + batter Logistic | 30 | 1.4808850441108863 | 0.7051447651407096 | 0.0022258367180264514 | 0.4528445971744941 | 0.09045073235175372 | 162.92039049975574 | 0.3160329000093043 |
| 5 | Extra Trees | 48 | 1.4820494065565262 | 0.7054753533055066 | 0.008530926011246017 | 0.4527449906203828 | 0.07820209303168701 | 284.1046179002151 | 5.5416635000146925 |
| 6 | Base Logistic | 22 | 1.4826901221878819 | 0.7061079942040106 | 0.003196593576219006 | 0.45240743507589465 | 0.086455864928205 | 134.6106296000071 | 0.25458050007000566 |
| 7 | HistGradientBoosting | 48 | 1.491692010291781 | 0.7073981710477766 | 0.01006763946190353 | 0.45147224020673893 | 0.09765949170737732 | 121.92973719956353 | 14.58092310000211 |
| 8 | Null | 0 | 1.500007666747898 | 0.7125111667964451 | 0.006053442362354389 | 0.4526177155790184 | 0.07789690823758876 | 0.46125909965485334 | 0.02427319996058941 |
| — | XGBoost | 48 | failed probability validation | — | — | — | — | 407.3030194998719 | 17.448706700000912 |

All successful models produced finite `180711 × 8` probabilities in the exact class order and passed the repository probability validator. Logistic fits emitted only the recorded SciPy L-BFGS deprecation warning.

## I. Four predefined feature-family comparisons

| Configuration | Features | 2024 log loss | Improvement vs matched base |
|---|---:|---:|---:|
| Base | 22 | 1.4826901221878819 | 0 |
| Base + batter history | 30 | 1.4808850441108863 | 0.001805078076995592 |
| Base + pitcher history | 34 | 1.4803905170806546 | 0.002299605107227265 |
| Full Gold V1 | 48 | 1.4778808498644482 | 0.004809272323433644 |

Both history families add signal; pitcher history is stronger alone, and the full combination plus matchup context is strongest.

## J. Best result versus the accepted reference

Gold Logistic is best by the primary metric. Against the accepted validation log loss `1.4827332596445002`, its `1.4778808498644482` is an absolute improvement of `0.0048524097800519694`, or `0.3272611407675162%`. The experiment therefore answers the Phase 7B2 question **yes**.

This is an experiment, not a promotion. The historical accepted reference used all 182,449 validation rows, whereas the connection-valid Gold comparison uses 180,711 rows after 1,738 reason-coded exclusions; that population difference must remain visible in any later decision.

## K. Failures and limitations

- XGBoost fit and scored but failed strict probability row-sum validation; it was excluded rather than renormalized.
- Current Silver V1 cannot support honest exit-velocity, hard-hit, or barrel features.
- 13,471 governed targets (1.84462483088771%) lack an exact one-to-one Silver PA bridge and remain in the external exclusion ledger.
- HistGradientBoosting under the fixed configuration did not beat the accepted reference.
- The best improvement is modest and has not been tested on a new future validation season.

## L. Artifacts and changed files

- Gold dataset: `C:\Users\james\asp-data-staging\mlb-gold-v1\objects\sha256\56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0`
- Gold dataset ID: `gold-table:gold_mlb_pa_v1:sha256:56162deb2473e173685012775fcedecca7f88ba59dffacbb04e49c918371a3f0`
- Experiment: `C:\Users\james\asp-data-staging\mlb-gold-v1\experiments\sha256\de7966fba2e6dfd1cde466eadb2b8cd6d737695fd75d89d5fce0938e8060538f`
- Full external leaderboard SHA-256: `16155af2889104535ed975d196525e2103795510ca106ab432a9e75aad665ea3`
- Gold build/result evidence SHA-256: `59c9428d2fc4ecbb408f83b387f6ef8910cfb5f690c135da14298ac39a51f004`
- Gold implementation identity SHA-256: `3f6d74d6de6aad6f68f54a969f9263db3ae53c3269d385e4cb349d9e15b553c1`

Repository changes are confined to `server/sports_gold/`, the approved `scripts/phase7b_research.py` entrypoint, eight focused tests under `tests/phase7b2/`, and the four Phase 7B2 documentation outputs. Gold Parquet, exclusions, model binaries, and full predictions/metrics remain outside Git.

## M. Git and safety state

No Bronze file was written, normalized, or reopened by the Gold pipeline. Silver was read through its current verified registrations and remains quarantined. Only seasons 2019–2024 were opened for historical/modeling work; 2025 remained sealed and 2026 untouched. No model registry was created or changed, no model was promoted, no champion changed, no remote was changed, and nothing was pushed.

Focused command result: `8 passed in 4.54s`. Gold build elapsed 1,118.0517948996276 seconds. Fixed experiment elapsed 1,541.3489733999595 seconds.

Exact definitive commands:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests\phase7b2 -q -rs -p no:cacheprovider --basetemp C:\Users\james\AppData\Local\Temp\asp-phase7b2-focused-20260825-final\basetemp
.\.venv\Scripts\python.exe -B -m scripts.phase7b_research --build-gold-v1 --silver-root C:\Users\james\asp-data-staging\mlb-silver-v1 --gold-root C:\Users\james\asp-data-staging\mlb-gold-v1
.\.venv\Scripts\python.exe -B -m scripts.phase7b_research --run-gold-v1 --gold-root C:\Users\james\asp-data-staging\mlb-gold-v1
```

Two earlier invocations of the same build command were manually interrupted before the Gold root existed so the final connection and quality evidence could be corrected; neither published a partial object.

## N. Next recommended modeling action

Keep Gold Logistic as a research challenger only. The next modeling action should be to understand and, where source authority permits, reduce the 13,471 exact-bridge exclusions, then evaluate the same frozen Gold specification on a genuinely future governed validation season before considering any promotion.

No model was promoted by Phase 7B2.

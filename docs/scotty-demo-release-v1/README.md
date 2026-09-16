# Scotty demo release — September 19–20, 2026

Additive producer release from source base `8067db9f338fde006e2f95ed92646457ab567f69`,
on `codex/scotty-demo-model-readiness-v1`. It declares retained configurations;
it does not select, refit, promote or deploy a model. Original runtime,
source-only development and AISP remain separate. See `PUBLICATION.json`
for the final immutable release address and physical hashes.

## Retained configurations

| Sport | Configuration and authority | Numerical channels and limitations |
|---|---|---|
| MLB | `MLB_V18_HGB_PA`, conditional operational controlling final. Registry manifest `3e8dcc1c50dcdfd2d748e5e0de8e7595ad0b50a2c62eb9baadb4ffe9e5d640c2`. | Unrestricted 5,000 paired final scores from frozen PA fold 5 and accepted transition fold 4. Confirmed lineups and governed starter evidence required. Historical training chronology remains uncertified. No research challenger substituted. |
| NFL | `NFL_M1_XGBOOST` / `NFL_M1_2026_RESEARCH_SHADOW_V1`, current research/paper baseline. Binary `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd`. | 10,000 paired-residual final scores. Equal discrete scores produce tie mass; it is not an independently validated overtime/tie model. Exact paper supplements and consumer gates remain mandatory. |
| NBA | `NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1`, research baseline; joint `NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1`. Ridge binary `063e69ffb685a16bd784276fa94bce27f8e2d5e91f744e8c9a60a46f242f70ef`. | Elo winner, Ridge points and 10,000 paired-residual joint draws are separate channels. Original point artifact has drawCount=0. Season inactive during demo. Close-score arm preserved, not selected. |
| CFB | `CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1`, research baseline. Ridge binary `cb3f20293477100c202d48c174f1c3e706c943728697e1089bbb742453876bb6`. | Ridge points, Development-calibrated margin winner, Elo winner and joint winner are separate. 10,000 paired draws. No cluster/gap challenger promoted. |

Exchange declarations contain full model, preprocessor, feature, source and
residual bindings with physical hashes/lengths. These dependencies remain
external. This source clone is not complete system recovery.

## Historical evidence carried forward, not reassessed

| Evidence | Population | Retained metrics |
|---|---|---|
| MLB PA fold 5 | 101,264 PAs; 1,342 registered games | PA log loss 1.470973; summed eight-class Brier 0.701268. Not game-winner metrics or certified prospective validation. |
| NFL M1 recipe | 1,408 Development games, 2020–24 | Three-way log loss 0.674896; summed three-class Brier 0.448840; margin MAE 10.0699; total MAE 10.6270. Season-forward recipe fits, not direct validation of all-history artifact. |
| NBA corrected Ridge/Elo | 1,225 reused 2025–26 games | Elo log loss 0.606258; binary Brier 0.208971; Ridge margin MAE 11.3932; total MAE 15.1779. |
| NBA joint baseline | 7,009 reused games | Energy 10.4342; total CRPS 10.7551; margin CRPS 7.87354; joint-winner log loss 0.625271; binary Brier 0.217916. Excess one-point margin mass remains disclosed. |
| CFB Ridge | 1,491 Validation games, 2023–24 | Calibrated-winner log loss 0.560084; binary Brier 0.189798; margin MAE 13.2717; total MAE 12.9134. |
| CFB joint baseline | 752 reused 2025 games | Energy 10.0004; total CRPS 8.78520; margin CRPS 9.25032; joint-winner log loss 0.537249; binary Brier 0.181440. |

Losses use natural logarithms. NBA/CFB binary Brier is `(pHome-yHome)^2`;
NFL retains AWAY/TIE/HOME summed Brier. Simulation draws are numerical samples,
not independent assessment games. Finalized-record reconstruction and selection
qualifications remain attached. No historical assessment was rerun.

## Forecast coverage and dependencies

The release identifies 21 objects covering 20 games: 16 NFL Week 2 CURRENT
forecasts, two NBA channels for BOS at DET, original CFB Syracuse at Pittsburgh,
one new CFB weekend forecast, and one historical MLB V18 example. Seventeen
existing SHOW_PREVIEW derivatives are separate; they add no independent games
and cannot replace final forecasts. `FORECAST_MATRIX.md` gives exact bindings.

New CFB: Coastal Carolina at Delaware, CFBD **401869940**, September 19 at
**15:30 UTC / 11:30 EDT**. Source cutoff **September 14 21:59:02.691510 UTC**;
created **September 16 14:42:00.913203 UTC**; published
**September 16 14:55:47.929484 UTC**. Ridge points: **22.774984 away /
32.949366 home**. Home-win probabilities: **0.724035 Ridge-margin**,
**0.558205 Elo**, **0.7315 joint**. This is an early research snapshot,
not a fresh final or a new Show Preview.

CFB index/address: `223bbc35becc894560cc255dd7b786d2921c3201d63875c0af4a1af4e0b3ff76`,
under `C:\Users\james\asp-model-exchange\cfb-gen1-research-v1\current-v1\packages\sha256`.
The original CFB current pointer was not replaced. Existing CFB paper eligibility
binds only Syracuse–Pittsburgh; it does not transfer to the new weekend game.

MLB natural invocation evidence verifies deployment
`77d39e1ae08e05be82e19bdb0bab21999fba1d3b`, installed owner code, a
`BOUNDED_TICK_COMPLETED` receipt and retained launcher exit 0. Timing remains
T-60 checks / T-45 delivery target / T-30 consumer-window open / T-15 decision /
T-5 independent research publication. No manual invocation, restart, STOP
mutation, scheduler change or activation occurred. Live task enumeration was
not newly established. Weekend finals must await authentic inputs and the
existing owner. Exact MLB exchange-package inspection was access-denied;
local original forecast and 5,000 paired scores verified. That is an audit
visibility gap, not proof of owner failure.

NFL `generatedAtUtc` is bundle generation, not a measured physical publication
instant. Package existence is verified before kickoff; original creation/source
clocks and eligibility remain bound. Unchanged CURRENT forecasts can be reused
by the existing final owner. A new version needs its own supplement. First
window: DET–BUF, September 17 **23:45–00:00 UTC**, kickoff September 18 **00:15 UTC**.

NBA retains the October 20 BOS–DET schedule and original September 14 clocks.
Prior point/Elo receipt confirms import but says display was not completed.
It does not confirm the joint package or this release. Existing joint-baseline
paper eligibility is preserved separately; NBA is season inactive for the demo.

The Show Preview plan pins an older consumer validator. Its guard correctly
rejected the changed file. Read-only inspection of successor pure validator
`35715f3241c3f2b6c1d2ce33f01728da2562c93485ffc47cd06fc72e2beac083`
confirmed compatibility; all 17 wrappers passed exact derivation replay.
Neither the old plan nor consumer code was modified.

**Blocks a fully live demo:** MLB weekend inputs/final packages; exact AISP
import/display acknowledgements; consumer canonical binding for the new CFB
game. Quotes, deadlines and policy gates remain consumer-owned.

**Does not block an honest research demo:** NBA inactivity; new CFB's missing
exact paper supplement; NFL tie/personnel limitations; historical vintages;
MLB inspection visibility gap; paused recovery encryption.

## Focused verification and commands

From `C:\Users\james\asp-model-studio-source`, using existing dependencies:

```powershell
$python = 'C:\Users\james\asp-model-studio\.venv\Scripts\python.exe'
$task = 'C:\Users\james\asp-model-studio\.runtime\scotty-demo-20260916-v1'
$env:ASP_DEMO_TEST_ROOT = "$task\focused-tests"
& $python -B -m pytest tests/test_scotty_demo_release.py -q -p no:cacheprovider
& $python -B scripts/scotty_demo_release.py verify --package '<packagePath in PUBLICATION.json>'
# Optional replay of only the new CFB forecast; no forecast writes:
& $python -B scripts/scotty_demo_cfb.py --studio C:\Users\james\asp-model-studio --output "$task\cfb-weekend" --verify-reproduction
```

The task-specific builder stages declarations/references. The finalizer admits
the new CFB package through its existing verifier and validates retained
preview/paper bindings. The release publisher atomically updates only its
additive demo tree. Do not rebuild over a sealed release: verify or idempotently
republish its original staging bytes. These are not recurring publishers.

Checks cover physical identity, probabilities, paired draws/counts/means,
UTC/EDT/DST, chronology, exact model/eligibility binding, CFB reproduction,
Unicode, authority separation, tamper rejection, atomic discovery and
idempotency. These are integrity checks, not predictive evidence. Numerical
source modules are unchanged from the starting branch.

Provider requests/bytes/cost: **0 / 0 / $0**. Sportsbook calls, AISP writes,
model fits, promotions, sealed payload reads and scheduler changes: **0**.
One new 10,000-draw CFB forecast; one 10,000-draw verification replay.
GitHub source traffic is separate from provider accounting. Independent
existing owners continue their own activity.

Safe recovery staging and Git bundle were retained; no new large archive,
encryption or OneDrive upload was started for this release.

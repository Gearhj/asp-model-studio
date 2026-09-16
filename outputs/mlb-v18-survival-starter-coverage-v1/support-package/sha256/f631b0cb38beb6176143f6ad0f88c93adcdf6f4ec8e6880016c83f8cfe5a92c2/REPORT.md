The starter-history intake and execution path is implemented, but no new supported survival forecast was possible in this session. The September 13 slate has 25 known starters and five missing identities; all 30 slots remain unsupported. The first matchup now has 21 eligible historical starts registered, with six protected appearances still unresolved. No additional fallback forecast was produced or presented as a successful survival run.

The separate 15-game cohort was fixed at 2026-09-12T23:32:36.838801Z before its outcomes. The final metadata check at 2026-09-13T00:09:42.936965Z found zero immutable ordinary V18 baselines for that slate: 15 games pending, zero expired, zero simulations, zero supported survival/transition/common pairs, zero candidate publications and zero confirmed imports. The previous six-game cohort, five survival fallbacks and stopping boundary remain unchanged.

The compact per-starter accounting is in [starter-support.md](starter-support.md), with exact identities and missing prerequisites in [starter-support.json](starter-support.json). For the first game, COL–DET 824225:

- Gabriel Hughes (687312): eight eligible 2026 starts retained, one relief appearance correctly excluded, three protected appearances unresolved. His pre-2026 absence is certified.
- Jackson Jobe (695549): ten eligible 2025 starts reconstructed with the accepted frozen parser and three eligible 2026 starts retained; three protected appearances unresolved. Earlier coverage is certified.
- The resulting 22-record registry contains 21 eligible starts. Its separately registered manifest is `740f2ce18d0cba10f0d0ae24353029b60f400ec1e328bb336340d0fda86b9592`. The existing runtime reads it and correctly refuses incomplete coverage. It also refuses to attach this later materialization to an earlier baseline snapshot.

The exact runtime fields and provenance requirements are traced in [runtime-feature-trace.json](runtime-feature-trace.json): home side and calendar month come from immutable pregame evidence; prior-start count, prior-start BF mean, rest and the certified history-missing indicator come from the eligible registered history. BF evolves in the simulator. Identity mapping alone cannot replace missing appearances, eligibility facts, BF or source/capture clocks. Snapshot workload fields that the frozen estimator does not use were not invented. Label-only assessment exports were not used as covariates.

The original intake authorization explicitly permits additional matchups in declared deadline/readiness order under its shared limits. This session used **41 requests, 9,788,585 original bytes and $0**: 29 metadata requests and 12 nonprotected source feeds. No paid requests, failures or retries occurred. The shared ledger now totals 101 requests and 33,151,875 bytes, leaving 99 requests and 491,136,125 bytes. Source bytes, receipts, revisions, identity mappings and clocks are retained; [source-intake-session.json](source-intake-session.json) gives every new request and digest.

The existing protected-source exception covers three different pilot appearances. [specific-source-exception-request.json](specific-source-exception-request.json) requests only Hughes games 823182/824316/822694 and Jobe games 824237/823342/824233 from the projected official game-feed endpoint: six calls, estimated 939,430 bytes, hard maximum 48 MiB, known cost $0. That request remains unapproved. It proposes permanent whole-game quarantine before any new access, with the original Final OOT payloads sealed. No protected values were accessed. Every fully identified matchup has at least one such unresolved pitcher; Pivetta alone has no protected appearance in the enumerated prefix, but his opponent Webb does.

Even if that exact request is approved, September 12 history must be enumerated again after the New York day closes at **2026-09-13T04:00:00Z**, then certified before a new immutable baseline's original input cutoff. Confirmed inputs and ordinary publication remain prerequisites. The first game's deadline is 2026-09-13T15:55:00Z. Permission, later history or a later final cannot retroactively change an earlier fallback.

Claude's new final handoff enabled one justified scoring pass through the existing scorer. Both arms use the same governed revision-1 final in each study; all three existing studies are now scored. Negative differences favor the candidate:

| Existing study | Δ winner log loss | Δ Brier | Δ total CRPS | Δ margin CRPS |
|---|---:|---:|---:|---:|
| September 11 COL–DET survival | −0.008113 | −0.003837 | −0.000188 | +0.032120 |
| September 12 NYM–NYY transition | −0.003315 | −0.001531 | Unavailable | Unavailable |
| September 12 KC–BOS transition | +0.001952 | +0.000924 | +0.011620 | +0.024924 |

All eligible home/away/total/margin measurements are retained in [scoring/current.json](scoring/current.json). NYM–NYY candidate distributions were never retained, so distribution metrics stay unavailable. Missing transition sequences do not block whole-game scores. COL–DET starter BF evidence is now available. All three completion clocks are qualified last-event proxies with unknown provider publication time; actual label-availability clocks remain separate. The original revision gate, exclusions and historical training-chronology limitations remain attached. These distinct one-game studies establish neither pooled gain nor superiority.

Claude's updated unmodified consumer validates the existing V1 survival and V2 transition packages with zero rejections; this clears the previous contract mismatch. It does not confirm import or display. The handoff for this assignment is a support/status package, with no new candidate forecast IDs or draws to import. Claude should read its manifest and support note; future candidate packages use the existing adapter and separate `survival-starter-coverage-v1/current.json` leaf only after a genuine survival execution. The support handoff uses `support-current.json` to preserve that distinction.

Run from `C:\Users\james\asp-model-studio`:

```powershell
# Cache-only history reconstruction; remains partial until authorized evidence exists.
.venv/Scripts/python.exe -B scripts/build_mlb_survival_slate_history_v1.py
# Readiness, then eligible execution and publication through the existing contract.
.venv/Scripts/python.exe -B scripts/run_mlb_survival_coverage_comparisons_v1.py plan
.venv/Scripts/python.exe -B scripts/run_mlb_survival_coverage_comparisons_v1.py run --max-games 1 --wall-seconds 1200
.venv/Scripts/python.exe -B scripts/run_mlb_survival_coverage_comparisons_v1.py package --export
# Existing-study scores; rerun only when a new governed final revision warrants it.
.venv/Scripts/python.exe -B scripts/score_mlb_frozen_component_pairs_v1.py --output-root outputs/mlb-v18-survival-starter-coverage-v1/scoring
```

The future runner holds the existing ownership locks, reuses the immutable baseline, original cutoffs, frozen components and 5,000-draw seed scheme, and retains paired draws on execution. A failed survival arm remains an exact baseline fallback and is excluded from a supported-survival publication. No numerical attempt occurred here. Focused checks cover the explicit history mapping, exact held-game identity distinction, registry/cutoff rejection, fallback filtering, package integration and preservation. There was no refit or broad test expansion.

Implementation commits are `9022474f6af77277875caf44197e83e28ea3065b` and `de2ec0168d016e20618d82a1d4f9e22afdadcc66`; this evidence is committed separately. V18, fitted preprocessing, survival estimator, transition challenger, calibration and authority settings are unchanged. The completed NFL restoration/archive receipts are preserved. The deployment verdict is **blocked by specific source permission, day-complete history and future baseline readiness; predictive improvement remains insufficiently evidenced**.

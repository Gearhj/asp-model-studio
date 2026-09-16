Correct winner picks remain **0/3**: **zero wrong-to-right and zero right-to-wrong changes**. No winner pick changes in the four executable populations, including the unscored prospective game. The evidence is insufficient to say that removing extreme scoring scenarios improves V18 winner forecasts.

The frozen initial rule accepts complete original draws only when every played half-inning has at most **5 runs** and both team final scores are at most **14 runs**. It rejects the union of violations, treats both teams identically, and accepts equality. These are the upward-rounded linear 99th percentiles from 7,267 permitted 2021–2023 Development games (128,887 played halves; 14,534 team scores). Twenty-two incomplete/inconsistent games were excluded under the declared completeness checks. Non-PA scoring and zero-run played halves count; unplayed halves do not. No September 12 outcome or challenger performance selected the thresholds.

The rule was frozen at **16:36:39Z** and delivered to Model Exchange at **16:41:59Z**, before filtering at **16:44:13–15Z**. The executable `MLB_V18_SCORE_LIMITED_V1` is a separate research configuration. It adds no draws, fits, feature changes, calibration, transitions, duration rules or production authority. Original paired scores, arrays, baseline forecast files and retained draw indices reconcile exactly. The accepted games themselves are unchanged; full event sequences that were never saved are not reconstructed or claimed retained.

| Observed September 12 cohort metric | V18 | Score-limited | Limited minus V18 |
|---|---:|---:|---:|
| Correct winner picks | 0/3 | 0/3 | 0 |
| Mean winner log loss | 0.829449 | 0.826990 | −0.002459 |
| Mean binary Brier | 0.316640 | 0.315483 | −0.001158 |
| Mean team-score absolute error | 3.824833 | 3.796399 | −0.028434 |
| Mean total-run absolute error | 3.814467 | 3.988560 | +0.174093 |

Negative error differences are better. Team-score error averages the absolute errors of the expected away and home scores, then weights each game equally. Binary Brier uses `(pHome − observedHomeWin)^2`; all four populations have zero ties. These are winner picks at probability 0.5, not selections based on offered prices or a claim about betting returns.

NYM–NYY retains **4,600/5,000** draws (8.00% excluded), PHI–ATL **4,660** (6.80%), and PIT–CHC **4,656** (6.88%). The NYY, PHI and PIT picks all remain wrong. NYM/PHI log loss and Brier improve slightly; PIT worsens. Lower total predictions worsen total errors in the two large-score games and improve PIT–CHC. Historical probability shifts are only about 0.13–0.21 percentage points, with paired difference MCSE about 0.19–0.20 points. MCSE measures simulation sampling precision, not model/input error or uncertainty about recurring improvement. The three games were selected after observing their outcomes and remain exploratory.

The declared inventory has **41 eligible ordinary immutable objects**: four full counter populations and **37 explicitly unsupported counter gaps**. No missing counter is treated as a zero exclusion or a successful execution. No simulation rerun fills those gaps. Final OOT remains sealed and the complete current whole-game quarantine was applied to identities before outcome access. The corrected V2 observed evidence and exact governed final revisions remain bound in the scoring receipt.

**CIN–MIL 823734** is the one prospective comparison. It retains **4,722/5,000** draws (5.56% excluded); the CIN pick is unchanged. MIL win probability is **49.62% → 49.386%** (candidate MCSE 0.728 percentage points; paired change MCSE 0.172 points). Expected CIN/MIL scores are **4.1116/3.8540 → 3.9416/3.6679**. Its immutable comparison was frozen **16:44:13.820226Z** and published **16:45:14.592443Z**, before the original **17:55Z** cutoff. No outcome was accessed. No threshold tuning or extension of this one-game declaration is planned here.

The package contains a precise V3 `SCORE_LIMIT` extension to the existing candidate adapter. AISP currently supports V1/V2: **one research comparison produced and published; zero imports confirmed**. Claude must implement that narrow research import role, preserve the original 5,000-draw baseline binding, use the actual 4,722 accepted denominator, verify hashes and return the exact import receipt. This changes no AISP settings or production authority. Existing survival/transition studies and completed NFL restoration remain untouched. Provider requests, downloads and cost were zero.

Reproduce the fixed comparison from retained evidence (no simulation, acquisition or future outcome access):

```powershell
.venv/Scripts/python.exe -B scripts/run_mlb_v18_score_limited_v1.py
.venv/Scripts/python.exe -B scripts/score_mlb_v18_score_limited_v1.py
```

The reusable filter is `server/sports_current_statcast/mlb_v18_score_limited.py`; the supported future packaging path is `scripts/package_mlb_v18_score_limited_v3.py --execution-ref outputs/mlb-v18-score-limited-v1/executions/823734/current.json`. Existing immutable receipts retain their original clocks when reused. A newly generated package must still pass the original cutoff; expired opportunities cannot be backfilled. The only next observation needed for this frozen challenger is the eligible final for the already published CIN–MIL comparison, not another threshold search. One future result also cannot establish recurring superiority.

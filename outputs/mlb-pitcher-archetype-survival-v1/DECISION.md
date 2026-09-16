Pitcher-archetype survival result

**Archetypes added no demonstrated useful information in this controlled comparison.** Continuous profiles increased the primary path loss by 0.008287 nats/start (0.31%); adding archetypes increased it by another 0.003656 (0.14%). Both descriptive uncertainty intervals include zero. Keep the frozen operational survival model; neither B nor C meets the predeclared advancement rule. These results do not establish that pitching style is universally uninformative.

One common cohort contains **2,175 assessment starts, 1,155 games and 270 distinct pitchers**, July–September 2024. A/B/C use the same 4,537 training starts from 2023 and 2,346 January–June 2024 starts for the existing one-scalar temperature procedure. All BF rows of a start remain together. The assessment is reused Development, already inspected in the preceding survival study; it is not untouched confirmation.

| Arm | Primary path NLL ↓ | 3-event boundary Brier ↓ | BF CRPS ↓ | BF mean absolute error ↓ | BF mean bias |
|---|---:|---:|---:|---:|---:|
| Frozen operational HGB | 2.673659 | 0.078347 | 1.972371 | 2.7660 | -0.1088 |
| A: matched refit | 2.672834 | 0.078221 | 1.962584 | 2.7450 | -0.1001 |
| B: + continuous profiles | 2.681120 | 0.078362 | 1.962028 | 2.7321 | -0.0749 |
| C: + soft archetypes | 2.684776 | 0.078552 | 1.968293 | 2.7388 | -0.0808 |

Primary loss is the mean across appearances of the sum of −log probabilities for the observed CONTINUE/REMOVAL/GAME_END path. Boundary Brier sums squared error over the three events, then averages within each appearance and across appearances. BF CRPS integrates the discrete BF distribution through 100; unresolved tail is retained. Positive bias means longer than observed. Actual mean BF was 22.0037. No BF row is counted as an independent game.

| Contrast; positive is worse | Path-NLL difference | 95% paired game interval | 95% paired pitcher interval |
|---|---:|---|---|
| A − FROZEN | -0.000825 | [-0.005704, +0.004405] | [-0.005150, +0.004325] |
| B − A | +0.008287 | [-0.005604, +0.022967] | [-0.007907, +0.026105] |
| C − B | +0.003656 | [-0.002821, +0.009703] | [-0.003328, +0.011272] |
| C − A | +0.011942 | [-0.001857, +0.027080] | [-0.003909, +0.028848] |

The fixed 500-resample intervals preserve paired starts within game or pitcher clusters. They show no reliable improvement and do not establish conclusive harm. B slightly improved BF MAE (−0.01285 BF) and early/long-start Brier, but BF CRPS was essentially unchanged (−0.000556), while path and BF likelihood worsened. C worsened BF CRPS by +0.006265 relative to B and eroded the small MAE gains. Raw path losses have the same unfavorable direction, so temperature calibration alone does not explain this result.

**Training-only groups.** K=3 had the lowest training BIC among configurations meeting support and seed-stability requirements. K=2 also passed. K=4/5 had undersupported groups; K=6 also failed stability. No assessment outcomes selected K. The same pooled HGB learns across every group.

| Group / measured description | Training starts / pitchers | Assessment starts / pitchers | Left-handed | Four-seam median / P90 mph | Splitter usage |
|---|---:|---:|---:|---:|---:|
| 0: Mostly right-handed; splitter usage prominent | 501 / 35 | 419 / 48 | 1.0% | 94.2 / 95.6 | 17.5% |
| 1: Right-handed; broader fastball/slider/change mix | 2787 / 223 | 1199 / 151 | 0.0% | 93.9 / 95.4 | 0.0% |
| 2: Mostly left-handed; somewhat lower four-seam velocity | 1249 / 105 | 557 / 75 | 99.3% | 92.9 / 94.3 | 0.0% |

These are descriptive profiles, not talent/command ratings. A distinct curve-heavy archetype did not emerge. Group pitcher counts overlap because one pitcher can change membership across historical starts. Maximum membership below 0.6 flags uncertainty: zero training and one assessment start. Other posteriors are very sharp; this is Gaussian-mixture concentration, not certified confidence in natural pitcher classes. Complete movement/release summaries, feature medians and denominators are retained in the cluster-selection object.

| Assessment group | A path NLL | B path NLL | C path NLL | B−A | C−B |
|---|---:|---:|---:|---:|---:|
| 0 | 2.66965 | 2.73002 | 2.74315 | +0.06037 | +0.01313 |
| 1 | 2.65386 | 2.64113 | 2.64215 | -0.01273 | +0.00102 |
| 2 | 2.71607 | 2.73041 | 2.73262 | +0.01434 | +0.00220 |

B helped the largest group but worsened the other two. C worsened the primary point estimate versus B in every group. All groups are reported; none is selected as a specialist.

**Allocation and terminal calibration.** B moves 49.4% of starts earlier and 50.6% later than A; average absolute change is 0.670 BF while its pooled mean shift is only +0.025 BF. C versus B moves 51.9% earlier and 48.1% later, with 0.254 BF average absolute change and −0.006 BF pooled shift. The changes are individualized, but that did not deliver improved primary accuracy.

There were 78 early exits (BF≤9, 3.59%), 255 long starts (BF≥27, 11.72%) and 13 GAME_END starts (0.60%). A/B/C predict early-exit means of 3.38%/3.46%/3.43%, long-start means of 10.93%/10.01%/10.00%, and game-end means of 0.539%/0.304%/0.328%. Only 13 competing game-end events support the last comparison. Lower aggregate terminal Brier is not evidence of better game-end calibration.

Over the same 47,858 observed BF boundaries, A/B/C sum to 2,265.0/2,290.3/2,294.9 removal probabilities, versus 2,162 observed removals. These sums are conditional on the observed risk set, not pregame counts of independent removals. The saved fixed-bin table retains ordinary and next-opportunity conditional removal calibration, sample counts, and equal-appearance weighted rates. Central 90% BF coverage is 90.99%/90.34%/90.34%; maximum mean unresolved tail across all arms is below 2.2e−16.

**Coverage and chronology.** The builder used 1,476,493 eligible prior pitch records from 546 retained daily source files, within 2022–2024. Profiles require ≥200 pitches over ≥3 prior dates in a 365-day window, a consistent throwing hand and ≥30 finite observations per measured pitch-group statistic. They contain usage fractions, median/P90 velocity in mph, and movement/release medians in feet with source horizontal orientation retained. Pitch effectiveness and measured-command claims are absent. Seven UNKNOWN-type measurement fields have no training support: the hazard imputer drops those measurement columns, while clustering retains zero-imputed constants. Unknown usage remains explicit.

Of 9,555 original eligible starts, 9,058 have supported profiles. Assessment coverage is 2,175/2,302 (94.48%): 127 unsupported starts involve 61 pitchers, including 30 with no supported assessment start. All identities mapped; insufficient prior pitch/date support drives the gaps. The original 163 unsupported duration starts stay excluded. Every unsupported appearance, exact reason and prior sample count is retained in profile-coverage.json.

Source captures occurred in August 2026. Target-start and later-game pitches are excluded, but original historical publication/revision clocks are unavailable. This remains prior-event reconstruction, not vintage-certified historical pregame evidence. The physically separate modeling sources contain none of the nine permanent exclusions; no protected-history exception supplies features or targets.

**Decision and future path.** Keep the frozen operational survival model. Do not advance B or C to a prospective game comparison from these results, and do not fit a favorable-group specialist. No new candidate game forecasts, fallback game rows or publications were created. The executable research lookup preserves q=REMOVAL/(CONTINUE+REMOVAL), BF0/inactive gates and exact baseline fallback; a calculated lookup is explicitly not a simulated game.

At the separate 20:06Z metadata snapshot, SD–SF 823171 had no immutable baseline yet, and its probable starters lacked certified complete workload histories for this new component. Existing protected HGB history permissions do not transfer to archetypes. No new acquisition or current-source processing is justified by this failed advancement gate. Existing V18, survival/transition studies, NFL operation, funded decisions and schedulers remain unchanged.

Access qualification: a delegated prospective metadata summary inadvertently surfaced nested protected-appearance BF/removal/attribution fields in an old starter-history manifest. Inspection stopped; none of those values entered selection, profiles, fitting or assessment. No raw protected source or sealed evaluation artifact was opened. The incident is retained in prospective-feasibility.json; this report does not claim zero exposure to protected parsed fields.

**Executable delivery.** The separate profile builder, A/B/C artifacts, soft-membership model, exact common-cohort IDs, per-risk predictions and per-start BF/cause distributions are checksum-bound. Twenty-five focused checks passed across profile/model/runner behavior; the unchanged cached --stage all path also completed without fitting or prediction reruns. Path NLL reconciled with the integrated observed BF/cause probability for every arm. Code commit: `5918517`.

[Immutable assessment](C:\Users\james\asp-model-studio\outputs\mlb-pitcher-archetype-survival-v1\objects\sha256\b8be226bfbc5622344cd6758d0203b0aaa3a91972162412b0cbe12a3477ff2e2\assessment.json) · [Fitted-artifact index](C:\Users\james\asp-model-studio\outputs\mlb-pitcher-archetype-survival-v1\fit.json) · [Cluster selection](C:\Users\james\asp-model-studio\outputs\mlb-pitcher-archetype-survival-v1\objects\sha256\27dd5c1da89882bdce31d85243a35558cfe1b4a48396a75d0eff5ce1e6ee2cdf\cluster-selection.json) · [Removal calibration](C:\Users\james\asp-model-studio\outputs\mlb-pitcher-archetype-survival-v1\objects\sha256\a1c02d4d4165c6dfc3c87362f6afe28f5403430b332a7f5c19f07f30762cad90\removal-calibration.json) · [Profile coverage](C:\Users\james\asp-model-studio\outputs\mlb-pitcher-archetype-survival-v1\profile-coverage.json) · [Profile contract](C:\Users\james\asp-model-studio\outputs\mlb-pitcher-archetype-survival-v1\PROFILE_CONTRACT.md)

Reproduce or verify the retained stages with no provider access:

```powershell
.venv/Scripts/python.exe -B scripts/run_mlb_pitcher_archetype_survival.py --stage all
```

Use --stage profiles, --stage fit or --stage assess to checkpoint the same declared pipeline. Existing valid caches are verified and reused; mismatched source/code/declaration bindings fail closed rather than silently refitting.

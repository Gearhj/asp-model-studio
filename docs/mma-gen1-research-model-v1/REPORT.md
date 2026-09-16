# UFC Generation 1 historical research model

## Disposition

**`NO_MODEL_SELECTED`.** A calibrated HGB finalist produced materially better
Validation and 2025 proper scores than the chronological Elo benchmark. It still
failed the frozen Final OOT calibration gate: slope `1.5187` exceeded the upper
limit `1.5`. Gen 1 is therefore preserved as a reproducible failed research
finalist. No threshold, calibration method or model was changed after opening OOT.

## Source and rights

The source is Kaggle dataset version 87,
`aminealibi/ufc-fights-fighters-and-events-dataset`, created 2026-04-01 and
downloaded once on 2026-09-16. Anonymous public access succeeded without a Kaggle
credential or affirmative bypass. The ZIP is 3,824,019 bytes with SHA-256
`83b18b1c834ac4ea586c16cbf44276494b81ea39f5663c8311959f0d0b22ff11`;
the nine extracted files total 11,655,635 bytes. Metadata used one request and
7,850 bytes; the download used one request and 3,824,019 bytes. Cost and credits
were zero. No other provider was called.

Kaggle labels the dataset `CC0: Public Domain`. The retained qualification remains:
some material was reportedly compiled from UFCStats, so this use is internal
research only and does not assert settled upstream commercial rights. Raw files
remain external and git-ignored. They are absent from the package and Git.

## Quality gate and population

The archive contains 756 events, 8,482 raw bout rows, 8,461 cleaned bout rows and
4,448 fighter rows. Event, fight and fighter IDs are unique; every clean bout joins
an event. One 1997 card contains two distinct `Fight_Id` values for the same pair,
which is a legitimate same-event rematch rather than a duplicate identity. Seven
normalized display names map to multiple fighter IDs, so IDs—not names—govern
identity. One 2025 bout lacks one fighter-dimension row and is excluded.

The clean history has 8,311 decisive bouts, 60 draws and 90 no-contest/overturned
bouts. The source contains finalized bouts and no cancellation population. The
model population begins in 2010, requires a decisive W/L and a standard three- or
five-round format, and has no modern fighter repeated on one date.

| Role | Dates | Eligible bouts |
|---|---|---:|
| Development | 2010-01-01 through 2022-12-31 | 5,538 |
| Validation | 2023-01-01 through 2024-12-31 | 1,005 |
| Final OOT | 2025-01-01 through 2025-12-06 | 499 |

Recorded exclusions are 1,244 pre-modern rows, 84 modern no-contest/overturned
rows, 51 modern draws, 39 nonstandard schedules and one missing fighter join.
The 2025 identity set was frozen at SHA-256
`982f6251d28885f19e115639ae0b9d58d440636939959ec55737d9b0bca366d9`
before directional labels or metrics were opened.

The fighter table is a current snapshot. Its W/L/D, belt and aggregate statistics
are target-leakage risks and are excluded. Age is unavailable. Height parses for
4,124 fighters with 324 missing, reach parses for 2,502 with 1,946 missing, and
weight has three implausible current-snapshot values; none of these fields enters
the model. Twenty-one raw rows absent from the clean table are all from 1994–1998
and therefore precede eligibility.

## Leakage and orientation controls

Features are emitted before a bout updates either fighter. The state update uses
only prior decisive bouts and includes Elo, experience, win/finish method rates,
recent form, layoff, duration, striking, takedown, submission, control,
knockdowns, opponent strength and weight-class changes. Weight class, scheduled
rounds, rematch count and calendar year are target context. There are 25 numeric
features and one categorical feature.

The row orientation is the sorted fighter-ID pair. The API returns the canonical A
probability or its exact complement for the reverse request. The retained test and
package replay both report zero complement error. This prevents learning a
red-corner, source row-order or winner-first convention.

Day-level dates cannot prove original publication timing, so every result is
reconstructed historical evidence. The zero modern same-date repeat-fighter count
prevents within-day ordering ambiguity from altering a fighter's feature state.

## Candidate screen

The candidate and selection design was frozen at SHA-256
`c03b4af9ae7b072b0b1a8ebdd502d37bd3ca910dc5db34cede82f045a7a404d7`
before Validation comparison. Development OOF folds assessed 2017 through 2022,
with each fold's preprocessing fitted only on earlier years. Platt calibration was
fitted from Development OOF predictions, then applied unchanged to Validation.

The bounded screen contained:

- Elo with K 24 and scale 400.
- Logistic regression at C 0.1 and 1.0.
- HGB at two frozen depth/regularization configurations.
- One fixed 50/50 calibrated logistic/HGB ensemble.

| Validation model | Log loss | Brier | ECE10 | Cal slope | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|---:|
| Elo | 0.6759 | 0.2415 | 0.0289 | 1.4827 | 0.6078 | 0.5781 |
| Logistic | **0.6430** | 0.2261 | 0.0375 | 0.8853 | 0.6781 | **0.6348** |
| HGB | 0.6475 | 0.2279 | 0.0239 | 0.9073 | 0.6721 | 0.6219 |
| 50/50 ensemble | 0.6418 | **0.2254** | **0.0238** | 0.9624 | **0.6807** | 0.6338 |

Logistic failed the predeclared ECE guardrail relative to Elo. The ensemble did
not beat both members by the required 0.003 log loss. HGB was the only non-Elo
candidate that passed all frozen eligibility rules, using learning rate 0.05,
160 iterations, 15 leaves and L2 regularization 1.0.

Validation permutation importance is associational. Experience difference was by
far the largest HGB signal, followed by prior average fight duration, finish rate,
Elo, control share and win rate. Several striking/submission permutation effects
were small or negative, which cautions against interpreting the model as a causal
fighter-style system.

## One-time Final OOT

The finalist receipt was written before OOT and has SHA-256
`1fe025b8fec04a20c017d271fe3634961787ef346d9f23c600d83ff2ded94fdb`.
The 2025 population was then evaluated once.

| Final OOT model | Log loss | Brier | ECE10 | Cal slope | AUC | Accuracy |
|---|---:|---:|---:|---:|---:|---:|
| Elo | 0.6645 | 0.2359 | 0.0541 | 2.4464 | 0.6563 | 0.5932 |
| HGB finalist | **0.6061** | **0.2084** | 0.0845 | **1.5187** | **0.7483** | **0.7114** |
| HGB minus Elo | -0.0583 | -0.0275 | +0.0305 | — | +0.0920 | +0.1182 |

Across 2,000 calendar-month block bootstrap draws, HGB-minus-Elo log-loss change
had 95% interval `[-0.0820, -0.0347]`; Brier change had interval
`[-0.0389, -0.0161]`. These support a recurring proper-score gain over Elo in the
retained year. They do not override the frozen calibration gate.

Calibration deteriorated relative to Validation. The finalist's mean picked-side
confidence was 0.6283 while the picked side won 0.7114, consistent with the slope
above one. The largest experience-gap segment (n=194) had strong discrimination
but slope 2.02 and ECE 0.140. Five-round bouts (n=50) had ECE 0.187. These segments
are diagnostic and were not used to retune Gen 1.

## Artifacts and verification

The final research-only package is:

`C:\Users\james\asp-data-staging\mma\ufc-gen1-study-v1\packages\sha256\dee6b5f1535c590be689de2912b469518b5b34d26d05df027789320cdd2bc074`

Its manifest SHA-256 is
`febaa31208396dc67ff24bb704dfa5bba22198631163db2bcfb94b058418902a`.
The retained fitted finalist is 179,332 bytes with SHA-256
`285c75b74d1bc25dc82dd9b3110df940440ce577550d26ae086efc476fdd51b5`.
The full OOT receipt SHA-256 is
`250a15b2eda8fe22e3228b37c856a13bd3f72996118b801f04a34740ee1250d4`.

Verification reconciled all 11 package members, reproduced 499 probabilities with
maximum serialization difference `8.33e-17`, found no raw tracked data and made no
network call. The exact fit environment is Python 3.12.6, NumPy 1.26.4, pandas
2.2.1, scikit-learn 1.6.1, SciPy 1.17.1 and joblib 1.4.2. Repository
`requirements.txt` says pandas 2.1.4; the actual environment difference is retained
rather than concealed.

## Operational boundary and next dependency

No current forecast was created. A real prospective forecast remains blocked by:

1. The frozen OOT calibration failure; any correction must be a separately named
   Gen 2 challenger with a new untouched assessment plan.
2. No validated live UFC schedule/bout/fighter identity feed or change lineage.
3. API-Sports and The Odds API rights/credential POC remains disabled; its existing
   80-request/80-credit guards and `MMA_POC_RIGHTS_APPROVED` gate are unchanged.
4. No certified current pre-bout capture, draw probability, weigh-in, injury,
   ranking or short-notice evidence.

There were zero AISP writes, sportsbook calls, scheduler changes, production
activations, positions or exchange publications. The smallest next modeling work
is a separately registered calibration-stability challenger; it must not reuse
2025 as untouched confirmation. Operational source validation remains a separate
rights-authorized task.


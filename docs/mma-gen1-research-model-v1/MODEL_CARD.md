# MMA_UFC_GEN1_WINNER_V1 model card

**Verdict: `NO_MODEL_SELECTED`.** The calibrated histogram-gradient-boosting
finalist improved proper scores over Elo on Validation and Final OOT, but its Final
OOT calibration slope was `1.5187`, outside the frozen `[0.5, 1.5]` gate. The
artifact is retained as a failed research finalist. It has no forecasting,
promotion, AISP decision, position, scheduler or production authority.

The target is the probability that canonical fighter A wins conditional on a
decisive result. Canonical orientation is lexicographic source fighter ID.
Reversing the participants returns `1 - p`; the verified complement error is zero.
Draws, no contests and cancellations are outside the binary probability.

The model uses 25 numeric chronological features plus weight class. Inputs are
prior Elo, experience, prior win and finish rates, recent form, layoff, prior fight
duration, striking, takedown, submission, control and knockdown rates, prior
opponent Elo, weight-class changes, rematches and scheduled rounds. Each feature
is emitted before the target bout updates state. The model excludes target-bout
statistics, modern fighter-page aggregates, rankings, odds, weigh-ins, injuries,
short-notice status, age and physical traits without historical vintages.

Data is reconstructed finalized history, not certified historical point-in-time
evidence. Event chronology has day resolution. Modern data has no fighter appearing
twice on the same date. Current schedule and fighter-identity intake remain
unvalidated, so no prospective forecast can be generated honestly.

Validation used 1,005 bouts from 2023–2024 after 5,538 Development bouts from
2010–2022. The frozen HGB finalist had log loss `0.6475`, Brier `0.2279`, ECE
`0.0239`, calibration slope `0.9073`, AUC `0.6721` and accuracy `0.6219`.
The one-time 499-bout 2025 Final OOT had log loss `0.6061`, Brier `0.2084`, ECE
`0.0845`, slope `1.5187`, AUC `0.7483` and accuracy `0.7114`.

The retained package contains no raw source rows. Its identity is
`dee6b5f1535c590be689de2912b469518b5b34d26d05df027789320cdd2bc074`.


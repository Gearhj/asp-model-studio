# Leakage and point-in-time audit

## Evidence classification

All numerical evidence is Category A: historical development reconstructed from finalized records. It supports research when each target uses only earlier games, but it does not certify that the same revision was published or captured at the historical forecast cutoff. No result here is Category B certified historical point-in-time evidence or Category C prospective evidence.

The input gate binds exact Parquet bytes, projects only the registered features/identity/targets, rejects calendar-2026 rows, and enforces unique game identity. CFB `feature_max_source_game_date` and NBA `history_latest_game_date` must be earlier than the target. NFL rolling construction was previously audited; the retained projection does not include a per-feature source timestamp, so its availability remains qualified.

## Roles and target access

The study design was committed at `71f17f4` before new outcome-backed calculations. Development and reused-later seasons, candidates, metrics, cold-start rule and acceptance gate were fixed there. Every origin trains on strictly earlier seasons. Target scores are not candidate features. Imputers and scalers are fitted inside the training origin.

The reused later populations were inspected by prior studies. They are labelled diagnostics, not untouched Validation or Final OOT. No 2026 label, sealed payload or Final OOT artifact was read. The permanent MLB quarantine is outside this sport scope and was not invoked because no MLB outcome comparison occurred.

## Known access qualification

The earlier multisport audit's `ACCESS_EXCEPTION.json` records that a discovery process exposed raw 2026 NFL result fields in a rejected snapshot. Those fields entered no fit, metric or recommendation. This study uses only the three independently hash-bound pre-2026 projections and does not claim zero historical exposure to the rejected file.

## Sport-specific risks

| Risk | NFL | CFB | NBA | Control |
|---|---|---|---|---|
| Target game included in rolling history | Possible if upstream chronology regresses | Possible | Possible | strict earlier-origin training; retained source-date assertions where present |
| Final lineup/active roster | not present | not present | not present | prohibit retrospective participant oracle |
| Actual snaps/minutes | not present | not present | not present | require pregame projection/status source |
| Later ranking/rating | source-era risk | material for rankings/schedule strength | Elo chronology risk | fit ratings inside origin; preserve vintages |
| Revised injury status | no retained revisions | no uniform retained feed | no retained revisions | require publication/retrieval/revision timestamps |
| Upstream imputation hides absence | partial | complete projection masks nulls | partial | retain observed/imputed/source-age indicators upstream |
| Team identity changes | relocation aliases | realignment/new programs | franchise aliases | effective-dated canonical identity and predecessor lineage |
| Overtime/tie | native NFL tie mass but no OT flag | final score only | final score includes OT, no period flag | keep final-score target; do not infer OT mechanism |

## Prohibited features

Actual postgame participants, snaps, minutes, substitutions, final active rosters, target-day status revisions captured after cutoff, end-season rankings, closing odds and later corrected statistics without historical vintages are excluded. Missing evidence is not encoded as zero unless zero is the documented semantic value.

## Injury capture contract

An admissible record needs canonical player/team/game identity, source status and vocabulary, source publication time, retrieval time, effective event, expected-participation or scenario semantics, revision/predecessor identity, and payload hash. The feature calculation must freeze at the exact forecast cutoff. Subsequent confirmation may create a new immutable forecast revision; it may not overwrite or backfill the earlier feature row.

## Remaining certification gap

The decisive missing evidence is original historical revision timing. The next challenger may support reconstructed research, but a claim about prospective gain requires future pregame captures under the same feature contract and frozen comparison. No production routing or model promotion follows this audit.

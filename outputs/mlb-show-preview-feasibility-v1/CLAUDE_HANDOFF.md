# MLB preview producer: current-input dependency

Disposition: **MLB_SHOW_PREVIEW_IMPLEMENTED_AWAITING_CURRENT_INPUTS**. This is a research-model and producer-capability handoff, not a forecast import or consumer activation request.

There is **no new genuine MLB SHOW_PREVIEW package to import**. Keep all 17 NFL/CFB preview packages and discovery entries. Discovery physical SHA remains `146fd0c48a0dab68fbd7acb279a417c48d989a289034925d58dd86aa69bdee59`. NBA and all final forecasts are untouched. No AISP records were written; no consumer acknowledgement is inferred.

The smallest assessed alternative is `MLB_TEAM_LOGISTIC_C1_POISSON_A1_SHOW_PREVIEW_V1`:16 team score/date-history features, Logistic C=1 winner probabilities and independently estimated Poisson alpha=1 home/away means. No pitchers, lineups, injury, park or market inputs; statuses UNKNOWN. No joint simulation, intervals, Over/Under probability or wagering authority. `draw_count=0`; distributions null. Do not present its mean scores and win probabilities as one joint population, or identify it as finalV18.

Reused 2024 Validation (2,429 games): log loss0.69239→0.68216; binary Brier0.24962→0.24454; accuracy52.16%→56.24%; AUC0.5842; total MAE3.421→3.412. Week-block 95% LL difference interval[-0.01602,-0.00459]. Historical source revision/publication vintages remain uncertified. All inputs omit the whole calendar day preceding each target. No 2026 outcome selection or sealed payload access occurred.

Retained consumer binding: `AISP_SHOW_PREVIEW_FORECAST_V1`, horizon exactly `SHOW_PREVIEW`, validator physical SHA `1a6771cb0fbf7c41cdc1e05e09141a7a4db513b82a7993399aec64fc6ea9f275`, Model Studio `outputs/multisport-show-preview-producer-v1/context/consumer-contract.py`. No schema replacement or consumer edit is requested.

A valid future source will be derived by the existing common publisher and discovered only after this validator passes. Before that can happen, Model Studio's source owner must supply the exact complete, timestamped, unsealed input export in CURRENT_INPUT_REQUEST.json. Existing cached daily receipts cover only August14–September14. A generic lineup or invented old-team prior cannot fill this gap.

First retained future identity: MIL at PIT, MLBAM823334, September17 16:35UTC/12:35EDT. Its publication deadline is September16 20:00UTC/16:00EDT, freeze20:30UTC/16:30EDT. This is a planning identity, not a frozen forecast or a publication commitment. September16 delivery is already late; nothing was backdated.

Automatic scheduling is inactive. No consumer action is needed now beyond retaining this status. Once a genuine package exists, import its preview forecast ID/content hash exactly, display UNKNOWN starter/lineup statuses and the above limitations, and acknowledge the actual imported identity. No price collection, policy, positions, funding or scheduler changes are granted.

Implementation `21a911557abc9837ed34f47627e7b060da56bebb`; assessed model SHA `27486409ddc1c65220b0da51b7fa120c7bbfa6703437dc16ea8ab00a93044a03`; ASSESSMENT.json SHA `4aedd92bce1c58b7ce7e8b9a01fdb1fd59661aa9a622f67d468d856fc2acc5d8`. Full results and source lineage are in REPORT.md, MODEL_CARD.md and SOURCE_ARTIFACT_INDEX.json. Local root: `C:\Users\james\asp-model-studio\outputs\mlb-show-preview-feasibility-v1`.

Dataset requests0, bytes0, cost$0, sportsbook calls0, AISP writes0. Four public-documentation tool invocations; transport bytes unavailable from that tool. No live contract call was needed while you were offline.

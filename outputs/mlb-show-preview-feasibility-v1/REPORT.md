# MLB preview closeout

**MLB_SHOW_PREVIEW_IMPLEMENTED_AWAITING_CURRENT_INPUTS**

Path C produced a useful, separate team-only research configuration. It passed the frozen winner-probability gate, but no authentic current MLB forecast was published. Model improvement is measured only on reconstructed historical evidence. Complete current input coverage remains required.

| Assessment | Games | Model | Log loss | Binary Brier | AUC | Accuracy | Away MAE | Home MAE | Total MAE |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2022 Development | 2428 | benchmark | 0.69098 | 0.24892 | 0.5000 | 53.34% | 2.524 | 2.429 | 3.504 |
| 2022 Development | 2428 | candidate | 0.68028 | 0.24347 | 0.5921 | 57.54% | 2.459 | 2.383 | 3.495 |
| 2023 Development | 2430 | benchmark | 0.69273 | 0.24979 | 0.5000 | 52.10% | 2.558 | 2.487 | 3.628 |
| 2023 Development | 2430 | candidate | 0.68258 | 0.24481 | 0.5804 | 56.13% | 2.490 | 2.443 | 3.615 |
| 2024 reused Validation | 2429 | benchmark | 0.69239 | 0.24962 | 0.5000 | 52.16% | 2.516 | 2.400 | 3.421 |
| 2024 reused Validation | 2429 | candidate | 0.68216 | 0.24454 | 0.5842 | 56.24% | 2.468 | 2.370 | 3.412 |

The 2024 log-loss difference is -0.010229, with paired calendar-week 95% interval [-0.016017, -0.004589]. Both Development seasons improved. Total-run MAE differs by only -0.009119; its interval crosses zero. No stronger score or calibration claim follows. All personnel inputs are unknown, by design.

The permitted source admits 12,993 games: 2019: 2,429, 2020: 850, 2021: 2,427, 2022: 2,428, 2023: 2,430, 2024: 2,429. Development targets are2021-2023; 2024 is reused Validation; 2019-2020 only supply earlier history. No 2025/2026 result payload or sealed outcome was opened. The fitted configuration, source hashes, actual later acquisition clocks, predictions and uncertainty are retained.

No suitable already-assessed early Gen1 or projected-lineup V18 path was established. The new model uses 16 score-history features, Logistic winner probabilities and independent Poisson expected scores. It has no simulated distribution. Confirmed-lineup V18, all final forecasts and the 17 existing preview packages remain unchanged. The original preview discovery SHA is still `146fd0c48a0dab68fbd7acb279a417c48d989a289034925d58dd86aa69bdee59`.

Current blocker: no complete, admitted current-history owner export matching the frozen features. Available daily receipt dates span2026-08-14 through2026-09-14; they cannot establish a full season, last60 history or prior-season inputs. The already retained identity-only schedule supports nine September17 games. September16 show delivery was already late when work began; no late forecast was created or presented as on-time. September17 deadline remains **September16 16:00 America/New_York /20:00UTC**. See CURRENT_INPUT_REQUEST.json for the bounded source-specific dependency; no new acquisition scope or sealed-data exception was assumed.

The existing framework's exact retained AISP validator is bound at physical SHA `1a6771cb0fbf7c41cdc1e05e09141a7a4db513b82a7993399aec64fc6ea9f275`. The new MLB source adapter passed isolated synthetic-input publication and byte-identical replay using the real fitted model. These are software checks, not genuine forecasts or predictive evidence. Five MLB tests and eight existing preview-framework tests passed; all 2,429 retained Validation predictions reproduced exactly. No broad suites ran.

Historical assembly, three frozen fits and scoring took 14.0seconds. Isolated single-game source/publication/replay test took approximately 0.7seconds. Real full-input prospective latency remains unmeasured; allow up to one minute provisionally, excluding source intake.

Automatic scheduling remains inactive. Future manual entry point: `.venv\Scripts\python.exe scripts\run_mlb_show_preview_feasibility_v1.py produce --inputs <admitted-current-inputs.json>`. It fails closed for missing evidence and after the preview deadline. Eventual activation belongs in the existing owner at 15:15 ET, with delivery by 16:00 ET; no new task or scheduler was created.

Provider dataset calls:0; new dataset bytes:0; sportsbook calls:0; AISP writes:0; spending:$0. Four documentation-tool invocations were made; their transport byte counts were not exposed. EXTERNAL_CALLS.json distinguishes those unknown documentation bytes from zero dataset bytes. Consumer acknowledgement: unavailable, Claude offline; no import is claimed.

Implementation commit: `21a911557abc9837ed34f47627e7b060da56bebb`. Assessment SHA: `4aedd92bce1c58b7ce7e8b9a01fdb1fd59661aa9a622f67d468d856fc2acc5d8`. Reproduce with REPLAY.md. The NFL EPA challenger remains queued and was not started.

The export contains 1,176 complete play records; official batting PA and opposing pitcher BF both sum to 1,173. The three extra records end an inning through a baserunning out, without completing the batter PA.

| Game | Export play records | Official PA | Extra event |
|---|---:|---:|---|
| 823496 | 77 | 76 | pickoff_caught_stealing_2b |
| 823737 | 87 | 86 | pickoff_caught_stealing_2b |
| 824712 | 68 | 67 | caught_stealing_2b |

All 15 exports use the same retained raw hashes as the official summary. Event-type counts, runner movement tallies, inning runs and all pitcher BF/outs/starter flags reconcile. The other 12 game counts agree.

The handoff directory digest matches sorted compact canonical JSON, not physical bytes. Derived file declared hashes match CRLF-to-LF normalized bytes. Physical byte hashes are retained separately. No physical byte identity claim or immutable-path rewrite.

Only COL-DET and SEA-ATH exceed their game PA p95, each 91 vs89. NYM-NYY scores14 total with76 PA near its75.73 mean, so extra PA alone cannot explain every run miss. SEA has home starterBF12/reliefBF43 and10 away runs in innings7+, a localized usage/sequencing question; no frozen BF population exists to diagnose duration bias. High PA may itself result from hits/walks/scoring, and none of these post-scan observations establishes a correction.

Reproduce: `.venv/Scripts/python.exe scripts/reconcile_mlb_v18_september12_postgame_export_v1.py`.

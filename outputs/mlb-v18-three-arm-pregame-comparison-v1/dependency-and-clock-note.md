Exact source snapshot and evidence clocks
========================================

The nested immutable package paths require Git long-path support on this Windows
host. Repository-local `core.longpaths=true` is enabled so ordinary Git and Codex
review commands can read them. No global Git setting was changed.

The six-game declaration pins the working-tree code used for the original
execution. One pre-existing dirty file adds a historical replay authority that
this live-only three-arm path does not use. Its full-file checksum nevertheless
belongs to the declaration, so a clean checkout of the task commit may correctly
reject that original declaration's shared-code checksum. This is not a reason to
include unrelated working-tree edits or weaken verification.

The first published package archives the exact file at:

`C:\Users\james\asp-model-studio\outputs\mlb-v18-three-arm-pregame-comparison-v1\packages\sha256\961b9d5592b83a5ed207e3fbafaa18a3a0300bce30498a2bb56bf5ecd0408337\code\server\sports_current_statcast\mlb_v18_prospective_transform.py`

Verified physical SHA-256:
`d9e55b24ebf8279c846c362c03cb0cbd1497e747edbdb8993b21a3aec9c4d687`
(9,528 bytes). The corresponding exchange package preserves the same
`code/server/sports_current_statcast/mlb_v18_prospective_transform.py` path under
`C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1\three-arm-pregame-comparison-v1\packages\sha256\961b9d5592b83a5ed207e3fbafaa18a3a0300bce30498a2bb56bf5ecd0408337`.

For exact source inspection, use the package's archived dependencies in a
separate disposable checkout, retaining their relative paths and verifying their
recorded hashes. Do not overwrite the active worktree. Reproduce saved results
from the retained immutable receipts and paired arrays; an expired prospective
execution must not be rerun or relabeled. A new eligible future cohort declared
from a clean checkout receives its own code identities and declaration.

The original baseline PA cutoff and the duration input cutoff have separate
meanings. In the first HOU–TB receipt, the unchanged baseline
`sourceCutoff.evidenceAvailableAt` is `2026-09-12T14:47:46.852962+00:00`.
The PA authority retains that exact value. Duration inputs are checked as of the
original baseline snapshot, `2026-09-12T19:43:04.140808+00:00`, as specified in the
frozen declaration. Their maximum accepted source clock is
`2026-09-12T19:34:04.703715+00:00`, from the same snapshot's starter confirmations.
The registered history coverage clocks are `2026-09-11T19:34:26.302782+00:00`.

The duration builder separately verifies observed/available/ingested clocks for
starter identity, coverage authority and eligible history rows against the
original snapshot cutoff, requires completed prior-date histories, and saves
the component cutoff, per-starter clocks and immutable history references in
`metadata.durationInputs`. It does not certify that every component input was
available at the earlier PA feature cutoff. HOU–TB has unresolved starter-history
identities and therefore uses identical baseline fallback for survival; it is
not a duration trial. A supported duration arm must retain and report both
original baseline source cutoff and its own saved duration evidence cutoff.

The registered history scope covers only MLBAM pitchers `664285` and `690279`;
all eight starters in the four currently available baseline games are outside
that scope, as recorded in `survival-support-gap.json`.

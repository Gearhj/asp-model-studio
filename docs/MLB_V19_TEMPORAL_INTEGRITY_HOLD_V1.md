# MLB V19 temporal-integrity hold — V1

Status: **ORIGINAL_COMPARISON_HELD_PENDING_COMPLETION_AVAILABILITY_REPAIR**.
This is a separately versioned successor to
[MLB_V19_STUDY_DECLARATION_V1.md](MLB_V19_STUDY_DECLARATION_V1.md), whose preserved
SHA-256 is `1f1d6424f6e01e200500805cc99eaa99310b155eda501e705164e2bc5f06fb06`.
It changes the permission to proceed, not the original declaration or receipts.
V18 remains retained; no V19 selection, publication or promotion follows.

## Proven defect and its scope

The Development cache assigns all 70 plate appearances of
`game-80cc05dfeda2a0d757afd91f` / `retrosheet:game:BOS202406260` to June 26, 2024.
The 55 plate appearances in innings 3 onward were actually played on August 26.
Excluding the current official game date therefore does not prevent their early
entry into later-June/July histories.

There is one directly demonstrated frozen-baseline training-cutoff violation:
fold 2's nominal July 6, 2024 training prefix includes those August 26 labels.
Its frozen artifact cannot represent information available on July 6. Other
folds have downstream history/feature-provenance concerns; this is **not** a
claim that every fold contains future training labels. Scope must be established
from actual completion availability, not inferred from a shared implementation.

The existing V18 last-100/last-250 histories and new V19 priors use official-date
ordering. Before resumption this can leak unavailable observations. After
resumption, the same ordering can still misorder rolling history even when every
observation is available. These are distinct defects.

Exact replay of the accepted V18 predictions remains a numerical reproduction
result. It is not proof of point-in-time validity. The original 494,432-PA,
6,570-game comparison, failure atlas, regime eligibility and subsequent
candidate selection cannot be represented as temporally validated under the
original declaration while this defect remains unresolved.

## Evidence exists locally; completeness is not yet established

The bounded source inspection found local completion evidence, not a lack of
provider access:

The preserved [timing ledger](../outputs/mlb-v19-current-state-specialists-v1/timing-blocker/sha256/5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b/timing-evidence.json)
(SHA-256 `5bbcdf6c7cae0332b903db18b410a6bae2da05da6871e2125688c6e8394b0e6b`)
records 14 known delayed games / 1,033 safe-cache PAs, plus 61 PAs with unresolved
finalization. Its hypothetical inclusive suspension-to-completion date mask
touches 74,483 validation PAs / 992 games. That mask was **not applied** and is
**not an admissibility certificate**.

- Governed 2023/2024 Retrosheet game logs contain six/three nonempty completion
  fields, respectively; relevant event comments corroborate the dates. The
  current projection had dropped the completion field.
- `NYN202309280` has a blank completion field and comments that the game was not
  completed and its score reverted to the eighth inning. Its 61 safe-cache PAs
  require an explicit finalization/retention disposition; a completion date must
  not be invented.
- The retained 2025 schedule contains four explicit `resumeDate` pairs. Source
  SHA-256: `a8e90faf13a67f04762e019c465e38c66def1d7c4fbc8621c47cb0785fac2948`.
- The safe 2026 metadata projection retains schedule observations but drops
  `resumeDate`/`resumedFrom` and actual completion/release timestamps. Its authority
  SHA-256 is `44c43a48dda5895dcc19417a1c51b18ccdaed9dd83b3c1b8d50826e42be69c4d`.
  Game `824912`, officially June 16, appears as Final on June 16 and 17. The latest
  Final listing is a retrospective day proxy, not a complete resumption census
  or proof of historical publication time. Mixed 2026 source payloads were not
  opened to resolve this question.

## Preserved execution and stopped interpretation

Five new global estimator fits completed before the worker was stopped. Four
fold-1 systems completed their full saved-artifact/reload verification. A fifth
fit completion is not a fifth fully verified fold or system. Scheduled slots,
actual fit starts, completed fits and complete verification remain separate
quantities in execution receipts; no missing count is inferred here.

All original models, predictions, partial artifacts and receipts remain
preserved as superseded or incomplete research evidence. No candidate
performance was inspected for this integrity decision or independent review.
No further global fitting, meta fitting, candidate ranking or simulations are
authorized by this hold. No new tests or model search were run to issue it.

## Smallest defensible next repair

1. Create a versioned Development-only completion/finalization projection from
   the already retained evidence. Resolve the uncompleted-game disposition and
   preserve the missing 2026 resumption metadata without reading sealed OOT
   payloads. Record unknown availability explicitly. This bounded preparatory
   projection is useful even if the comparison remains held.
2. Establish a new baseline/history-repair authority before resumed evaluation:
   define contribution availability and chronological ordering, scope affected
   fitted preprocessing and labels, and freeze outcome-independent common
   eligibility masks. Preserve original fold identities, original artifacts,
   original target and the 56-observation hold. Do not silently call a reduced
   population the original accepted comparison.
3. A conservative next-day completed-game sensitivity may be possible without
   refitting V18: exclude validation dates throughout every known
   suspension-to-completion interval and admit a frozen fold only after **all**
   information used by its training and fitted preprocessing was available.
   For the demonstrated fold-2 case, August 27 is the earliest calendar-day
   candidate under that rule, not an established sufficient cutoff. The rule
   must cover every relevant delayed game and included validation feature
   lineage. It does not require inventing per-PA publication vintages, but must
   disclose its conservative historical reconstruction assumption. Repair new
   histories with completion availability and correct event ordering. Such a
   sensitivity has not been run and cannot support the original five-fold claim
   unless the remaining coverage and decision rule are separately established.
4. If that subset cannot be established, retain the hold. Rebuilding the accepted
   baseline or redesigning folds requires explicit baseline-repair authority;
   do not substitute a new V18 estimator or reopen the model matrix.

Final OOT remains sealed. Operational V18, AISP, selection policy, positions,
settlements and wagering authority are unchanged. This hold concerns the new
historical research comparison, not a retroactive rewrite of accepted outputs.

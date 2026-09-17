# MLB V18 prospective player-prop capture V1

## Disposition

`ACTIVATED_AWAITING_FIRST_ELIGIBLE_CAPTURE`

The passive named-player observer is implemented on the actual MLB V18 owner
lineage, packaged as a content-addressed deployment, verified against a
retained immutable 5,000-draw V18 forecast, and activated through the supported
installer after explicit authorization. The live owner is deployment
`b8cae23dde745d0d5f5cf4d160b4970d2892c38b`. Deployment
`77d39e1ae08e05be82e19bdb0bab21999fba1d3b` and its manifest remain the verified
rollback target.

## Owner reconciliation

The canonical owner is the single Windows task `ASP MLB V18 Research
Publisher`. Its marker is `ASP_MLB_V18_UNATTENDED_OWNER_V1`; it runs as the
current user with S4U, least privilege, a boot trigger after one minute, a
five-minute repeating trigger, `StartWhenAvailable`, and `IgnoreNew` instance
handling. The installed action points at deployment `77d39e1...` and the shared
manifest at `.runtime/mlb-v18-unattended/deployment.json`.

The installed owner sources and the corresponding source-base files were
byte-identical before this change. The successor was built directly from
reviewed Git commit `b8cae23dde745d0d5f5cf4d160b4970d2892c38b`, without switching,
resetting, or modifying the dirty production checkout. The inactive deployment
is:

```
C:\Users\james\asp-model-studio\.deployments\mlb-v18-unattended\b8cae23dde745d0d5f5cf4d160b4970d2892c38b
```

The supported installer's Plan mode passed with one existing canonical owner,
920 hashed code files, the expected S4U identity, and the same five-minute
schedule. The first guarded install request correctly demanded `-Force`; the
non-administrator attempt then failed closed and restored 77d. The explicitly
authorized Administrator `Install -Force` invocation completed with exit code
0 at manifest preparation time `2026-09-17T02:12:03.3202457Z`.

Post-install verification found exactly one owner. The task action and runtime
manifest both bind b8cae23, manifest SHA-256
`3018217630357316ce2069ec57ed76be836dc02bc9756cd2e39ee5c4bde7798c`.
S4U, least privilege, two triggers, `StartWhenAvailable`, `IgnoreNew`, and the
T-60/T-45/T-30/T-15/T-5 timing contract are preserved.

## Capture path

For each future eligible new V18 inference, the existing engine:

1. checks ordinary forecast eligibility and evidence;
2. runs the original 5,000 simulations exactly once;
3. observes already-produced PA events without drawing randomness;
4. validates the ordinary V18 forecast and predicts its exact immutable object
   identity;
5. finalizes and atomically registers the private sidecar before first pitch;
6. writes the ordinary forecast through the unchanged publisher.

The observer retains batter identity, batting-order position, sampled PA class,
hits, total bases, home runs, starting-pitcher strikeouts, PA exposure, and the
forecast/population/model/source bindings needed by the frozen prospective
plan. It adds no draws and does not modify event order, RNG state, simulated
scores, forecast fields, package bytes, or authority.

An unchanged numerical forecast is reused without another 5,000-draw run. If
the reused forecast predates activation and has no capture, it remains
`NO_PROSPECTIVE_CAPTURE_NO_REPLAY_AUTHORIZED`; the system does not manufacture
prospective evidence from a later replay.

Observer, finalization, or storage failure is fail-open for the ordinary V18
forecast and fail-closed for player-prop evidence. The forecast continues and
an atomic failure receipt records the category and forecast binding. A late
sidecar cannot be registered as prospective.

## Evidence and authority

Capture packages are private, content-addressed objects outside Git under:

```
outputs/mlb-v18-player-prop-prospective-v1/
```

Discovery is append-only and keyed by package and forecast identity. Packages
contain no outcomes. Every initial capture is assigned to consecutive,
date-atomic `DEVELOPMENT` only. Validation cannot start until Development is
closed, the method/calibrator is frozen, and a separate authorized closure
receipt exists. Final OOT remains prohibited and sealed; the permanent MLB OOT
quarantine is unchanged.

The authority flags deny AISP display/write, exchange publication, calibration
fit, model promotion, wagering, and outcome access. This work creates evidence
for a later assessment; it creates no player-prop probability authority.

## Forecast invariance and accounting

The production-representative replay used immutable forecast object
`2f07648c51e830736d65ff37689c563bb2195ec767090d14ecc8e905968cbdac`,
the exact saved inputs, seed `20260907`, and 5,000 draws. It compared counters
disabled and enabled and also reconciled both against the saved forecast
population.

- All numerical draw arrays and scalar summaries matched exactly.
- All 382,769 completed PAs reconciled by team and outcome.
- Batter PAs, hits, total bases, and component hit counts reconciled.
- Starter BF plus anonymous-relief BF reconciled to opposing PA exposure.
- The sidecar is 267,423 bytes with SHA-256
  `3259706deca700ac6d0ea1b8779eaae9fdbcc359612b69ad3168dd920924d3d4`.
- The replay receipt is SHA-256
  `eb4badc5856fffcce0a85855e42317f71c9ca16fe4c183b3643a42776da46f31`.
- The two-pass verification took 1,436.587 seconds. Production performs only
  the original single pass.
- Collector arrays allocate exactly 1,510,000 bytes for 5,000 draws. The
  sampled whole verification process peaked at 446,578,688 bytes; this is not
  attributed entirely to the observer.

This verification is comfortably inside a T-45 window even though it performs
two full populations. Actual production retains the existing T-60/T-45/T-30/
T-15/T-5 owner timing contract and runs only one population. No new scheduler
or checkpoint was introduced.

## Focused verification

- New prospective-capture tests: 5 passed.
- Existing current-publisher regressions with their read-only artifact root
  bound to the main repository: 7 passed.
- Earlier combined sidecar/calibration/capture/deployment tests: 18 passed.
- Python AST parse: 6 changed Python files passed.
- `git diff --check`: passed.
- Source secret-pattern scan: no credential material found.
- Prospective verifier: zero packages, which is expected before activation and
  the next eligible new inference.

The failed direct publisher invocation from the clean checkout was an expected
missing-artifact binding, not a product failure; the same tests passed after
binding the existing read-only artifact root. Temporary-path setup errors in an
earlier rerun occurred before test execution and were corrected.

## Operations performed

- Provider calls/bytes/cost by implementation and replay: `0 / 0 / $0`.
- AISP writes: `0`.
- Exchange writes: `0`.
- Outcome reads: `0`.
- Sealed reads: `0`.
- Model fits: `0`.
- Forecast publications caused by this work: `0`.

Natural invocations of the pre-existing 77d owner continued independently and
completed with task result 0 while this work was staged. The pre-activation tick
from `2026-09-17T01:43:56.464505Z` through `01:44:07.005493Z` is
`BOUNDED_TICK_COMPLETED`, SHA-256
`4d788ce1719908f5513100093a4ac91c4b72c80fb89d68911195786a3d9bd7d1`.
It records one `SCHEDULE_IDENTITIES_ONLY` request, zero paid-provider calls,
zero cost, and zero AISP writes; response bytes are not reported in that
receipt. It binds 77d and is not evidence that the successor observer ran.

Two b8cae23 invocations then ran naturally at `02:13:13Z` and `02:18:18Z`.
Windows task result and the immutable launcher receipt both report exit code 0.
The launcher receipt SHA-256 is
`2bdf4f0a907a63550d82a28b4cc69ac95108bbf73a0d96369cb66a4bd1f6e4d9`.
Both ticks authenticated the successor manifest and returned
`NOT_DUE_NO_PROVIDER_OR_MODEL_ACTIVITY`; their tick SHA-256 values are
`a9a1fd2a64a2820af980e135094f57388d9f02aa8c4b42e9dd8887ffd5b74014`
and `3cc12f14a535e01ae79467bf42c03b864a31f97dfa395e9ae096c7d70feaee95`.
This is the correct successful terminal state outside the T-60 window, so a
successor `BOUNDED_TICK_COMPLETED` receipt was not available during this bounded
observation. Neither tick made provider calls, published a forecast, created a
capture, or exercised the observer. No observer failure occurred.

## Remaining dependency

Activation is complete. The first real capture remains dependent on a future
eligible new V18 forecast with complete pregame evidence before first pitch.
The first natural tick inside a governed window should be checked for
`BOUNDED_TICK_COMPLETED`; this observation must not be manufactured by a manual
start. A no-due tick or unchanged pre-activation forecast remains a valid
zero-capture state and is not a rollback condition.

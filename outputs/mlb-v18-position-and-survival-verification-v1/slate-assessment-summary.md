September 12 frozen V18 assessment

| Cohort | Games | Log loss | Brier | CRPS H/A/T/M |
|---|---:|---:|---:|---|
| V18: all eligible finalized | 9 | 0.711244 | 0.258561 | 1.494 / 1.794 / 2.313 / 2.283 |
| V18: funded finalized subset | 5 | 0.712525 | 0.259146 | 1.140 / 2.280 / 2.093 / 2.738 |
| V18: gen1 matched | 9 | 0.711244 | 0.258561 | 1.494 / 1.794 / 2.313 / 2.283 |
| gen1: matched pre-cutoff | 9 | 0.659802 | 0.233395 | Unavailable |
| V18: market matched | 5 | 0.716795 | 0.261179 | 1.925 / 2.324 / 3.075 / 2.768 |
| market: matched pre-cutoff | 5 | 0.652908 | 0.229931 | Unavailable |

On available governed finals V18 has higher mean winner loss than the matched earlier Gen1 and market snapshots. Five funded losses are a selected subset; whole-slate scores are reported separately. Neither correct artifact execution nor these few adverse outcomes establishes a recurring modeling failure or harmless randomness. No tuning, significance threshold, replacement or promotion is selected.

Nine of fifteen governed finals are available; the funded subset has five finalized games and two pending. Gen1 horizons span 7.15–10.14 hours before start versus V18 1.63–2.64 hours. Matched market snapshots span 2.65–24.03 hours before start; they are not closing quotes. Gen1 snapshots retain a stale-roster flag and 27 missing-feature flags. These horizon and input limitations prevent a like-for-like superiority claim.

The actual selected first position was NYY, which lost at home 2–12 to NYM. KC lost away 1–5 to BOS; both latest source-bound finals are revision 1. Position attribution and policy quote evidence are in the separate position audit.

Commands:
- `.venv/Scripts/python.exe scripts/assess_mlb_v18_frozen_slate_20260912_v1.py --score`
- `.venv/Scripts/python.exe scripts/assess_mlb_v18_frozen_slate_20260912_v1.py --comparators`

These commands reuse exact frozen membership and saved database projections if present; they do not refresh finals, simulate or replace forecasts.

Summary SHA256: 240c8e8d1f33c48f79a82b0abdec399e7b2d864a25f967670f2592ac52c3e0b5

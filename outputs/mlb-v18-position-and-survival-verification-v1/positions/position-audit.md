All seven stored positions match their exact immutable V18 forecasts. No model, policy or position was changed.

| Selected team | Side | Status | Model P | Price | Break-even | P minus no-vig | Policy adjusted edge |
|---|---|---|---:|---:|---:|---:|---:|
| NYY | HOME | LOSS | 63.86% | -160 | 61.54% | +4.84 pp | +2.84 pp |
| PIT | AWAY | LOSS | 52.62% | +110 | 47.62% | +7.53 pp | +5.53 pp |
| SF | HOME | LOSS | 46.38% | +160 | 38.46% | +9.35 pp | +7.35 pp |
| LAA | AWAY | LOSS | 49.80% | +115 | 46.51% | +5.06 pp | +3.06 pp |
| KC | AWAY | LOSS | 38.46% | +195 | 33.90% | +6.15 pp | +4.15 pp |
| PHI | AWAY | PENDING | 51.50% | +126 | 44.25% | +9.06 pp | +7.06 pp |
| CWS | AWAY | PENDING | 53.98% | -107 | 51.69% | +4.73 pp | +2.73 pp |

Actual stored first selection is NYY ML -160, not NYM. Studio and consumer agree NYM away/NYY home; retained final is NYM12-NYY2, so the NYY loss is coherent.
KC is away at BOS. Governed final is KC1-BOS5: home-away5-1 and away-home1-5 describe the same result. Existing correctly oriented scoring inputs need no replacement.
All seven use the original baseline V18 PA and transition bindings, not Gen1, survival or transition-challenger forecasts.
Saved decision.edge is raw model minus offered-price break-even. Actual practical-policy adjusted_edge is the penalized selected probability minus saved no-vig market; it is a different quantity.
All fourteen latest retained ordered lineups at decision match the frozen identities/order; saved starter qualification evidence also matches. No selected-side orientation or artifact mismatch is found.
CWS position decimal is rounded to1.9346 while the original quote is1.9345794392523366; break-even and edge reconciliation uses the original quote. Saved adjusted EV uses the rounded policy-selection decimal; raw decision edge/EV use the original quote. Both adjusted EV values remain positive, so this rounding does not explain the selection or loss.

The consumer stores the snapshot capture as its source cutoff. The earlier PA-history evidence cutoff is preserved separately in each original sourceCutoff record; neither is backdated or substituted.

The policy applied a saved two-percentage-point probable-starter penalty, zero lineup/uncertainty penalties, then tested adjusted edge against the saved no-vig market and positive adjusted expected value. The displayed break-even derives from the selected source quote; no-vig disagreement is separate.

This attribution excludes neither losing nor open positions. Full-slate and matched Gen1/market performance are a separate declared analysis. Five losses alone establish neither model failure nor harmless randomness.

Reproduce offline: `.venv/Scripts/python.exe -B outputs/mlb-v18-position-and-survival-verification-v1/positions/verify_positions.py`

Exact captures, code/source identities, clocks and final revisions: position-audit.json. The database capture retains the exact read-only SQL; this replay command makes no database or provider requests.

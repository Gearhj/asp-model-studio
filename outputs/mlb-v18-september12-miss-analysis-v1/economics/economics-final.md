# September 12 decision economics — final evidence update

**All seven positions now have governed final evidence:** six losses and one win, net **−$12.78** on $14.21 staked. PHI lost 2–12; CWS won 6–5. Both agree with the already captured settlements. Earlier economics artifacts are preserved; only the final-availability labels have changed.

The unchanged frozen probabilities imply **3.5660 raw / 3.4260 adjusted expected wins**, and **+$1.7627 / +$1.1006 expected net P&L**. Expectations require correct marginal probabilities, not independence. These are virtual ledger amounts, with no extra fees or slippage assumed.

| Selection | Stake / price | Raw p | Adjusted p | Offered break-even | Saved no-vig p | Adjusted − break-even | Saved adjusted − no-vig | Expected net raw / adjusted | Realized net | Final: away–home / revision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| NYY | $1.04 / -160 | 63.86% | 61.86% | 61.54% | 59.02% | +0.322 pp | +2.844 pp | $0.0392 / $0.0054 | −$1.04 | 12–2 / r2 |
| PIT | $2.48 / +110 | 52.62% | 50.62% | 47.62% | 45.09% | +3.001 pp | +5.527 pp | $0.2604 / $0.1563 | −$2.48 | 3–4 / r2 |
| SF | $2.49 / +160 | 46.38% | 44.38% | 38.46% | 37.03% | +5.918 pp | +7.348 pp | $0.5126 / $0.3832 | −$2.49 | 7–6 / r2 |
| LAA | $2.49 / +115 | 49.80% | 47.80% | 46.51% | 44.74% | +1.288 pp | +3.059 pp | $0.1760 / $0.0690 | −$2.49 | 5–6 / r2 |
| KC | $2.49 / +195 | 38.46% | 36.46% | 33.90% | 32.31% | +2.562 pp | +4.149 pp | $0.3351 / $0.1882 | −$2.49 | 1–5 / r2 |
| PHI | $2.48 / +126 | 51.50% | 49.50% | 44.25% | 42.44% | +5.252 pp | +7.055 pp | $0.4065 / $0.2944 | −$2.48 | 2–12 / r1 |
| CWS | $0.74 / -107 | 53.98% | 51.98% | 51.69% | 49.25% | +0.290 pp | +2.733 pp | $0.0328 / $0.0041 | +$0.69 | 6–5 / r1 |

Offered break-even uses the stored position decimal price. No-vig disagreement is a separate quantity; the saved policy threshold applies to adjusted p minus no-vig p. CWS stored decimal 1.9346 versus exact source 1.9345794392523366 remains preserved, as does its cent-rounded $1.43 gross payout. Saved probability adjustments are the original 2-percentage-point starter penalty, not a new calibration.

Under the explicit conditional assumptions of independent games and true supplied probabilities, the previously computed chance of **at most one win in seven is 5.44% raw / 6.74% adjusted**. Net P&L at most −$12.78 has probability 1.38% / 1.75%, using cent-rounded gross payouts. The earlier five-loss illustration remains 2.84% / 3.47% for that earlier subset.

These probabilities are not proof of bad luck, a significance test, or evidence that the selections were correct. Game dependence and model accuracy remain uncertain. Conditional numerical Monte Carlo SE of roughly 0.7 percentage points per 5,000-draw win estimate is separate from predictive uncertainty; 5,000 draws are not 5,000 observed games.

Reused [economics.json](economics.json), SHA `3bcfc9f6d691dd2acef9c6f98934008e85936a20f3af0aa58cac61531c4776e8`. Current [final-revision game evidence](../final-revision-followup/game-scores.json), captured 2026-09-13T14:54:28.627631+00:00, SHA `1ec3778228d596ee88082639b887ffe6dfc145380763ec9c4a14b4a9939221da`. No expected-value calculation, probability enumeration, database query, scoring, model or simulation was repeated for this note.

Reproduce this presentation update: `.venv/Scripts/python.exe -B outputs/mlb-v18-september12-miss-analysis-v1/economics/render_economics_final.py`

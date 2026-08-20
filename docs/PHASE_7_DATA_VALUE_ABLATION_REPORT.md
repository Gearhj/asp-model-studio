# Phase 7 — Data-Value Ablation Report (Training Volume)

**Branch:** `phase7-advanced-mlb-data-integration` · **Study:** Gate 15A (training-volume) on the Gen-3
base-22 feature view. Selection metric = **2024 validation only**. The 2025 secondary OOT season was
**not scored** (sealed behind `--run-secondary-oot-2025`; default off). 2026 untouched. No champion
promoted; D3/C4 and the frozen Gen-2 view unchanged.

Harness: `scripts/phase7_ablation.py`. Same target, same 22 base features (semantics **proven identical**
to Gen-2 — 549,479 overlapping rows, 0 feature mismatches), same fold-local preprocessing (median impute
fit on development only + fixed-category one-hot for the 3 categorical context features), same two model
families. This isolates the value of additional training rows.

---

## A. Training-volume study — same base 22 features

| Branch | Development | Dev rows | Family | Val 2024 log loss | Δ vs A0 | Top-1 | Macro-F1 |
|---|---|---|---|---|---|---|---|
| **A0** | 2023 | 184,104 | logistic | 1.483693 | — | 0.4520 | 0.0880 |
| **A0** | 2023 | 184,104 | HGB | 1.488036 | — | 0.4518 | 0.0898 |
| **A1** | 2022–2023 | 366,076 | logistic | **1.482535** | **−0.001158** | 0.4525 | 0.0862 |
| **A1** | 2022–2023 | 366,076 | HGB | 1.486241 | −0.001795 | 0.4522 | 0.0890 |
| **A2** | 2021–2023 | 547,808 | logistic | 1.482727 | −0.000966 | 0.4525 | 0.0864 |
| **A2** | 2021–2023 | 547,808 | HGB | **1.485650** | **−0.002386** | 0.4520 | 0.0883 |

**Did more rows help? Yes — consistently, but by a small margin.**

- Every larger-development branch **beats the 2023-only baseline** on 2024 validation, for both families.
- **Logistic winner: A1 (2022–2023), 1.482535.** Adding the prior-blind 2021 season (A2) slightly
  *regresses* logistic vs A1 (+0.000192), because 2021's all-missing prior features dilute the linear
  prior signal.
- **HGB winner: A2 (2021–2023), 1.485650** — the tree model exploits the `*_prior_missing` indicators to
  partition the prior-blind 2021 rows, so it monotonically improves with more rows.
- **Overall best validation model: A1 logistic (1.482535).**
- Effect sizes are ~0.001–0.002 log loss — directionally positive and reproducible, but not
  production-transformative, consistent with the Phase-6H weak-signal finding on the base 22 features.

### Class-conditional log loss (logistic, 2024)

| Class | A0 | A1 | A2 |
|---|---|---|---|
| BIP_OUT | 0.8208 | 0.7981 | **0.7974** |
| STRIKEOUT | **1.4429** | 1.4604 | 1.4623 |
| SINGLE | 1.9552 | **1.9420** | 1.9422 |
| WALK_HBP_CI | **2.2429** | 2.2954 | 2.2972 |
| DOUBLE | **3.1076** | 3.1135 | 3.1122 |
| HOME_RUN | **3.3689** | 3.4443 | 3.4401 |

The dominant **BIP_OUT** class improves most with more rows (better base-rate calibration); several rarer
classes (HR, WALK, K) degrade slightly for the linear model — added rows sharpen the majority-class fit at
a small cost to the tails. This is the mechanism behind the small aggregate gain.

## B. Advanced feature-family study (B0–B7)

**Not run this session — blocked on the advanced Statcast corpus** (pitch-level discipline / contact
quality / arsenal / matchup / workload families), which was designed and availability-matrixed in the Plan
doc but not acquired. When acquired, the B-study starts from the best valid volume branch selected on 2024
(**A1, 2022–2023, logistic**) and adds families sequentially.

## C. Coverage / prior-blindness

- A0/A1: fully prior-valid development. A2: adds 181,732 prior-blind 2021 rows (0 eligible priors — no
  ≤2020 `player_prior`), surfaced honestly via the `*_prior_missing` indicators.
- Making 2021 prior-valid requires acquiring 2020 season priors (Lahman-2020 → `player_prior` 2020) — the
  recommended next data step if 2021 is to contribute cleanly to a linear model.

## D. Runtime

Logistic fits: 102 s (184K) → ~200–300 s (366K–548K). HGB fits: ~6 s each. Parity join: ~seconds over
549,479 rows. Full study (6 fits + parity): ~15 min single-process.

## E. Paid-feed decision (from this evidence)

- **Historical value of more free rows demonstrated:** **yes, but small** (~0.001–0.002 val log loss). It
  is real and free — worth keeping (adopt A1 as the volume baseline for future studies).
- **Does this evidence justify a paid daily feed?** **Not yet.** The base-22 features are near their
  signal ceiling regardless of row count (all model families cluster ~1.48). The likely high-leverage
  lever is **feature richness (advanced Statcast contact-quality / arsenal / discipline)**, not more rows
  of the same 22 features — a **prospective test on the advanced corpus is required** before recommending
  any paid feed.
- **Recommended next data families to evaluate (free first):** Statcast batter contact-quality (EV, barrel,
  hard-hit), pitcher arsenal/shape, plate-discipline (chase/whiff/CSW), and batter×pitcher handedness /
  pitch-type matchup — acquired from Baseball Savant, integrated as the Gen-3 advanced families, then
  ablated (B0–B7) on 2024 before any paid-feed decision.

## F. Winner & practical effect

- **Best validation branch:** A1 (development 2022–2023), logistic, val log loss **1.482535**
  (−0.00116 vs 2023-only). **Not promoted** — informational only.
- **Practical effect:** a small, honest, free validation gain from ~2× development rows; the larger
  opportunity is feature richness, pending the advanced-corpus study.

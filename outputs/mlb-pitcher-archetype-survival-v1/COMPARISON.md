Pitcher-profile and archetype survival comparison

Reused 2023–2024 Development; historical pitch availability is reconstructed from prior event dates, not certified publication vintages. Lower scores are better. All arms use identical supported starts; the frozen HGB remains an operational benchmark.

| Arm | Starts / pitchers | Path NLL | BF CRPS | BF MAE | BF bias | Early-exit Brier | Long-start Brier |
|---|---:|---:|---:|---:|---:|---:|---:|
| FROZEN | 2175 / 270 | 2.673659 | 1.9724 | 2.7660 | -0.1088 | 0.01703 | 0.10286 |
| A | 2175 / 270 | 2.672834 | 1.9626 | 2.7450 | -0.1001 | 0.01669 | 0.10323 |
| B | 2175 / 270 | 2.681120 | 1.9620 | 2.7321 | -0.0749 | 0.01637 | 0.10227 |
| C | 2175 / 270 | 2.684776 | 1.9683 | 2.7388 | -0.0808 | 0.01647 | 0.10245 |

A is a matched refit of the seven existing features; B adds continuous profiles; C additionally adds soft archetypes. CONTINUE/REMOVAL/GAME_END remain distinct. BF scores integrate the reduced pregame process, not full-game rollouts.

| Contrast | Path-NLL difference | 95% whole-game interval | 95% pitcher interval |
|---|---:|---|---|
| A − FROZEN | -0.000825 | [-0.005704, +0.004405] | [-0.005150, +0.004325] |
| B − A | +0.008287 | [-0.005604, +0.022967] | [-0.007907, +0.026105] |
| C − B | +0.003656 | [-0.002821, +0.009703] | [-0.003328, +0.011272] |
| C − A | +0.011942 | [-0.001857, +0.027080] | [-0.003909, +0.028848] |

These paired intervals resample whole games or pitchers; BF rows are not independent observations. Prior assessment exposure and repeated pitcher use limit confirmation claims.

Reproduce without provider access:

```powershell
.venv/Scripts/python.exe -B scripts/run_mlb_pitcher_archetype_survival.py --stage all
```

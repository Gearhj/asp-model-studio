September 13 frozen comparisons

COL–DET's existing AISP official-wire evaluation reports COL 1–DET 8. No game_final_outcomes revision exists at the retained read; these are qualified consumer results, not completed governed study assessments. CIN–MIL was live and had no evaluation.

| Game / arm | Draws | P(home) | Expected away/home | Log loss | Binary Brier | CRPS away/home/total/margin |
|---|---:|---:|---|---:|---:|---|
| COL–DET / V18_BASE | 5000 | 0.6258 | 3.9712/5.0984 | 0.468724 | 0.140026 | 1.567261/1.937243/1.017086/3.866331 |
| COL–DET / V18_SURVIVAL_ONLY | 5000 | 0.6272 | 3.9970/5.1330 | 0.466490 | 0.138980 | 1.586509/1.915655/1.019543/3.861264 |
| COL–DET / V18_TRANSITION_ONLY | 5000 | 0.6256 | 3.9282/5.1096 | 0.469044 | 0.140175 | 1.520415/1.933867/1.023615/3.816305 |
| CIN–MIL / baseline | 5000 | 0.496200 | 4.1116/3.8540 | Pending | Pending | Pending |
| CIN–MIL / accepted | 4722 | 0.493859 | 3.9416/3.6679 | Pending | Pending | Pending |

All COL–DET picks were correctly Detroit. Survival: slightly better winner, home and margin scores; worse away and total CRPS. Transition: slightly worse winner scores; better away/home/margin CRPS, worse total CRPS. No recurring gain established. CIN–MIL retains the CIN pick: 278/5000 excluded (5.56%), 4722 retained. Its result is pending.

UNAVAILABLE: original baseline has no starter/relief counters; no final-bound actual pitcher history for this game. Candidate summaries alone cannot establish allocation improvement.

No research arm advances. Archetype B/C remain closed without advancement.

Run: `.venv/Scripts/python.exe -B scripts/close_mlb_existing_prospective_comparisons_v1.py`

Immutable result: C:\Users\james\asp-model-studio\outputs\mlb-prospective-closeout-and-explanations-v1\objects\sha256\0dfae37cde71206c21fa1a680e7c6e05aaaf50a50fb4d1ad26526eb702187eb8\prospective-closeout.json; SHA256 0dfae37cde71206c21fa1a680e7c6e05aaaf50a50fb4d1ad26526eb702187eb8

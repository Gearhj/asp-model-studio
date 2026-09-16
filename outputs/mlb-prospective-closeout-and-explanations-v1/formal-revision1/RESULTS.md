September 13: formal revision-1 assessment

COL–DET finished 1–8; CIN–MIL finished 4–3. Two distinct prospective games, three research interventions. Every arm uses its exact original frozen population and the same governed final revision within each game.

| Game / arm | N | P(home) | Expected away/home | Log loss | Binary Brier | CRPS away/home/total/margin | Joint energy |
|---|---:|---:|---|---:|---:|---|---:|
| COL–DET / BASELINE | 5000 | 0.625800 | 3.9712/5.0984 | 0.468724 | 0.140026 | 1.567261/1.937243/1.017086/3.866331 | 2.741982 |
| COL–DET / V18_SURVIVAL_ONLY | 5000 | 0.627200 | 3.9970/5.1330 | 0.466490 | 0.138980 | 1.586509/1.915655/1.019543/3.861264 | 2.740247 |
| COL–DET / V18_TRANSITION_ONLY | 5000 | 0.625600 | 3.9282/5.1096 | 0.469044 | 0.140175 | 1.520415/1.933867/1.023615/3.816305 | 2.712896 |
| CIN–MIL / BASELINE | 5000 | 0.496200 | 4.1116/3.8540 | 0.685576 | 0.246214 | 0.664855/0.652306/0.931136/0.957898 | 1.058870 |
| CIN–MIL / SCORE_LIMITED | 4722 | 0.493859 | 3.9416/3.6679 | 0.680939 | 0.243896 | 0.644457/0.608413/0.854517/0.913844 | 1.000716 |

Candidate minus baseline; negative is better for every score below.

| Game / candidate | Δ log loss | Δ binary Brier | Δ CRPS away/home/total/margin | Δ joint energy | Δ absolute margin/total error |
|---|---:|---:|---|---:|---|
| COL–DET / V18_SURVIVAL_ONLY | -0.002235 | -0.001046 | +0.019248/-0.021588/+0.002457/-0.005067 | -0.001736 | -0.008800/+0.060400 |
| COL–DET / V18_TRANSITION_ONLY | +0.000320 | +0.000150 | -0.046846/-0.003376/+0.006529/-0.050027 | -0.029087 | -0.054200/-0.031800 |
| CIN–MIL / SCORE_LIMITED | -0.004637 | -0.002318 | -0.020398/-0.043893/-0.076619/-0.044054 | -0.058154 | -0.016013/-0.356112 |

Survival improves winner scores slightly; transition worsens them slightly. Both have mixed marginal results. CIN score limits improve winner scores, every marginal CRPS and joint energy on this realized game; both configurations already selected CIN correctly. There were zero pick changes. These are individual outcomes, not evidence of recurring improvement or profitability; no arm advances.

Score limits retained 4,722/5,000 draws (278 excluded, 5.56%); fixed limits remain 5 runs per played half-inning and 14 per team per game. The original 5,000-draw baseline and full scoring tail remain unchanged. Existing simulation MCSE is retained in the scoring receipts; it does not bound model error.

Pitcher-allocation improvement remains unavailable: the original baseline lacks starter/relief counters and no exact-final-bound actual pitcher evidence is retained. This does not block whole-game scoring. Prior qualified consumer reports remain unchanged; this is an additive formal completion.

Governed final receipt: `C:\Users\james\asp-model-studio\outputs\mlb-prospective-closeout-and-explanations-v1\formal-revision1\governed-finals.json`, physical SHA-256 `4b5dd5c0aad2c56abd18176fc7576a2c736a5f2a942a37a20e328785fb99cdf0`.
COL–DET: `cd779bf5-e277-4d9c-a631-6eb3e422a0f1`, revision 1. CIN–MIL: `105dc37c-8fbe-4dbf-abf4-a81bfddb2194`, revision 1.

Formal result: `C:\Users\james\asp-model-studio\outputs\mlb-prospective-closeout-and-explanations-v1\formal-revision1\objects\sha256\e8d0a026e77a33264855d78fd16209f0c8e49f2c68e5e8e93d91263cbf013aab\formal-assessment.json`, physical SHA-256 `e8d0a026e77a33264855d78fd16209f0c8e49f2c68e5e8e93d91263cbf013aab`.

Reproduce from retained finals and draws: `.venv/Scripts/python.exe -B scripts/assess_mlb_existing_prospective_finals_v1.py`.
To preserve one-shot artifacts, remove no files: after completion the command verifies the retained receipt instead of resimulation or outcome polling.

# Focused verification

The nine boundary tests passed in two focused executions: the original eight tests, followed by the added midpoint-history test. The empty-uncertainty-cell assertion also passed. These are software checks, not football assessment observations.

The original historical BAL-KC fixture reproduced its complete 200-draw score distribution and score summary exactly; see baseline-reproduction.json. No 2026 game was regenerated for that check.

Preplay-score verification checked all 171,166 supported states against the immediately preceding ordered scoreboard, with zero mismatches. Drive score increments reconcile to all 1,942 final scores. No supported remaining-time value is missing or negative. These receipts preserve their actual verification times.

Final population accounting, representative complete-sequence replay, exact unsupported/zero-weight full-game fallbacks, original artifact preservation and fitted-object hashes are certified by replay-verification.json. The final physical-byte inventory is artifact-index.json.

```powershell
.\.venv\Scripts\python.exe -B scripts\run_nfl_drive_survival_v1.py --stage replay
.\.venv\Scripts\python.exe -B scripts\run_nfl_drive_survival_v1.py --stage verify-preplay
# Optional software-boundary test reproduction; no model assessment is run:
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_nfl_drive_survival.py -v
```

Replay preserves the first verification receipt. It verifies retained bytes and numerical outputs; it does not restamp or publish any forecast.

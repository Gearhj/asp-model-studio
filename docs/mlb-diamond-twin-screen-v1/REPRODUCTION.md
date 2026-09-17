# Reproduction

From the independent worktree, with the existing Model Studio virtual environment:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\run_mlb_diamond_twin_screen.py
C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_mlb_diamond_twin_screen.py -q
```

The runner verifies every registered physical SHA-256 before loading rows, verifies both Silver authority barriers, reads fold 1 / season 2024 only, excludes delayed/unresolved target games, forbids same-date carry-forward, and writes research artifacts to `C:\Users\james\asp-data-staging\mlb\diamond-twin-screen-v1`.

Expected terminal disposition: `NO_MATERIAL_INCREMENTAL_VALUE`.

Expected assessment SHA-256: `5e865281823c62f327b8fde71dab281f34e488daca62e1ca6cea9100f9c5dcc7`.

Expected artifact-index SHA-256: `51b7c0da785ac945db9027669fc35552e2bc5d4bd81fa5579f457686dca948cc`.

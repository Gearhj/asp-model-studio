# Reproduction

Use the isolated source branch and the existing project virtual environment. The command reads only the hash-pinned 2023/2024 sources named in the frozen design and writes research artifacts outside Git.

```powershell
cd C:\Users\james\asp-model-studio-source-mlb-v19-structural
$env:PYTHONDONTWRITEBYTECODE = '1'
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe scripts\run_mlb_v19_structural_innovation.py
```

Focused verification:

```powershell
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_mlb_v19_structural_defense.py -q
```

Expected: four tests pass. A second full runner invocation must leave all eight artifact hashes unchanged. The completed run produced zero changed hashes.

The default external root is `C:\Users\james\asp-data-staging\mlb\structural-innovation-v1`. Do not substitute a new baseline file with the same name; the runner verifies physical SHA-256 before reading it.

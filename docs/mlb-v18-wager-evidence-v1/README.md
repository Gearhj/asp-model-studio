# Retained MLB V18 evidence for wagering-record diagnosis

This read-only extraction uses the reconciled consumer position export as wager authority and exact producer forecast identities as model authority. It does not query a live database, acquire data, execute or fit a model, alter policy, or publish forecasts.

Run from this source worktree with the existing research Python environment:

```powershell
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B scripts\extract_mlb_v18_wager_evidence.py --output C:\Users\james\asp-model-studio\outputs\mlb-v18-wager-evidence-20260918-v1
```

The authority defaults to `C:\Users\james\aisp-analysis\wagering-record-20260918`, with cutoff `2026-09-18T20:15:00Z`. An identity-only date and permanent-quarantine gate runs before opening outcome columns. A protected/missing date or ambiguous identity fails closed. No protected evaluation permission is inferred from this task.

The private table contains selected positions joined to their exact decision-named forecast, plus a separately labeled producer comparison population from the same slate dates. Comparators have no position in the full authority export and use the latest original version evidenced in a retained handoff by kickoff minus 15 minutes. Consumer eligibility and comparator outcomes are not inferred.

The helper verifies exact immutable child hashes, feature snapshots, model byte identities and retained distributions. It never follows raw history/source references or deserializes models. It separates original evidence from diagnostics computed during extraction and absent retention. Passive observer diagnostics, where available, must bind the exact forecast and retain their actual original clocks; retrospective replays never replace missing prospective evidence.

Files under the private output include the CSV/JSONL table, column dictionary, source and join receipts, descriptive support counts, separate-era identities and concise interpretation. Fitted/data/raw/numerical artifacts stay outside Git. No source freeze script or production launcher is called.

Focused verification:

```powershell
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B -m pytest tests/test_mlb_v18_wager_join.py tests/test_mlb_v18_wager_evidence_fields.py -q
```

All experimental recommendations remain proposals. Existing model authority, consumer policy, protected data restrictions and the separate CFB prospective collector are unchanged.

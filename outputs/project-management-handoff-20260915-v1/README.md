# Project-management handoff

Use `HANDOFF.md` as the portable attachment for a new project-management chat. It combines the detailed report with all 35 source links. `REPORT.md` is the narrative without the source appendix; `SOURCE_INDEX.json` retains exact source bytes and SHA-256 hashes. `REPORT_RECEIPT.json` records the repository state and task scope. `VERIFICATION.json` records the focused report checks.

The browser report is a local presentation of the same reviewed content. It does not query model providers or AISP and does not run forecasts. Preview: http://127.0.0.1:4178 while the local server remains running.

Rebuild the browser report from the retained authored snapshot:

```powershell
Set-Location C:\Users\james\asp-model-studio
node C:\Users\james\.codex\plugins\cache\openai-curated-remote\data-analytics\1.0.8\scripts\data-app.mjs build --project-dir outputs/project-management-handoff-20260915-v1/report-app --separate-data
.\.venv\Scripts\python.exe -m http.server 4178 --bind 127.0.0.1 --directory outputs/project-management-handoff-20260915-v1/report-app/dist
```

`prepare_report.py` rebuilds the evidence catalog and section/table snapshot from the Markdown and named retained reports; it does not reassess games. Running it later records a new retrieval clock. It does not automatically overwrite the browser app's stable identity or user presentation.

No operational code, fitted artifact, forecast, exchange package or AISP record was modified. No new commit or model experiment was required for this reporting task. Existing operational pointers may advance independently after this snapshot.

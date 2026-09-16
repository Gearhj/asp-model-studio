# Claude successor verification

Both the V2 handoff and its bound predecessor verify by canonical JSON identity. All seven saved economics records agree with Studio: probabilities, prices, break-even, separate no-vig reference, stakes, payouts and P&L. The full 15-game final index is retained through the predecessor; the seven position final-score/revision identities match Studio. No economics or scores were recomputed.

**Transport qualification:** none of the 15 external derived files matches its declared SHA as raw bytes. Every declared SHA matches after CRLF-to-LF conversion, with identical parsed JSON. External files are untouched. `derived-as-published` preserves their exact bytes; `derived-bound-lf` contains local copies whose physical hashes match the handoff. The receipt records both identities and the explicit conversion. No dedicated V2 schema-specific validator or declared LF-hash allowance was found in the inspected contract/importer paths.

All 15 raw-source descriptors match the already independently verified official captures; no raw feed was reread. The handoff's 1,176 ordered play records must not be silently equated to the independently reconciled 1,173 completed PAs. These are postgame records, not pre-PA forecasts.

The Brier definitions agree with existing scorer code: normalized three-class sum is twice binary Brier only when tie probability is zero and the result is HOME/AWAY. Model-implied price advantages are not proven true edges. The nominal Monte Carlo SE does not quantify model/input error; a deterministic seed alone does not establish independent draws.

Reproduce: `.venv/Scripts/python.exe -B outputs/mlb-v18-september12-miss-analysis-v1/claude-successor/verify_handoff.py`

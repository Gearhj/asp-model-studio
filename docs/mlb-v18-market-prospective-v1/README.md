# Focused operational follow-up and separate market protocol

This source-only change documents and freezes a private prospective protocol. It does not repair the consumer, start collection, install an assessment job, change a model or request provider data.

`PROTOCOL.md` defines the full-population regular-season pilot, exact forecast/price anchors, pregame seal deadlines, original selection labels, fresh two-sided book selection, missing/push/void handling, evidence gates and dated descriptive assessments. `PACKET_SCHEMA.json` describes the required export structure; successful structural validation alone is not evidence that temporal and source rules passed.

`scripts/freeze_mlb_v18_market_protocol.py` writes a content-addressed local instance and refuses to replace an existing freeze. It binds the rule document, schema, model identities and retained feasibility summary. It performs no enrollment or database/provider call.

`scripts/inspect_mlb_market_protocol_feasibility.py` reads only retained schedule/forecast/quote metadata in one read-only AISP database transaction; it does not select scores/outcomes or price values. Its original private snapshot is preserved, and reruns require a new output path. Use AISP's existing Python environment.

`scripts/reconstruct_mlb_v18_uncertainty_diagnostic.py` reads the previously admitted 31-position/model joins and reproduces the consumer scalar arithmetic with retained MC sampling error. It holds original selections fixed and never replays portfolio ranking. Run with the Model Studio environment and a new private `--output-root`; the original diagnostic cannot be overwritten by this source runner.

`scripts/reconstruct_mlb_v18_timestamp_diagnostic.py` verifies the exact retained pregame clocks and source mappings. It requires a new absolute `--output-root` under the original private `outputs/` directory, refuses existing artifacts, and neither connects to AISP nor reads new outcomes.

The retained private delivery roots are:

- `C:\Users\james\asp-model-studio\outputs\mlb-v18-operational-followup-20260918-v1` for reconstructed diagnostics and source citations.
- `C:\Users\james\asp-model-studio\outputs\mlb-v18-market-prospective-v1` for the separate frozen protocol and metadata-only feasibility.

Claude's coordination request is `C:\Users\james\aisp-analysis\wagering-record-20260918\MODEL_FOLLOWUP_REQUEST.md`. A request is not an acknowledgement. The final private receipt records whether a reply and genuine pregame capture existed at closeout; neither may be inferred from a frozen protocol.

Focused verification checks reconstructed original probabilities, adapter field behavior, source clocks/hashes, schema syntax, freeze identities and overwrite refusal. There is no new historical model run or parameter search.

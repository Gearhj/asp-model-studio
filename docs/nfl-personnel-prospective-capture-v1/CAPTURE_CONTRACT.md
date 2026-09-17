# NFL personnel prospective capture contract

`NFL_PERSONNEL_PROSPECTIVE_OWNER_V1` is a data-only, research-only owner for the remainder of the 2026 NFL season. It acquires the six admitted free nflverse release assets: injuries, weekly rosters, depth charts, snap counts, player identity, and draft identity. It does not download schedules. Game identity and kickoff are projected from the registered local Foundation schedule by reading only `game_id`, season, game type, week, date, time, away team, and home team.

The owner may issue at most six HTTP requests in one capture, 28 requests per UTC day, and accept at most 64 MiB per capture. Retained objects may occupy at most 2 GiB. HTTP validators are reused; a 304 response creates a lightweight receipt bound to the predecessor object. A missing current-season asset is recorded as `SOURCE_NOT_PUBLISHED` rather than replaced with older evidence.

Every accepted byte stream is bounded while reading, staged, reread, hashed, and moved to content-addressed storage. Receipts retain URL, actual retrieval time, provider validators, physical SHA-256, bytes, license, disposition, predecessor, and schema fingerprint. Projections use an explicit field allowlist. Schedule outcomes, market fields, weather, and schedule quarterback fields are never read into the projection.

Expected-quarterback states are `CONFIRMED_PREGAME`, `PROBABLE_FROM_CURRENT_DEPTH_CHART`, `AMBIGUOUS_EXPECTED_QUARTERBACK`, and `UNAVAILABLE_EXPECTED_QUARTERBACK`. This source set cannot prove confirmation, so the first state remains unavailable unless a later admitted timestamped confirmation source is added under a new contract. Depth rank 1 plus a matching current weekly roster row yields only `PROBABLE_FROM_CURRENT_DEPTH_CHART`.

Availability is bound separately for `EARLY` (T-48h), `CURRENT` (T-6h), and `FINAL_PREGAME` (T-15m). A capture after a cutoff is `NO_PROSPECTIVE_EVIDENCE_BEFORE_CUTOFF`; it is never backfilled. Complete captured weeks are assigned only to Development. No outcome is read and no Validation, OOT, promotion, forecast, AISP, exchange, decision, or wagering authority is created.

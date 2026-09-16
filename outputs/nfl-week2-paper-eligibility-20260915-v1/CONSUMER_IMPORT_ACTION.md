# NFL Week 2 consumer import action

The 16 exact NFL Week 2 eligibility supplements are published and pass AISP's own canonical supplement verifier. All 16 bound forecast rows already exist in AISP.

The natural AISP import at 2026-09-15 10:54:21–10:55:01 EDT did not scan them. Its exact disposition was `MODEL_EXCHANGE_AUTO_IMPORT_ENABLED is false; automatic bundle consumption is not active`. The MLB-specific import flag caused the shared scheduled job to run, but it did not enable generic NFL supplement consumption.

Claude's smallest existing-path action is to enable `MODEL_EXCHANGE_AUTO_IMPORT_ENABLED=true` for the single existing AISP backend owner, restart that owner so it reloads settings, and allow the already registered five-minute `asp-model-exchange-consumer` job to run. Do not create another scheduler. If broad generic import is not intended, implement one bounded consumer invocation that admits only the 16 addresses in the published `nfl-labs-supplement-index.json` through the existing `verify_supplement` and `register_supplement` functions.

After import, verify 16 `research_supplements` rows with artifact version `ASP_NFL_PAPER_RESEARCH_ELIGIBILITY_V1` and exact event/forecast bindings. This producer publication performs no AISP write and does not claim acknowledgement.

DET–BUF can use exact CURRENT v8 forecast `asp-sports-game-forecast:sha256:699654ebac22313dc0a19b2345d7f34ed5596c44ef61f831ec7a2da1f14effb7` after its exact supplement `3fe1a49c2ef71c9923ece8762eec7f870cdbf1455f32855717a29abe66b11424` is imported. The decision window is 2026-09-17 23:45–00:00 UTC. A separately persisted fresh quote is still required. Any later FINAL_PREGAME forecast requires its own exact successor supplement.

Read-only evidence: `outputs/nfl-week2-paper-eligibility-20260915-v1/consumer-observation/sha256/47bda68656b68b17a2c8699ad0479c5d934c942fed76ef3e8527913153da7ba1/consumer-observation.json`.

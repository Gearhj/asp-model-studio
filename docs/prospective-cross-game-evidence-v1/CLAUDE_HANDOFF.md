# Claude/AISP handoff

No AISP feature, import path or display is authorized by this work. Cross-game display remains fail closed because no historical category passed the frozen gate.

Model Studio now has an inactive producer evidence contract that can later supply:

- exact forecast/package/population identities;
- separate source, creation, publication, discovery, acknowledgement and decision-window clocks;
- explicit tri-state dependency metadata;
- calibration certificate status;
- append-only revision and outcome bindings; and
- frozen-gate readiness counts.

Do not ingest the synthetic fixtures as forecasts. They exist only to validate the contract. Do not treat `READY_FOR_FROZEN_ASSESSMENT` as display or decision authority; the readiness record explicitly sets both assessment flags false.

Schemas are under `docs/prospective-cross-game-evidence-v1/schemas/`. The current sport calibration dispositions are all `UNCERTIFIED`. The sidecar path returned by the library is a proposal only; no exchange object or discovery pointer exists.

Future AISP work requires explicit authorization after producer activation: implement a new research-evidence importer that preserves every clock separately, records consumer acknowledgements as additive receipts, rejects unknown/excluded dependencies for an unrelated-game category, and never enables display until a separately authorized frozen assessment passes.

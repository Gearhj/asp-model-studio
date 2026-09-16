# September 14 MLB V18 producer handoff

Import the five precomputed, unrestricted V18 forecasts from:

`C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\8e3653210e6d062166b1d9b52c784e0b0357f6502ad24d8539fbb578d1983c4f`

Package content address: `8e3653210e6d062166b1d9b52c784e0b0357f6502ad24d8539fbb578d1983c4f`.

Handoff: `handoffs\sha256\e9904df67a922d083fa773b03047af0450f781b1bfa2ee40bf4cf48007c7216a\aisp-handoff.json`; logical SHA-256 `e9904df67a922d083fa773b03047af0450f781b1bfa2ee40bf4cf48007c7216a`; physical SHA-256 `ad449cc74ebc2c7b8e959e1561871618ac54ddb0193eadf27940aa66d503f4da`; 78,573 bytes.

Receipt: `slates\2026-09-14\sha256\d925597447907c7af1edfb1e111c7a020645ea983b1ed78a042d0c02bca4274d\slate-result.json`; logical SHA-256 `d925597447907c7af1edfb1e111c7a020645ea983b1ed78a042d0c02bca4274d`; physical SHA-256 `a69d5b705b70d7e95fb73d19eda5e9b68d4136ba75d5bc9d5df91aa312d47701`; 7,754 bytes.

Manifest physical SHA-256: `72d1e8c8e1b800e0bf183f905ec840d806a8852ed3ea932c878daaf21c7a8f35`; 24,202 bytes.

Run:

```powershell
python -m scripts.mlb_v18_daily_slate import --handoff "C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\8e3653210e6d062166b1d9b52c784e0b0357f6502ad24d8539fbb578d1983c4f\handoffs\sha256\e9904df67a922d083fa773b03047af0450f781b1bfa2ee40bf4cf48007c7216a\aisp-handoff.json" --receipt "C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\8e3653210e6d062166b1d9b52c784e0b0357f6502ad24d8539fbb578d1983c4f\slates\2026-09-14\sha256\d925597447907c7af1edfb1e111c7a020645ea983b1ed78a042d0c02bca4274d\slate-result.json"
```

The package contains LAD-CIN 824465, CWS-CLE 824386, DET-TOR 822765, BAL-NYM 823575 and SF-STL 823006. Each forecast uses the exact immutable object/import identity listed in `audit.json`, 5,000 paired draws, seed 20260907, confirmed ordered lineups and supported starters. Import idempotently by `objectSha256`. This package is the ordinary V18 research-shadow configuration; it contains no Gen 1, score-limited, survival or transition substitution and grants no wagering or promotion authority.

The remaining five games were outside their governing 60-minute checkpoints at the 20:24Z owner pass. Their last input preflight at 19:47Z recorded missing confirmed-lineup evidence; the existing owner remains responsible for later eligible publication. No consumer import is claimed.

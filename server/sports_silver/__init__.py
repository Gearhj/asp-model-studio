"""Phase 7B1 — Governed Silver normalization & identity reconciliation.

Converts the already-landed, QUARANTINED MLB advanced Bronze corpus into normalized, identity-reconciled,
point-in-time governed Silver objects. This package does NOT train models, does NOT make Silver model-eligible, and
does NOT begin feature experiments. Every produced Silver object stays QUARANTINED / NOT_MODEL_ELIGIBLE.

Modules:
  * ``bronze_authority``   — verify the governed Bronze manifest, inventory partitions read-only, prove immutability.
  * ``canonical_ids``      — deterministic, reproducible canonical identity derivation (no randomness / order / clock).
  * ``contracts``          — versioned Silver table/schema + temporal semantic contracts.
  * ``player_identity``    — Chadwick-authoritative canonical player reconciliation (fail-closed on ambiguity).
  * ``game_identity``      — Statcast<->Retrosheet canonical game reconciliation (fail-closed on ambiguity).
  * ``statcast_normalize`` — deterministic Statcast pitch + plate-appearance normalization with lineage.
  * ``silver_publication`` — governed content-addressed, immutable, QUARANTINED Silver publication + verification.
  * ``reconciliation``     — cross-source reconciliation + fail-closed data-quality evidence.
  * ``cli``                — deterministic dependency-ordered normalization runner.
"""

# SPORTS_IDENTITY_BRIDGE_CONSUMER_V1

## Model Studio adapter boundary

Model Studio consumes the companion through three explicit layers:

1. Generic Sports Identity Registry
2. `SPORTS_IDENTITY_BRIDGE_V1` Consumer
3. MLB FD1 Identity Adapter

The V1 companion is not a generic all-sports crosswalk and is never valid on
its own. It is accepted only beside the already registered MLB FD1 dataset
`sports-dataset-1b58d5d1def2c9b7` and project
`sports-project-mlb-fd1-1b58d5d1def2`.

## Frozen trust anchors

- Parent manifest SHA-256:
  `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Parent partition-authority SHA-256:
  `8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437`
- Bridge semantic SHA-256:
  `6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf`
- Alias row-authority SHA-256:
  `ddb828aee391b2f725ba4540a874865963313e6c210f246eacd7bbcf28025661`
- Active-player-dimension row-authority SHA-256:
  `6f30e1b30ca41002d6cbb2dea8b90da5abfad4f62f96237e780fbee518005acf`
- Validation-report SHA-256:
  `caacf363c6cd4205b823b5c0137fb734d9c640de12cdbffcca0e4fed972eef9b`

The consumer rejects any other manifest field set, semantic digest, derived
identity, parent binding, class order, seven-file inventory, file size/hash,
ordered Parquet schema, row checksum, row authority, namespace/source-version
binding, rights control, or validation-report result. Strict UTF-8 JSON,
duplicate-key rejection, normalized package-relative paths, containment, and
link/reparse/hardlink rejection are mandatory.

## Exact consumer joins

For every declared Retrosheet event-family surface, filter
`player-identity-aliases.parquet` to `namespace == "RETROSHEET"`, then join the
physical parent value exactly to `parent_join_key`. Return
`canonical_player_uuid`. Do not trim, change case, add or remove a prefix, use a
fallback namespace, inspect a player name, or perform fuzzy/probabilistic
matching. Null, blank, unresolved, ambiguous, or multiply mapped values fail
closed.

For `player_prior`, join `canonical_player_id` directly to the unique
`active-player-dimension.canonical_player_uuid`. Multiple temporal prior rows
per UUID are permitted; duplicate dimension UUIDs are not.

The adapter must reproduce 4,633,762 declared exact references at a 100%
mapping rate, including every 2023–2025 batter and pitcher reference and all
21,823 player-prior rows. The content-addressed audit remains in ignored
target-local runtime storage. Only its logical URI and metadata enter SQLite or
the browser contract.

## Y-minus-one rule and legitimate missing history

For target season `Y`, batter features use only BATTING-domain evidence and
pitcher features use only PITCHING-domain evidence. Select the latest annual
row satisfying both `season <= Y - 1` and `eligible_from_season <= Y`.
Same-season and future evidence are rejected. A resolved player without an
eligible earlier-domain prior is legitimate missing history, not an identity
failure.

## Portable-population limitation

The immutable dimension has 2,692 portable players while upstream governance
records 2,693, and the primary portable population has 2,070 rather than
2,071. This is accepted only under the frozen proof that the one absent identity
is roster-only, appears in no permitted immutable parent field, affects zero
downstream rows, and was not guessed or manufactured. Any nonzero downstream
impact fails registration.

## Storage and rights

Alias and dimension rows remain lazy, read-only Parquet evidence in the
companion. They are not copied into the application database. Registration
persists metadata, logical URIs, counts, authorities, rights, limitations, and
audit identity only. The registered uses remain local/private model
development, internal derived analytics, and read-only registration; the
companion does not authorize raw public distribution, identity-data resale, or
unrestricted commercial redistribution.

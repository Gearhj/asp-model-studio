# SPORTS_DATASET_CONSUMER_ADAPTER_V1

## Scope

This contract defines ASP Model Studio's first immutable sports-exchange consumer. It is deliberately layered:

1. Generic Sports Dataset Registry
2. `SPORTS_DATASET_MANIFEST_V1` Consumer
3. `asp.mlb.open-data.fd1` Adapter

Version 1 is not represented as a universal multi-sport manifest.

## Approved authority

- Contract: `SPORTS_DATASET_MANIFEST`
- Version: `SPORTS_DATASET_MANIFEST_V1`
- Canonicalization: `SPORTS_CANONICAL_JSON_V1`
- Dataset: `asp.mlb.open-data.fd1`
- Manifest: `sports-dataset-manifest:sha256:1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Semantic SHA-256: `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Partition authority SHA-256: `8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437`

The earlier `6c6cde` metadata package is rejected.

## Canonical identity

The consumer parses strict UTF-8 JSON with duplicate-key and non-finite-number rejection. For semantic identity it deep-copies the manifest, removes exactly `manifest_id`, `manifest_sha256`, `dataset_version_id`, `package_id`, and `published_at`, then serializes with sorted object keys, compact separators, preserved Unicode, and no trailing newline. The computed SHA-256 must equal the approved semantic digest, and every digest-derived identifier is recomputed.

Partition authority is independently computed from the complete all-field partition projection, ordered by package-relative URI. A self-consistent manifest with the wrong external authority is invalid.

## Package validation

Registration fails closed unless all of the following agree with the manifest and frozen adapter expectations:

- exact file inventory and safe relative paths;
- regular-file containment beneath the approved package root;
- bytes and SHA-256 for every declared file;
- Parquet footer row counts, ordered schemas, schema fingerprints, and partition identities;
- family, season, population, and package totals;
- source-right controls, attribution, limitations, temporal rules, and target definitions;
- immutable eight-class plate-appearance probability order.

No exchange file is opened for write, copied into application storage, or exposed by physical path.

## Registration and logical access

The administrator configures `ASP_MODEL_EXCHANGE_ROOT` outside source control. Browser requests identify only the approved adapter; they cannot submit a filesystem path. Registered partitions are exposed as logical URIs beneath:

`asp-model-exchange://datasets/mlb-fd1/sha256-1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49/`

The persistent registry stores metadata, declared partition authority, schemas, populations, folds, rights, and limitations. It never imports the 3.7 million exchange rows.

Analytical reads are server-resolved, read-only, field-allowlisted, bounded, cancellable, and auditable. Validation caching is target-local and is reusable only when manifest identity, relative path, size, modification time, file SHA-256, schema fingerprint, and row count remain bound.

## Security boundary

- registration is administrator-only and idempotent;
- only the fixed approved manifest adapter can be registered;
- only registered, declared partitions can be queried;
- raw physical paths are not returned to the browser;
- arbitrary filesystem SQL and package mutation are prohibited;
- runtime caches and derived artifacts remain beneath ignored ASP Model Studio storage.

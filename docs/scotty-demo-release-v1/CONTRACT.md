# Additive demo declaration and release contract V1

`ASP_RETAINED_CHAMPION_DECLARATION_V1` declares an already selected sport
configuration: sport/competition, exact model identity, training cutoffs,
feature/preprocessing contract, channels/distributions, historical metrics
with population/convention, authority, limitations, artifact references and
valid horizons. Physical references have path, SHA-256 and bytes. Declaration
does not promote a model or grant consumer authority.

`ASP_MULTISPORT_DEMO_RELEASE_V1` contains four declarations, exact forecast
references, separate Show Preview references, operational evidence, blockers,
accounting and no-new-authority flags. Native MLB/NFL/NBA/CFB packages retain
their schemas and identities. AISP can use existing forecast adapters before
adding a release-envelope parser.

Probability units are fractions 0–1; scores are runs/points; clocks are explicitly
timezone-aware. Ridge/Elo/joint channels are not interchangeable. Missing exact
publication clocks remain null, qualified separately from bundle generation.
Totals preserve paired home/away draws and full tails. Over T>L, push T=L,
Under T<L. No actual sportsbook price is implied.

Logical package identity uses existing
`ASP_FILENAME_TO_SHA256_MAP_CANONICAL_JSON_UTF8_V1`: SHA-256 of canonical JSON
mapping normalized relative filenames to their physical SHA-256s. Encoding:
UTF-8, ensure_ascii=False, allow_nan=False, sort_keys=True,
separators=(",", ":"). Byte counts are checked but excluded from the address.
`package-manifest.json` records members; its physical hash is different from
the directory's logical identity. A separate immutable publication receipt
records actual exchange publication after content verification.

Tree: `asp-model-exchange/demo-releases-v1/sha256/<logical identity>/`.
Discovery: `demo-releases-v1/discovery.json`. The publisher locks only this
release tree, verifies staging, renames it, writes publication receipt, then
atomically updates discovery. Earlier discovery bytes remain in
`index-history/`. Identical replay reuses package, receipt and discovery bytes.
Existing sport pointers, forecast objects and owner locks remain unchanged.

CFB/NBA instead retain their **physical index SHA-256** package address. NFL
bundles use their physical bundle hash. Paper supplements use their existing
logical identity excluding supplementSha256. These hashes are not interchangeable.

An additive AISP acknowledgement should identify the release address, every
imported forecast ID/hash, canonical event binding, new/reused/rejected counts,
display checks and actual UTC time. A previous receipt covers only its named
objects/actions. Publication does not establish import, display, quotes,
decision creation, eligibility activation or settlement. No consumer runtime
or scheduler activation is part of this contract.

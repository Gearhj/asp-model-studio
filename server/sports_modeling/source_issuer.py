"""Stage B — governed source issuer authority.

A canonical, content-addressed **server issuer registry** is the sole authority that converts an untrusted Stage-A
physical object into a governed source. The registry is bound through a GENERIC configuration seam
(``ASP_SOURCE_ISSUER_REGISTRY``) — the same mechanism that will later bind a real approved Bronze issuer in a
production deployment. Nothing here inspects a display identifier, filesystem path, helper name, or call context:
resolution begins from a persisted issuer-record content address (or an INDEPENDENTLY reconstructed physical source
identity) and rehashes/reconstructs every relationship before authority is granted. A source whose reconstructed
identity is not bound by a canonical issuer record, whose issuer body is forged, or whose season set is outside the
authorized temporal contract is rejected.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes

# GENERIC production seam. When configured, Stage B enforces canonical server issuer authority for governed source
# resolution. (In a real deployment this points at the governed issuer registry; the acceptance packages point it at
# a runner-owned synthetic registry. Production never inspects the value's provenance — only its content.)
ISSUER_REGISTRY_ENV = "ASP_SOURCE_ISSUER_REGISTRY"

# Only these physically-reconstructable relationships may drive issuer lookup. Display identifiers, paths, helpers,
# and pytest/call context are never lookup inputs.
_SCIENTIFIC_KEYS = ("sourceLogicalSha256", "sourcePhysicalSha256", "sourceSchemaSha256", "rowCount", "seasons")


class SourceIssuerError(RuntimeError):
    """A governed source issuer authority could not be resolved/verified (fail-closed)."""


def _canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def issuer_registry_configured() -> bool:
    return bool(os.environ.get(ISSUER_REGISTRY_ENV, "").strip())


def load_canonical_issuer_registry() -> dict[str, Any] | None:
    """Load + fully self-verify the configured issuer registry, or return None when no registry is configured."""
    raw = os.environ.get(ISSUER_REGISTRY_ENV, "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        raise SourceIssuerError(f"configured source issuer registry is missing: {path}")
    try:
        reg = json.loads(path.read_bytes().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SourceIssuerError(f"source issuer registry is unreadable: {exc}")
    if not isinstance(reg, dict):
        raise SourceIssuerError("source issuer registry is malformed")
    if reg.get("registrySha256") != _canonical_sha({k: v for k, v in reg.items() if k != "registrySha256"}):
        raise SourceIssuerError("source issuer registry is not canonically self-addressed")
    declaration = reg.get("authorityDeclaration") or {}
    if declaration.get("issuerAuthorityRootSha256") != _canonical_sha(
            {k: v for k, v in declaration.items() if k != "issuerAuthorityRootSha256"}):
        raise SourceIssuerError("issuer authority declaration is not self-addressed")
    for contract in (reg.get("contracts") or {}).values():
        if contract.get("sha256") != _canonical_sha({k: v for k, v in contract.items() if k != "sha256"}):
            raise SourceIssuerError("issuer registry scientific contract is not self-addressed")
    upstream = {u.get("upstreamRegistrationSha256") for u in reg.get("canonicalUpstreamRegistrations", [])}
    for record in reg.get("issuerRecords", []):
        if record.get("issuerRecordSha256") != _canonical_sha(
                {k: v for k, v in record.items() if k != "issuerRecordSha256"}):
            raise SourceIssuerError("canonical issuer record is not content-addressed")
        if record.get("issuerAuthorityRootSha256") != declaration.get("issuerAuthorityRootSha256"):
            raise SourceIssuerError("canonical issuer record is not bound to the registry authority root")
        if record.get("canonicalUpstreamRegistrationSha256") not in upstream:
            raise SourceIssuerError("canonical issuer record lacks a canonical upstream registration")
    return reg


def _reconstructed(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sourceLogicalSha256": identity["logical"],
        "sourcePhysicalSha256": identity["physical"],
        "sourceSchemaSha256": identity["schema"],
        "rowCount": int(identity["rowCount"]),
        "seasons": [int(s) for s in identity["seasons"]],
    }


def resolve_source_issuer_authority(*, source_root: Path, registry_entry: Mapping[str, Any],
                                    identity: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve + verify the canonical governed issuer authority for a reconstructed Stage-A object.

    Returns ``{"record": ..., "authorizedSeasons": [...]}`` on success, ``None`` when no registry is configured
    (Stage B not enforced), or raises ``SourceIssuerError`` (missing/forged issuer, divergent relationship, or an
    unauthorized season). ``identity`` is the INDEPENDENTLY reconstructed physical identity
    ``{logical, physical, schema, rowCount, seasons}`` — never a candidate-declared field.
    """
    reg = load_canonical_issuer_registry()
    if reg is None:
        return None
    recon = _reconstructed(identity)
    records = {r.get("issuerRecordSha256"): r for r in reg.get("issuerRecords", [])}
    explicit = (registry_entry or {}).get("issuerRecordSha256")

    if explicit:
        # A persisted issuer-record reference: load its bytes, rehash them, and require it to be a canonical
        # server-issued record (a caller-minted or forged record is never accepted).
        rpath = Path(source_root) / "issuer-records" / "sha256" / str(explicit) / "issuer-record.json"
        if not rpath.is_file():
            raise SourceIssuerError(f"missing issuer record for governed authority reference {explicit!r}")
        try:
            record = json.loads(rpath.read_bytes().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise SourceIssuerError(f"persisted issuer record is unreadable (forged issuer body): {exc}")
        body = {k: v for k, v in record.items() if k != "issuerRecordSha256"}
        if record.get("issuerRecordSha256") != explicit or _canonical_sha(body) != explicit:
            raise SourceIssuerError("persisted issuer record body is not content-addressed (forged issuer body)")
        canonical = records.get(explicit)
        if canonical is None or canonical != record:
            raise SourceIssuerError(
                "persisted issuer record is not a canonical server-issued record (caller-minted issuer authority)")
        record = canonical
    else:
        # No persisted reference: the source is governed only if its INDEPENDENTLY reconstructed physical identity
        # is bound by exactly one canonical issuer record. Otherwise there is no server issuer authority.
        matches = [r for r in reg.get("issuerRecords", []) if all(r.get(k) == recon[k] for k in _SCIENTIFIC_KEYS)]
        if len(matches) != 1:
            raise SourceIssuerError(
                "no canonical server issuer record governs this source; missing issuer / governed authority")
        record = matches[0]

    for key in _SCIENTIFIC_KEYS:
        if record.get(key) != recon[key]:
            raise SourceIssuerError(
                f"issuer record relationship {key} diverges from the reconstructed source (forged/mismatched parent)")

    temporal = (reg.get("contracts") or {}).get("temporal") or {}
    if record.get("temporalContractSha256") != temporal.get("sha256"):
        raise SourceIssuerError("issuer record is not bound to the canonical temporal contract")

    authorized = sorted(int(s) for s in temporal.get("authorizedSeasons", []))
    unauthorized = sorted(s for s in recon["seasons"] if s not in set(authorized))
    if unauthorized:
        bad = ", ".join(str(s) for s in unauthorized)
        raise SourceIssuerError(
            f"UNAUTHORIZED_SEASON: issuer season(s) {bad} are outside the authorized {authorized[0]}-{authorized[-1]} "
            "temporal contract")
    return {"record": record, "authorizedSeasons": authorized}

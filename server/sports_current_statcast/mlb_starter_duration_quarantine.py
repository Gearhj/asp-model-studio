"""Exact prospective source exception and permanent whole-game OOT exclusions.

No model, source payload or sealed evaluation file is opened here. Future OOT
readers must filter identity metadata before accessing any evaluation payload.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from server.sports_silver.canonical_ids import canonical_game_id

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "server/artifacts/governance/mlb-final-oot-quarantine-v1.json"
AUTHORITY_POINTER = ROOT / "outputs/mlb-starter-duration-paired-research-v1/intake/protected-source-authority.json"
SIX_AUTHORITY_POINTER = AUTHORITY_POINTER.with_name("protected-six-game-authority-v2.json")
PURPOSE = "CURRENT_HGB_STARTER_HISTORY_FUTURE_FORECAST_ONLY"
ALLOWED = frozenset({("664285", 823343, "2026-08-17"), ("664285", 824235, "2026-08-24"), ("690279", 822693, "2026-08-25")})
SIX_ALLOWED = frozenset({("687312", 823182, "2026-08-16"), ("687312", 824316, "2026-08-22"),
                         ("687312", 822694, "2026-08-27"), ("695549", 824237, "2026-08-14"),
                         ("695549", 823342, "2026-08-19"), ("695549", 824233, "2026-08-25")})
ORIGINAL_LEDGER_SHA = "59ce1dccab97c520c4c3007281a2597cb89fb5d0ae8007ae89a09f008d8a495a"
ORIGINAL_AUTHORITY_SHA = "ff44954b71645132efc4509bb5d0582f1bb4de25a86b706e58491a9f609119d5"
SIX_USER_GRANT_SHA = "a9c2275d19a1e0012d8afd3afb4353752343f0dc636319040c0a218b15c89057"
LEDGER_ARCHIVE = LEDGER.parent / "mlb-final-oot-quarantine-history/sha256"


def reference(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def verified_json(ref):
    if reference(ref["path"]) != ref:
        raise ValueError("PROSPECTIVE_EXCEPTION_REFERENCE_MISMATCH")
    return json.loads(Path(ref["path"]).read_bytes())


def quarantine_ledger():
    ledger = json.loads(LEDGER.read_bytes())
    tuples = {(g["authorizedPitcherMlbamId"], g["mlbamGamePk"], g["gameDate"]) for g in ledger["games"]}
    if (tuples not in (ALLOWED, ALLOWED | SIX_ALLOWED) or len(ledger["games"]) != len(tuples) or ledger.get("permanent") is not True
            or ledger.get("reason") != "PROSPECTIVE_FEATURE_CONSTRUCTION"
            or ledger.get("scope") != "ENTIRE_CORRESPONDING_GAMES_ALL_PLAYERS_ALL_COMPONENTS"
            or any(g["canonicalGameId"] != canonical_game_id(g["mlbamGamePk"]) for g in ledger["games"])):
        raise ValueError("PERMANENT_GAME_QUARANTINE_INVALID")
    if tuples == ALLOWED:
        if SIX_AUTHORITY_POINTER.exists():
            raise ValueError("REGISTERED_SIX_GAME_QUARANTINE_CANNOT_BE_REMOVED")
        if reference(LEDGER)["sha256"] != ORIGINAL_LEDGER_SHA:
            raise ValueError("ORIGINAL_QUARANTINE_CHANGED")
    else:
        predecessor = ledger.get("predecessor") or {}
        expected = LEDGER_ARCHIVE / ORIGINAL_LEDGER_SHA / "quarantine.json"
        if predecessor.get("path") != str(expected) or predecessor.get("sha256") != ORIGINAL_LEDGER_SHA:
            raise ValueError("APPEND_ONLY_QUARANTINE_PREDECESSOR_REQUIRED")
        old = verified_json(predecessor)
        if ledger["games"][:3] != old["games"]:
            raise ValueError("ORIGINAL_WHOLE_GAME_EXCLUSIONS_CHANGED")
        grant = ledger.get("userAuthorization") or {}
        if grant.get("sha256") != SIX_USER_GRANT_SHA or reference(grant["path"]) != grant:
            raise ValueError("EXACT_SIX_GAME_USER_AMENDMENT_REQUIRED")
    return ledger


def load_exception_authority(authority_ref=None):
    """Original pilot refs remain valid after the append-only six-game grant."""
    original = json.loads(AUTHORITY_POINTER.read_bytes())
    supplemental = json.loads(SIX_AUTHORITY_POINTER.read_bytes()) if SIX_AUTHORITY_POINTER.exists() else None
    pointer = original if authority_ref is None else authority_ref
    if pointer not in (original, supplemental):
        raise ValueError("UNREGISTERED_PROTECTED_SOURCE_AUTHORITY")
    path = Path(pointer["path"]).resolve()
    if path != AUTHORITY_POINTER.parent / "objects/sha256" / (pointer["sha256"] + ".source-amendment.json"):
        raise ValueError("EXCEPTION_AUTHORITY_OUTSIDE_IMMUTABLE_NAMESPACE")
    authority = verified_json(pointer)
    ledger = quarantine_ledger()
    expected = ALLOWED if pointer == original else SIX_ALLOWED
    declared_quarantine = authority.get("quarantineRef") or {}
    if pointer == original:
        if pointer["sha256"] != ORIGINAL_AUTHORITY_SHA or declared_quarantine.get("sha256") != ORIGINAL_LEDGER_SHA:
            raise ValueError("ORIGINAL_PILOT_SOURCE_AUTHORITY_CHANGED")
        # Its historical descriptor names the live path. Read its preserved
        # bytes from the archive after the current ledger advances.
        original_path = LEDGER if reference(LEDGER)["sha256"] == ORIGINAL_LEDGER_SHA else LEDGER_ARCHIVE / ORIGINAL_LEDGER_SHA / "quarantine.json"
        original_ref = reference(original_path)
        if original_ref["sha256"] != ORIGINAL_LEDGER_SHA or original_ref["bytes"] != declared_quarantine.get("bytes") or declared_quarantine.get("path") != str(LEDGER):
            raise ValueError("PILOT_QUARANTINE_PREDECESSOR_UNAVAILABLE")
    else:
        grant = authority.get("userAuthorizationRef") or {}
        if (declared_quarantine != reference(LEDGER) or grant.get("sha256") != SIX_USER_GRANT_SHA
                or reference(grant["path"]) != grant or authority.get("maxNewRequests") != 6
                or authority.get("maxNewOriginalBytes") != 50331648
                or authority.get("sourceCostUsdCeiling") != 0):
            raise ValueError("EXACT_SIX_SOURCE_SCOPE_OR_BUDGET_CHANGED")
    current_tuples = {(g["authorizedPitcherMlbamId"], g["mlbamGamePk"], g["gameDate"]) for g in ledger["games"]}
    if (authority.get("purpose") != PURPOSE or not expected <= current_tuples
            or {(str(g["pitcherMlbamId"]), int(g["gamePk"]), g["gameDate"]) for g in authority["allowedTuples"]} != expected
            or authority.get("evaluationAllowed") is not False or authority.get("sealedEvaluationFilesMayBeRead") is not False):
        raise ValueError("PROSPECTIVE_SOURCE_AMENDMENT_INVALID")
    return {**authority, "authorityRef": pointer, "quarantineRef": declared_quarantine,
            "currentQuarantineRef": reference(LEDGER), "quarantine": ledger}


def assert_prospective_source_allowed(pitcher_mlbam_id, game_pk, game_date, *, authority_ref=None):
    key = (str(pitcher_mlbam_id), int(game_pk), str(game_date)[:10])
    if authority_ref is None and key in SIX_ALLOWED:
        if not SIX_AUTHORITY_POINTER.exists():
            raise ValueError("SIX_GAME_AMENDMENT_NOT_RECORDED")
        authority_ref = json.loads(SIX_AUTHORITY_POINTER.read_bytes())
    authority = load_exception_authority(authority_ref)
    allowed = {(str(g["pitcherMlbamId"]), int(g["gamePk"]), g["gameDate"]) for g in authority["allowedTuples"]}
    if key not in allowed:
        raise ValueError("PROTECTED_GAME_OUTSIDE_EXACT_SOURCE_EXCEPTION")
    return authority


def final_oot_eligible_key_mask(canonical_game_ids):
    """Identity-only gate; entire games, never only a selected pitcher's rows."""
    ledger = quarantine_ledger()
    denied = {g["canonicalGameId"] for g in ledger["games"]}
    denied.update(f"mlbam:game:{g['mlbamGamePk']}" for g in ledger["games"])
    denied.update(str(g["mlbamGamePk"]) for g in ledger["games"])
    keys = list(canonical_game_ids)
    if any(key is None or not str(key).strip() for key in keys):
        raise ValueError("FINAL_OOT_GAME_IDENTITY_REQUIRED")
    return [str(key) not in denied for key in keys]


def require_reduced_final_oot_report(canonical_game_ids, report):
    """Fail closed before any future comparison/component/calibration report."""
    if not all(final_oot_eligible_key_mask(canonical_game_ids)):
        raise ValueError("PERMANENTLY_QUARANTINED_GAME_IN_FINAL_OOT")
    if (report.get("quarantineRef") != reference(LEDGER)
            or report.get("cohortStatus") != "REDUCED_FINAL_OOT_AFTER_PROSPECTIVE_FEATURE_CONSTRUCTION"
            or report.get("originalUntouchedFinalOot") is not False):
        raise ValueError("REDUCED_FINAL_OOT_DISCLOSURE_REQUIRED")

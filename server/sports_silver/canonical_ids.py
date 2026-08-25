"""Deterministic canonical identity derivation (Phase 7B1, Section 23).

Canonical identifiers are DETERMINISTIC and STABLE: the same governed source identity material always yields the same
canonical id on every rerun, and different real-world entities never collapse merely because names match. No random
UUID, Python object identity, processing/traversal order, wall-clock, or display-name-alone is ever an input.

Scheme (``ASP_MLB_CANONICAL_ID_V1``): a canonical id is ``{namespace}-{sha256(contract | namespace | components)[:24]}``
where ``components`` are the ordered STABLE GOVERNED identity material for that entity (e.g. the Chadwick register key
for a player, the MLBAM game_pk for a game). The contract + namespace are mixed in so ids from different namespaces
never collide even on identical material.
"""
from __future__ import annotations

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes

CANONICAL_ID_CONTRACT = "ASP_MLB_CANONICAL_ID_V1"


def canonical_id(namespace: str, *components: object) -> str:
    if not namespace or any(c is None or str(c).strip() == "" for c in components):
        raise ValueError(f"canonical id for {namespace!r} requires non-empty governed components, got {components!r}")
    payload = canonical_json_bytes([CANONICAL_ID_CONTRACT, namespace, [str(c) for c in components]])
    return f"{namespace}-{sha256_bytes(payload)[:24]}"


def canonical_player_id(chadwick_key_person: str) -> str:
    """Bind to the Chadwick register key ``key_person`` — the authoritative cross-source person identity."""
    return canonical_id("player", chadwick_key_person)


def canonical_game_id(mlbam_game_pk: object) -> str:
    """Bind to the MLBAM ``game_pk`` — the authoritative modern game identity."""
    return canonical_id("game", mlbam_game_pk)


def canonical_retro_game_id(retrosheet_game_id: str) -> str:
    """Canonical game identity for a Retrosheet-only game (no MLBAM game_pk); recorded distinctly from an MLBAM game."""
    return canonical_id("game", f"retro:{retrosheet_game_id}")


def canonical_team_id(team_abbrev: str) -> str:
    """Bind to the (2019-2024 window-stable) team abbreviation; franchise-alias handling is recorded in dim_team."""
    return canonical_id("team", team_abbrev.strip().upper())


def canonical_park_id(venue_key: object) -> str:
    return canonical_id("park", venue_key)


def canonical_pa_id(canonical_game: str, at_bat_number: object, batter_canonical: str) -> str:
    """Deterministic plate-appearance identity from stable governed components (Section 43): the canonical game, the
    source at-bat sequence, and the canonical batter — NEVER outcome, event text, processing order, or a random id."""
    return canonical_id("pa", canonical_game, at_bat_number, batter_canonical)


def canonical_pitch_id(canonical_game: str, at_bat_number: object, pitch_number: object) -> str:
    """Deterministic pitch identity from the validated Statcast natural key (Section 44)."""
    return canonical_id("pitch", canonical_game, at_bat_number, pitch_number)

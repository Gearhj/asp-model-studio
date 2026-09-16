"""Separate, outcome-free Development completion-date diagnostic projections.

This module is deliberately not imported by frozen V18 inference. Historical
completion dates and observed source-publication timestamps are different facts.
Date reconstruction is opt-in and never certifies a fitted model or a metric.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

SCHEMA = "MLB_V18_DEVELOPMENT_COMPLETION_AUTHORITY_V1"
SAFE_START, SAFE_END = "2023-03-30", "2026-08-06"


def project_contributions(rows: pd.DataFrame, authority: pd.DataFrame) -> pd.DataFrame:
    """Attach a declared date-level lower eligibility bound without changing events.

    Known date => strictly later calendar date, not an invented release timestamp.
    Uncertified 2026 and reverted/uncompleted games remain unknown and excluded.
    """
    required = {"canonicalGameId", "eventDate", "completionDate", "timingStatus", "observedPublicationAt"}
    if not required.issubset(authority) or authority.canonicalGameId.duplicated().any():
        raise ValueError("Unique complete timing authority is required")
    if not {"canonicalPaId", "canonicalGameId", "game_date"}.issubset(rows) or rows.canonicalPaId.duplicated().any():
        raise ValueError("Unique Development PA identities are required")
    if not rows.game_date.astype(str).between(SAFE_START, SAFE_END).all():
        raise ValueError("Physically isolated Development dates are required")
    result = rows.merge(authority, on="canonicalGameId", how="left", validate="many_to_one", sort=False)
    if result.eventDate.isna().any() or not result.game_date.astype(str).eq(result.eventDate).all():
        raise ValueError("Every PA must match its original event identity/date")
    if result.completionDate.notna().any():
        known = result.completionDate.notna()
        if (result.loc[known, "completionDate"] < result.loc[known, "eventDate"]).any():
            raise ValueError("Completion date precedes event date")
    result["historyContributionNotBeforeDate"] = result.completionDate.map(
        lambda d: (date.fromisoformat(d) + timedelta(days=1)).isoformat() if pd.notna(d) else None)
    result["reconstructedDateEligible"] = result.completionDate.notna()
    result["observedPublicationAvailable"] = result.observedPublicationAt.notna()
    return result


def training_prefix_mask(projected: pd.DataFrame, cutoff_exclusive: str, *, allow_reconstructed_date: bool = False) -> np.ndarray:
    """Fail closed by default; explicit diagnostic mode allows known date proxies.

    cutoff_exclusive is a calendar date. Completion must precede that date.
    Thus BOS June26/Aug26 never contributes to a July7-exclusive training prefix.
    No actual timestamp is fabricated from a game date or retrieval timestamp.
    """
    date.fromisoformat(cutoff_exclusive)
    allowed = projected.completionDate.notna() & projected.completionDate.fillna("9999-12-31").lt(cutoff_exclusive)
    if not allow_reconstructed_date:
        allowed &= projected.observedPublicationAt.notna()
        timestamps = pd.to_datetime(projected.observedPublicationAt, utc=True, errors="raise")
        allowed &= timestamps.lt(pd.Timestamp(cutoff_exclusive, tz="UTC"))
    return allowed.to_numpy(dtype=bool)


def contribution_day_blocks(projected: pd.DataFrame, entity: str, cutoff_exclusive: str) -> pd.DataFrame:
    """Return known, strictly available whole-game blocks grouped by completion day.

    Ordering is a partial order: same-completion-date games deliberately share a
    bucket. No fabricated within-day ordering or exact last-N-PA window is given.
    """
    take = training_prefix_mask(projected, cutoff_exclusive, allow_reconstructed_date=True)
    result = projected.loc[take].groupby([entity, "canonicalGameId", "eventDate", "completionDate"], dropna=False).size().reset_index(name="paCount")
    result["completionDayRank"] = result.groupby(entity).completionDate.rank(method="dense").astype(int)
    result["withinDayOrderUnknown"] = result.groupby([entity, "completionDate"]).canonicalGameId.transform("nunique").gt(1)
    return result.sort_values([entity, "completionDate", "canonicalGameId"], kind="stable").reset_index(drop=True)


def potential_prior_exposure(projected: pd.DataFrame, delayed_records: list[dict], entity: str) -> np.ndarray:
    """Outcome-free conservative exposure, not a count of numerical feature changes.

    The whole delayed game is withheld through completion. Earlier finished PAs
    may therefore be overcounted intentionally. Unknown completion stays unknown.
    """
    exposed = np.zeros(len(projected), dtype=bool)
    for item in delayed_records:
        game_rows = projected[projected.canonicalGameId.eq(item["canonicalGameId"])]
        if game_rows.empty:
            continue
        entities = set(game_rows[entity].dropna())
        temporal = projected.game_date.gt(item["gameDate"]) & projected.game_date.le(item["completionDateProxy"])
        exposed |= (temporal & projected[entity].isin(entities)).to_numpy()
    return exposed


def interdate_reorder_impact(projected: pd.DataFrame, entity: str) -> dict:
    """Count proven reversed entity/game blocks without assuming PA or same-day order.

    A before B by original event date and A after B by completion date proves a
    reversal. Equal completion days are ambiguous, not silently tie-broken.
    Includes both moved delayed-game blocks and displaced intervening blocks.
    """
    known = projected[projected.completionDate.notna()]
    blocks = known.groupby([entity, "canonicalGameId", "eventDate", "completionDate"], dropna=False).size().reset_index(name="paCount")
    delayed = blocks[blocks.completionDate.gt(blocks.eventDate)]
    by_entity = {key: value for key, value in blocks.groupby(entity, dropna=False)}
    affected, ambiguous, pairs = set(), set(), set()
    for source in delayed.itertuples(index=False):
        key = getattr(source, entity)
        group = by_entity[key]
        later = group[group.eventDate.gt(source.eventDate)]
        for candidate in later.itertuples(index=False):
            a, b = (key, source.canonicalGameId), (key, candidate.canonicalGameId)
            if candidate.completionDate < source.completionDate:
                affected.update((a, b))
                pairs.add((key, source.canonicalGameId, candidate.canonicalGameId))
            elif candidate.completionDate == source.completionDate:
                ambiguous.update((a, b))
    selected = np.array([(getattr(r, entity), r.canonicalGameId) in affected for r in known.itertuples(index=False)])
    return {"entity": entity, "knownDateRows": len(known), "reversedBlockPairs": len(pairs),
            "entityGameBlocksWithProvenInterdateReversal": len(affected),
            "paRowsInReversedBlocks": int(selected.sum()),
            "gamesInReversedBlocks": int(known.loc[selected, "canonicalGameId"].nunique()),
            "sameCompletionDayAmbiguousEntityGameBlocks": len(ambiguous),
            "affectedPaIds": known.loc[selected, "canonicalPaId"].tolist(),
            "exactLastNWindowValuesRebuilt": False,
            "interpretation": "PROVEN_PARTIAL_ORDER_REVERSAL_NOT_EXACT_PA_RANK_OR_NUMERICAL_FEATURE_DELTA"}

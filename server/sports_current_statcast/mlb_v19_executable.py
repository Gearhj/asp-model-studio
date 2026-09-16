"""Aggregate saved V19 research inference dependencies without publication.

Exact Development-fixture execution is separate from prospective readiness.
This module does not retrieve sources, open datasets, fit parameters, publish a
forecast, or grant AISP execution/wagering authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from server.sports_modeling.metrics import PA_CLASS_ORDER
from .mlb_v19_meta import GLOBAL_ORDER, ENSEMBLE_NAMES, MetaSystem
from .mlb_v19_models import CandidatePipeline, predict_estimator


def utc(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("An explicit timezone is required")
    return parsed.astimezone(timezone.utc)


def prospective_readiness(rows: pd.DataFrame, authority: Mapping, ordered_raw_features: Sequence[str], *, as_of_utc) -> dict:
    """Fail closed on absent source composition, clocks, history or identities.

    The historical Development cache is not a current source package. A declared
    no-observation state cannot substitute for missing/stale history coverage.
    This check describes necessary input conditions; it is not a publisher or a
    claim that the currently running V18 source path already supplies them.
    """
    now = utc(as_of_utc)
    blockers = []
    def block(code, **detail):
        blockers.append({"reason": code, **detail})
    if len(ordered_raw_features) != 246 or len(set(ordered_raw_features)) != 246:
        block("FROZEN_246_RAW_FEATURE_CONTRACT_DIFFERS")
    missing = sorted(set(ordered_raw_features) - set(rows.columns))
    if missing:
        block("RAW_FEATURES_MISSING", fields=missing)
    if rows.empty:
        block("NO_PREGAME_ROWS")
    if authority.get("schemaVersion") != "MLB_V19_PROSPECTIVE_INPUT_AUTHORITY_V1":
        block("CURRENT_V19_SOURCE_COMPOSITION_AUTHORITY_NOT_IMPLEMENTED_OR_SUPPLIED")
    if list(authority.get("orderedRawFeatures", [])) != list(ordered_raw_features):
        block("CURRENT_SOURCE_FEATURE_ORDER_DIFFERS")
    if authority.get("historicalTemplatesBorrowed") is not False or authority.get("genericImputation") is not False:
        block("NO_HISTORICAL_TEMPLATE_OR_GENERIC_IMPUTATION_PROOF")
    sources = authority.get("sourceArtifacts", [])
    if not sources or any(not ref.get("sha256") or not ref.get("bytes") for ref in sources):
        block("IMMUTABLE_SOURCE_CHECKSUM_LINEAGE_MISSING")
    events = authority.get("events", [])
    event_ids = {str(event.get("canonicalGameId")) for event in events}
    row_ids = set(rows["canonicalGameId"].astype(str)) if "canonicalGameId" in rows else set()
    if not events or len(event_ids) != len(events) or row_ids != event_ids:
        block("EVENT_IDENTITY_MISMATCH")
    for name in ("batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "battingTeamId", "fieldingTeamId"):
        if name not in rows or rows[name].isna().any() or rows[name].astype(str).str.strip().eq("").any():
            block("PLAYER_OR_TEAM_IDENTITY_MISSING", field=name)
    for event in events:
        identifier = str(event.get("canonicalGameId"))
        try:
            cutoff, start = utc(event["evidenceCutoff"]), utc(event["scheduledStartUtc"])
            if cutoff > now or now >= start or cutoff >= start:
                block("EVENT_NOT_CURRENTLY_PREKICKOFF_WITH_PREGAME_CUTOFF", event=identifier)
            day = date.fromisoformat(event["officialGameDate"])
            if date(2026, 8, 14) <= day <= date(2026, 8, 27):
                block("FINAL_OOT_EVENT_EXCLUDED", event=identifier)
            if str(event.get("status")).upper() not in {"SCHEDULED", "PREGAME", "PRE_GAME"}:
                block("EVENT_NOT_SCHEDULED_PREGAME", event=identifier)
            history = event.get("semanticHistory", {})
            required_through = (day - timedelta(days=1)).isoformat()
            if (history.get("completeThrough") != required_through or history.get("coverageComplete") is not True
                or history.get("missingDates") != [] or history.get("sourceFailure") is not False):
                block("SEMANTIC_HISTORY_NOT_COMPLETE_THROUGH_PRIOR_LOCAL_DATE", event=identifier,
                      requiredThrough=required_through, suppliedThrough=history.get("completeThrough"))
            if history.get("allPriorRegisteredSeasonsComplete") is not True or history.get("domainCoverage") != ["BATTER", "PITCHER", "BATTING_TEAM", "FIELDING_TEAM"]:
                block("MULTISEASON_SEMANTIC_HISTORY_AUTHORITY_INCOMPLETE", event=identifier)
            for key in ("observedAt", "availableAsOf", "ingestedAt"):
                if key not in history or utc(history[key]) > cutoff:
                    block("SEMANTIC_HISTORY_SOURCE_CLOCK_NOT_PREGAME", event=identifier, clock=key)
            fields = event.get("fieldEvidence", {})
            if set(fields) != set(ordered_raw_features):
                block("PER_FIELD_SOURCE_PROVENANCE_INCOMPLETE", event=identifier)
            for name, evidence in fields.items():
                if not evidence.get("sourceIdentity") or evidence.get("sourceFailure") is not False:
                    block("FIELD_SOURCE_FAILURE_OR_UNKNOWN", event=identifier, field=name)
                    continue
                observed, available, retrieved = (utc(evidence[key]) for key in ("observedAt", "availableAsOf", "ingestedAt"))
                if observed > available or available > cutoff or retrieved > cutoff:
                    block("FIELD_SOURCE_CLOCK_NOT_PREGAME", event=identifier, field=name)
        except (ValueError, TypeError, KeyError) as error:
            block("SOURCE_CLOCK_OR_EVENT_CONTRACT_UNRESOLVED", event=identifier, error=str(error))
    return {"schemaVersion": "MLB_V19_PROSPECTIVE_READINESS_V1", "asOfUtc": now.isoformat(),
        "sourceConditionsSatisfied": not blockers, "publicationAuthorizedByThisCheck": False,
        "blockers": blockers, "eventCount": len(events), "rowCount": len(rows),
        "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False,
        "executionAllowedInAISP": False,
        "currentSourcePipelineClaim": "CONDITIONAL_CONTRACT_CHECK_NOT_A_CLAIM_OF_AVAILABLE_CURRENT_INPUTS"}


@dataclass
class V19Executable:
    """All fitted forecast components in memory, no runtime training fallback."""
    baseline: Any
    globals: dict[str, CandidatePipeline]
    meta: MetaSystem
    selected_branch: str
    raw_feature_order: tuple[str, ...]
    lineage: dict

    def __post_init__(self):
        if set(self.globals) != set(GLOBAL_ORDER[1:]):
            raise ValueError("All four saved V19 global branches are required")
        if self.selected_branch not in (*GLOBAL_ORDER, *ENSEMBLE_NAMES):
            raise ValueError("Unknown frozen research branch")
        if tuple(self.baseline.preprocessor.source_columns) != self.raw_feature_order:
            raise ValueError("Frozen V18 raw feature ordering differs")
        for name, candidate in self.globals.items():
            if candidate.variant != name or tuple(candidate.target_order) != tuple(PA_CLASS_ORDER):
                raise ValueError("Saved global identity or target order differs")
            if tuple(candidate.frozen_preprocessor.source_columns) != self.raw_feature_order:
                raise ValueError("Global model source contract differs from accepted V18")

    def predict_development_fixture(self, rows: pd.DataFrame, history: pd.DataFrame, *, calibrated=True) -> dict[str, np.ndarray]:
        """Only explicitly isolated Development fixtures may bypass current gates."""
        if rows.empty or history.empty or not rows.game_date.astype(str).le("2026-08-06").all() or not history.game_date.astype(str).le("2026-08-06").all():
            raise ValueError("Development fixture must use physically isolated allowed dates")
        return self._predict(rows, history, calibrated=calibrated)

    def _predict(self, rows, history, *, calibrated):
        values = self.baseline.preprocessor.transform(rows)
        branches = {"V18": predict_estimator(self.baseline.estimator, values)}
        for name in GLOBAL_ORDER[1:]:
            branches[name] = self.globals[name].predict_proba(rows, history)
        return self.meta.predict(rows, branches, calibrated=calibrated)

    def predict_prospective(self, rows: pd.DataFrame, history: pd.DataFrame, *, authority: Mapping, as_of_utc):
        readiness = prospective_readiness(rows, authority, self.raw_feature_order, as_of_utc=as_of_utc)
        if not readiness["sourceConditionsSatisfied"]:
            raise ValueError("CURRENT_RESEARCH_INPUTS_UNSUPPORTED: " + ",".join(sorted({r["reason"] for r in readiness["blockers"]})))
        # Source authority alone cannot override an actually stale input frame.
        target_dates = pd.to_datetime(rows.game_date).dt.normalize().unique()
        if len(target_dates) != 1:
            raise ValueError("ONE_OFFICIAL_LOCAL_DATE_PER_CURRENT_INPUT_PACKAGE_REQUIRED")
        required_through = pd.Timestamp(target_dates[0]) - pd.Timedelta(days=1)
        if history.empty or pd.to_datetime(history.game_date).max().normalize() != required_through:
            raise ValueError("ACTUAL_SEMANTIC_HISTORY_FRAME_STALE_FUTURE_DATED_OR_EMPTY")
        return self._predict(rows, history, calibrated=True)[self.selected_branch]

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, timedelta
from typing import Any, Mapping

from .db import Database, json_dumps, json_loads, now_iso
from .repositories.project_dataset_activation_repository import (
    ProjectDatasetActivationRepository,
)


FORECAST_CONTRACT_METADATA_KEY = "sportsForecastContract"
FORECAST_CONTRACT_SCHEMA_VERSION = "SPORTS_FORECAST_CONTRACT_V2"
SEASON_ROLES = "SEASON_ROLES"
CUSTOM_DATES_ROLLING_ORIGIN = "CUSTOM_DATES_ROLLING_ORIGIN"
# Import compatibility for the first bounded backend draft.  The persisted
# value is always the canonical UI/domain value above.
CUSTOM_DATES = CUSTOM_DATES_ROLLING_ORIGIN
_LEGACY_CUSTOM_DATES = "CUSTOM_DATES"
_TEMPORAL_MODES = {SEASON_ROLES, CUSTOM_DATES_ROLLING_ORIGIN, _LEGACY_CUSTOM_DATES}
_EVIDENCE_MODES = {"STRICT", "ENHANCED"}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CHRONOLOGICAL_VALIDATION_REQUIREMENT: dict[str, Any] = {
    "required": True,
    "configurationStage": "VALIDATION_CALIBRATION",
    "foldCount": 5,
    "window": "EXPANDING",
    "validationBlocks": "DATE_ATOMIC",
    "grouping": "CANONICAL_GAME",
    "shuffle": False,
    "preprocessing": "FOLD_LOCAL",
    "boundaryOptions": ["BALANCED_BY_GAME_COUNT", "MANUAL_DATE_RANGES"],
    "finalOotUse": "REPORTING_ONLY",
    "exactBoundaries": None,
}


class SportsForecastContractError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})

    def public_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


def _text(payload: Mapping[str, Any], key: str, *, required: bool = True) -> str:
    value = str(payload.get(key) or "").strip()
    if required and not value:
        raise SportsForecastContractError(
            "FORECAST_CONTRACT_FIELD_REQUIRED",
            f"{key} is required.",
            details={"field": key},
        )
    return value


def _iso_date(payload: Mapping[str, Any], key: str) -> date:
    raw = _text(payload, key)
    if not _ISO_DATE.fullmatch(raw):
        raise SportsForecastContractError(
            "INVALID_TEMPORAL_DATE",
            f"{key} must be an exact ISO calendar date (YYYY-MM-DD).",
            details={"field": key, "value": raw},
        )
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise SportsForecastContractError(
            "INVALID_TEMPORAL_DATE",
            f"{key} is not a valid calendar date.",
            details={"field": key, "value": raw},
        ) from exc
    return parsed


def _integer(payload: Mapping[str, Any], key: str, *, nullable: bool = False) -> int | None:
    value = payload.get(key)
    if nullable and value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SportsForecastContractError(
            "INVALID_SEASON_ROLE",
            f"{key} must be an integer year.",
            details={"field": key, "value": value},
        )
    return value


def _normalize_common(payload: Mapping[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("temporalDesignMode") or SEASON_ROLES).strip().upper()
    if mode not in _TEMPORAL_MODES:
        raise SportsForecastContractError(
            "INVALID_TEMPORAL_DESIGN_MODE",
            "temporalDesignMode must be SEASON_ROLES or CUSTOM_DATES_ROLLING_ORIGIN.",
            details={"temporalDesignMode": mode},
        )
    if mode == _LEGACY_CUSTOM_DATES:
        mode = CUSTOM_DATES_ROLLING_ORIGIN
    evidence_mode = str(payload.get("evidenceMode") or "").strip().upper()
    if evidence_mode not in _EVIDENCE_MODES:
        raise SportsForecastContractError(
            "INVALID_EVIDENCE_MODE",
            "evidenceMode must be STRICT or ENHANCED.",
            details={"evidenceMode": evidence_mode},
        )
    chronological_contract = payload.get("chronologicalValidation")
    if isinstance(chronological_contract, Mapping):
        chronological = chronological_contract.get("required")
    else:
        chronological = payload.get("chronologicalValidationRequired", True)
    if chronological is not True:
        raise SportsForecastContractError(
            "CHRONOLOGICAL_VALIDATION_REQUIRED",
            "MLB forecast contracts require chronological validation.",
        )
    outputs = payload.get("intendedOutputs") or []
    if not isinstance(outputs, list) or any(not str(item).strip() for item in outputs):
        raise SportsForecastContractError(
            "INVALID_INTENDED_OUTPUTS",
            "intendedOutputs must be a list of non-empty strings.",
        )
    return {
        "temporalDesignMode": mode,
        "target": _text(payload, "target"),
        "lifecycle": _text(payload, "lifecycle"),
        "evidenceMode": evidence_mode,
        # Stage 1 records the immutable requirement, but deliberately leaves
        # exact fold boundaries unset for Validation & Calibration.
        "chronologicalValidation": deepcopy(CHRONOLOGICAL_VALIDATION_REQUIREMENT),
        "intendedOutputs": [str(item).strip() for item in outputs],
        "researchPurpose": _text(payload, "researchPurpose", required=False),
        "notes": _text(payload, "notes", required=False),
    }


def _normalize_season_roles(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_development = payload.get("developmentSeasons")
    if (
        not isinstance(raw_development, list)
        or not raw_development
        or any(isinstance(item, bool) or not isinstance(item, int) for item in raw_development)
    ):
        raise SportsForecastContractError(
            "INVALID_SEASON_ROLE",
            "developmentSeasons must contain one or more integer years.",
            details={"field": "developmentSeasons"},
        )
    development = sorted(set(raw_development))
    validation = _integer(payload, "validationSeason")
    frozen = _integer(payload, "frozenSeason")
    prospective = _integer(payload, "prospectiveSeason", nullable=True)
    assert validation is not None and frozen is not None
    if development != list(range(development[0], development[-1] + 1)):
        raise SportsForecastContractError(
            "INVALID_SEASON_ROLE",
            "developmentSeasons must be a contiguous whole-season window.",
            details={"developmentSeasons": development},
        )
    if not development[-1] < validation < frozen:
        raise SportsForecastContractError(
            "INVALID_TEMPORAL_ORDER",
            "Development must end before validation, and validation before the frozen final season.",
            details={
                "developmentSeasons": development,
                "validationSeason": validation,
                "frozenSeason": frozen,
            },
        )
    return {
        "developmentSeasons": development,
        "validationSeason": validation,
        "frozenSeason": frozen,
        "prospectiveSeason": prospective,
    }


def _custom_date_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Accept the canonical flat wire shape plus nested range compatibility."""

    result = dict(payload)
    for range_key, start_key, end_key in (
        ("eligibleEvidence", "eligibleEvidenceStart", "eligibleEvidenceEnd"),
        ("developmentSelection", "developmentSelectionStart", "developmentSelectionEnd"),
        ("finalOot", "finalOotStart", "finalOotEnd"),
    ):
        nested = payload.get(range_key)
        if not isinstance(nested, Mapping):
            continue
        result.setdefault(start_key, nested.get("startDate"))
        result.setdefault(end_key, nested.get("endDate"))
    return result


def _normalize_custom_dates(payload: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, date]]:
    payload = _custom_date_payload(payload)
    keys = (
        "eligibleEvidenceStart",
        "eligibleEvidenceEnd",
        "developmentSelectionStart",
        "developmentSelectionEnd",
        "finalOotStart",
        "finalOotEnd",
    )
    parsed = {key: _iso_date(payload, key) for key in keys}
    eligible_start = parsed["eligibleEvidenceStart"]
    eligible_end = parsed["eligibleEvidenceEnd"]
    development_start = parsed["developmentSelectionStart"]
    development_end = parsed["developmentSelectionEnd"]
    oot_start = parsed["finalOotStart"]
    oot_end = parsed["finalOotEnd"]
    for label, start, end in (
        ("Eligible evidence", eligible_start, eligible_end),
        ("Development and model selection", development_start, development_end),
        ("Final OOT", oot_start, oot_end),
    ):
        if start > end:
            raise SportsForecastContractError(
                "INVALID_TEMPORAL_ORDER",
                f"{label} start must not be after its end.",
                details={"range": label, "start": start.isoformat(), "end": end.isoformat()},
            )
    if development_start < eligible_start or development_end > eligible_end:
        raise SportsForecastContractError(
            "TEMPORAL_RANGE_OUTSIDE_ELIGIBLE_EVIDENCE",
            "Development and model selection must lie within the eligible evidence range.",
            details={
                "eligibleEvidenceStart": eligible_start.isoformat(),
                "eligibleEvidenceEnd": eligible_end.isoformat(),
                "developmentSelectionStart": development_start.isoformat(),
                "developmentSelectionEnd": development_end.isoformat(),
            },
        )
    if oot_start < eligible_start or oot_end > eligible_end:
        raise SportsForecastContractError(
            "TEMPORAL_RANGE_OUTSIDE_ELIGIBLE_EVIDENCE",
            "Final OOT must lie within the eligible evidence range.",
            details={
                "eligibleEvidenceStart": eligible_start.isoformat(),
                "eligibleEvidenceEnd": eligible_end.isoformat(),
                "finalOotStart": oot_start.isoformat(),
                "finalOotEnd": oot_end.isoformat(),
            },
        )
    if oot_start <= development_end:
        raise SportsForecastContractError(
            "TEMPORAL_RANGE_OVERLAP",
            "Final OOT must begin after development and model selection ends; the ranges may not overlap.",
            details={
                "developmentSelectionEnd": development_end.isoformat(),
                "finalOotStart": oot_start.isoformat(),
            },
        )
    return ({key: parsed[key].isoformat() for key in keys}, parsed)


def _project_not_registered() -> SportsForecastContractError:
    return SportsForecastContractError(
        "PROJECT_NOT_REGISTERED",
        "The ASP Model Studio sports project is not registered in the local persistence database.",
        status_code=404,
    )


def _registration_coverage(
    connection: Any,
    registration: Mapping[str, Any],
    *,
    activation_revision: int | None = None,
) -> dict[str, Any] | None:
    # player_prior is an annual summary whose maximum_date is deliberately
    # December 31.  It is not game-day/PA coverage and must never extend the
    # contract boundary beyond the last registered plate appearance.
    coverage = connection.execute(
        """
        SELECT MIN(minimum_date) AS earliest_date,
               MAX(maximum_date) AS latest_date,
               COUNT(*) AS partition_count,
               COALESCE(SUM(row_count), 0) AS row_count
        FROM sports_dataset_partitions
        WHERE registration_id = ?
          AND family = 'plate_appearance'
          AND row_count > 0
          AND minimum_date IS NOT NULL
          AND maximum_date IS NOT NULL
        """,
        (registration["registration_id"],),
    ).fetchone()
    if coverage is None or not coverage["earliest_date"] or not coverage["latest_date"]:
        return None
    result = {
        "registrationId": registration["registration_id"],
        "datasetId": registration["dataset_id"],
        "datasetVersionId": registration["dataset_version_id"],
        "manifestSha": registration["manifest_sha"],
        "family": "plate_appearance",
        "coverageBasis": "REGISTERED_PLATE_APPEARANCE_PARTITION_METADATA",
        "earliestDate": coverage["earliest_date"],
        "latestDate": coverage["latest_date"],
        "partitionCount": int(coverage["partition_count"] or 0),
        "rowCount": int(coverage["row_count"] or 0),
    }
    if activation_revision is not None:
        result["activationRevision"] = activation_revision
    return result


def _source_coverage(connection: Any, project_id: str) -> dict[str, Any]:
    """Resolve MLB PA coverage only through this project's durable selection.

    The workspace-global ``sports_dataset_registrations.active`` flag is a
    catalog convenience.  It is deliberately not scientific authority for a
    project: one project's FD1 selection must not silently control another
    project's current-Statcast contract.
    """

    selection = connection.execute(
        """
        SELECT active.dataset_id, active.dataset_version_id,
               active.activation_revision, active.activation_status,
               active.metadata_json AS activation_metadata_json,
               link.link_status, link.metadata_json AS link_metadata_json
        FROM active_modeling_dataset_versions AS active
        LEFT JOIN project_dataset_links AS link
          ON link.project_id = active.project_id
         AND link.dataset_id = active.dataset_id
        WHERE active.project_id = ?
        """,
        (project_id,),
    ).fetchone()
    if (
        selection is None
        or selection["activation_status"] != "active"
        or selection["link_status"] != "active"
    ):
        raise SportsForecastContractError(
            "DATASET_NOT_LINKED",
            "Select an evidence dataset for this sports project before registering its forecast contract.",
            status_code=409,
            details={"projectId": project_id},
        )

    activation_metadata = json_loads(selection["activation_metadata_json"], {})
    link_metadata = json_loads(selection["link_metadata_json"], {})
    registration_id = (
        str(
            (link_metadata.get("registrationId") if isinstance(link_metadata, Mapping) else "")
            or (
                activation_metadata.get("registrationId")
                if isinstance(activation_metadata, Mapping)
                else ""
            )
            or ""
        ).strip()
    )
    bound_manifest_sha = (
        str(
            (link_metadata.get("manifestSha") if isinstance(link_metadata, Mapping) else "")
            or (
                activation_metadata.get("manifestSha")
                if isinstance(activation_metadata, Mapping)
                else ""
            )
            or ""
        ).strip()
    )
    parameters: list[Any] = [
        selection["dataset_id"],
        selection["dataset_version_id"],
    ]
    registration_clause = ""
    if registration_id:
        registration_clause = "AND registration_id = ?"
        parameters.append(registration_id)
    registrations = connection.execute(
        """
        SELECT registration_id, dataset_id, dataset_version_id, manifest_sha,
               metadata_json
        FROM sports_dataset_registrations
        WHERE dataset_id = ?
          AND dataset_version_id = ?
          AND validation_status = 'VALID'
          AND UPPER(league) = 'MLB'
        """
        + registration_clause
        + " ORDER BY registered_at DESC, registration_id",
        tuple(parameters),
    ).fetchall()
    # Legacy durable selections did not persist registrationId.  They remain
    # compatible only when the exact dataset/version pair resolves uniquely;
    # ambiguity is never repaired by choosing first/latest/global-active.
    if len(registrations) != 1:
        raise SportsForecastContractError(
            "SOURCE_COVERAGE_UNAVAILABLE",
            "The linked dataset does not resolve to one exact validated MLB evidence registration.",
            status_code=409,
            details={
                "projectId": project_id,
                "datasetId": selection["dataset_id"],
                "datasetVersionId": selection["dataset_version_id"],
                "registrationId": registration_id or None,
            },
        )
    registration = registrations[0]
    if bound_manifest_sha and registration["manifest_sha"] != bound_manifest_sha:
        raise SportsForecastContractError(
            "SOURCE_COVERAGE_UNAVAILABLE",
            "The linked sports evidence manifest does not match the selected registration authority.",
            status_code=409,
            details={
                "registrationId": registration["registration_id"],
                "expectedManifestSha": bound_manifest_sha,
                "actualManifestSha": registration["manifest_sha"],
            },
        )
    registration_metadata = json_loads(registration["metadata_json"], {})
    if (
        isinstance(registration_metadata, Mapping)
        and registration_metadata.get("authorityState") == "HISTORICAL"
    ):
        raise SportsForecastContractError(
            "SOURCE_COVERAGE_UNAVAILABLE",
            "The linked sports evidence registration is historical and cannot authorize a new forecast contract.",
            status_code=409,
            details={"registrationId": registration["registration_id"]},
        )
    coverage = _registration_coverage(
        connection,
        registration,
        activation_revision=int(selection["activation_revision"]),
    )
    if coverage is None:
        raise SportsForecastContractError(
            "SOURCE_COVERAGE_UNAVAILABLE",
            "The linked sports evidence registration has no authoritative plate-appearance date coverage.",
            status_code=409,
            details={"registrationId": registration["registration_id"]},
        )
    return coverage


def _validate_source_coverage(
    requested: Mapping[str, date],
    coverage: Mapping[str, Any],
) -> None:
    registered_start = date.fromisoformat(str(coverage["earliestDate"]))
    registered_end = date.fromisoformat(str(coverage["latestDate"]))
    requested_start = requested["eligibleEvidenceStart"]
    requested_end = requested["eligibleEvidenceEnd"]
    missing: list[dict[str, str]] = []
    if requested_start < registered_start:
        missing.append(
            {
                "start": requested_start.isoformat(),
                "end": (registered_start - timedelta(days=1)).isoformat(),
            }
        )
    if requested_end > registered_end:
        missing.append(
            {
                "start": (registered_end + timedelta(days=1)).isoformat(),
                "end": requested_end.isoformat(),
            }
        )
    if not missing:
        return
    final_year = requested["finalOotEnd"].year
    if requested_end > registered_end:
        message = (
            f"Registered source evidence currently ends on {registered_end.isoformat()}. "
            f"The requested {final_year} evaluation period is not available in the Data Warehouse."
        )
    else:
        message = (
            f"Registered source evidence currently begins on {registered_start.isoformat()}. "
            "The requested eligible evidence period is not available in the Data Warehouse."
        )
    raise SportsForecastContractError(
        "SOURCE_COVERAGE_INSUFFICIENT",
        message,
        details={
            "requestedRange": {
                "start": requested_start.isoformat(),
                "end": requested_end.isoformat(),
            },
            "requestedFinalOotRange": {
                "start": requested["finalOotStart"].isoformat(),
                "end": requested["finalOotEnd"].isoformat(),
            },
            "coverage": dict(coverage),
            "missingInterval": missing[0],
            "missingIntervals": missing,
        },
    )


def _validate_season_role_coverage(
    contract: Mapping[str, Any],
    coverage: Mapping[str, Any],
) -> None:
    """Reject governed evidence seasons outside registered PA coverage.

    ``prospectiveSeason`` describes a future application horizon and is not
    evidence authority, so it is intentionally excluded.  A boundary season
    is considered represented when registered PA coverage reaches that year;
    the partition metadata, rather than artificial January/December dates,
    remains the exact source authority within that season.
    """

    development = [int(year) for year in contract.get("developmentSeasons") or []]
    validation = int(contract["validationSeason"])
    frozen = int(contract["frozenSeason"])
    governed_years = sorted(set([*development, validation, frozen]))
    registered_start = date.fromisoformat(str(coverage["earliestDate"]))
    registered_end = date.fromisoformat(str(coverage["latestDate"]))
    missing_years = [
        year
        for year in governed_years
        if year < registered_start.year or year > registered_end.year
    ]
    if not missing_years:
        return

    missing: list[dict[str, str]] = []
    interval_start = missing_years[0]
    interval_end = missing_years[0]
    for year in missing_years[1:]:
        if year == interval_end + 1:
            interval_end = year
            continue
        missing.append(
            {
                "start": f"{interval_start:04d}-01-01",
                "end": f"{interval_end:04d}-12-31",
            }
        )
        interval_start = interval_end = year
    missing.append(
        {
            "start": f"{interval_start:04d}-01-01",
            "end": f"{interval_end:04d}-12-31",
        }
    )

    if any(year > registered_end.year for year in missing_years):
        requested_year = max(year for year in missing_years if year > registered_end.year)
        message = (
            f"Registered source evidence currently ends on {registered_end.isoformat()}. "
            f"The requested {requested_year} evaluation period is not available in the Data Warehouse."
        )
    else:
        message = (
            f"Registered source evidence currently begins on {registered_start.isoformat()}. "
            "The requested governed season is not available in the Data Warehouse."
        )
    raise SportsForecastContractError(
        "SOURCE_COVERAGE_INSUFFICIENT",
        message,
        details={
            "requestedRange": {
                "start": f"{min(governed_years):04d}-01-01",
                "end": f"{max(governed_years):04d}-12-31",
            },
            "requestedSeasons": {
                "developmentSeasons": development,
                "validationSeason": validation,
                "frozenSeason": frozen,
            },
            "coverage": dict(coverage),
            "missingInterval": missing[0],
            "missingIntervals": missing,
        },
    )


def _state(metadata: Mapping[str, Any]) -> dict[str, Any]:
    raw = metadata.get(FORECAST_CONTRACT_METADATA_KEY)
    if raw is None:
        return {
            "schemaVersion": FORECAST_CONTRACT_SCHEMA_VERSION,
            "currentVersion": 0,
            "current": None,
            "history": [],
        }
    if not isinstance(raw, dict):
        raise SportsForecastContractError(
            "FORECAST_CONTRACT_STATE_INVALID",
            "The persisted forecast-contract state is malformed.",
            status_code=409,
        )
    current = raw.get("current")
    history = raw.get("history")
    version = raw.get("currentVersion")
    if (
        raw.get("schemaVersion") != FORECAST_CONTRACT_SCHEMA_VERSION
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version < 0
        or (current is not None and not isinstance(current, dict))
        or not isinstance(history, list)
        or any(not isinstance(item, dict) for item in history)
    ):
        raise SportsForecastContractError(
            "FORECAST_CONTRACT_STATE_INVALID",
            "The persisted forecast-contract state is malformed.",
            status_code=409,
        )
    return {
        "schemaVersion": FORECAST_CONTRACT_SCHEMA_VERSION,
        "currentVersion": version,
        "current": current,
        "history": list(history),
    }


class SportsForecastContractStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_evidence_dataset(self, project_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone() is None:
                raise _project_not_registered()
            coverage = _source_coverage(connection, project_id)
        return {
            "projectId": project_id,
            "registrationId": coverage["registrationId"],
            "datasetId": coverage["datasetId"],
            "datasetVersionId": coverage["datasetVersionId"],
            "manifestSha": coverage["manifestSha"],
            "activationRevision": coverage["activationRevision"],
            "coverage": {
                key: coverage[key]
                for key in (
                    "earliestDate",
                    "latestDate",
                    "family",
                    "rowCount",
                    "partitionCount",
                )
            },
        }

    def link_evidence_dataset(
        self,
        project_id: str,
        registration_id: str,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        registration_key = str(registration_id or "").strip()
        if not registration_key:
            raise SportsForecastContractError(
                "SOURCE_REGISTRATION_REQUIRED",
                "registrationId is required to select a sports evidence dataset.",
                details={"field": "registrationId"},
            )
        with self.database.connection() as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone() is None:
                raise _project_not_registered()
            registration = connection.execute(
                """
                SELECT registration_id, dataset_id, dataset_version_id,
                       manifest_sha, metadata_json
                FROM sports_dataset_registrations
                WHERE registration_id = ?
                  AND validation_status = 'VALID'
                  AND UPPER(league) = 'MLB'
                """,
                (registration_key,),
            ).fetchone()
            if registration is None:
                raise SportsForecastContractError(
                    "SOURCE_COVERAGE_UNAVAILABLE",
                    "The selected validated MLB evidence registration is unavailable.",
                    status_code=409,
                    details={"registrationId": registration_key},
                )
            registration_metadata = json_loads(registration["metadata_json"], {})
            if (
                isinstance(registration_metadata, Mapping)
                and registration_metadata.get("authorityState") == "HISTORICAL"
            ):
                raise SportsForecastContractError(
                    "SOURCE_COVERAGE_UNAVAILABLE",
                    "The selected sports evidence registration is historical and cannot authorize a new forecast contract.",
                    status_code=409,
                    details={"registrationId": registration_key},
                )
            if _registration_coverage(connection, registration) is None:
                raise SportsForecastContractError(
                    "SOURCE_COVERAGE_UNAVAILABLE",
                    "The selected sports evidence registration has no authoritative plate-appearance date coverage.",
                    status_code=409,
                    details={"registrationId": registration_key},
                )

        ProjectDatasetActivationRepository(self.database).activate_exact(
            project_id=project_id,
            dataset_id=str(registration["dataset_id"]),
            dataset_version_id=str(registration["dataset_version_id"]),
            actor_user_id=user_id,
            metadata={
                "source": "sports_evidence_dataset_selection",
                "registrationId": registration_key,
                "manifestSha": str(registration["manifest_sha"]),
                "requestedDatasetVersionId": str(registration["dataset_version_id"]),
            },
            # The generic predictive workflow uses step00..step13 lineage.
            # Sports stages have their own persisted identifiers and must not
            # be rewritten as a side effect of choosing evidence.
            reconcile_workflow=False,
        )
        return self.get_evidence_dataset(project_id)

    def get(self, project_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                raise _project_not_registered()
            metadata = json_loads(row["metadata_json"], {})
            state = _state(metadata if isinstance(metadata, dict) else {})
            coverage = _source_coverage(connection, project_id)
        return {**state, "sourceCoverage": coverage}

    def save(
        self,
        project_id: str,
        payload: Mapping[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        expected = payload.get("expectedVersion")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise SportsForecastContractError(
                "EXPECTED_VERSION_REQUIRED",
                "expectedVersion must be the non-negative current contract version.",
                details={"expectedVersion": expected},
            )
        contract_payload = payload.get("contract")
        if contract_payload is None:
            # Backward compatibility for a direct/flat store caller.  The HTTP
            # client uses {expectedVersion, contract: draft}.
            contract_payload = payload
        if not isinstance(contract_payload, Mapping):
            raise SportsForecastContractError(
                "FORECAST_CONTRACT_REQUIRED",
                "contract must be an object containing the Stage 1 forecast-contract draft.",
                details={"field": "contract"},
            )

        normalized = _normalize_common(contract_payload)
        parsed_custom: dict[str, date] | None = None
        if normalized["temporalDesignMode"] == CUSTOM_DATES_ROLLING_ORIGIN:
            custom, parsed_custom = _normalize_custom_dates(contract_payload)
            normalized.update(custom)
        else:
            normalized.update(_normalize_season_roles(contract_payload))

        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT metadata_json FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                raise _project_not_registered()
            metadata = json_loads(row["metadata_json"], {})
            if not isinstance(metadata, dict):
                metadata = {}
            state = _state(metadata)
            current_version = state["currentVersion"]
            if expected != current_version:
                raise SportsForecastContractError(
                    "FORECAST_CONTRACT_VERSION_CONFLICT",
                    "The forecast contract changed after this page was loaded. Reload before saving.",
                    status_code=409,
                    details={"expectedVersion": expected, "currentVersion": current_version},
                )
            coverage = _source_coverage(connection, project_id)
            if parsed_custom is not None:
                _validate_source_coverage(parsed_custom, coverage)
            else:
                _validate_season_role_coverage(normalized, coverage)

            coverage_authority = {
                key: coverage[key]
                for key in (
                    "registrationId",
                    "datasetId",
                    "datasetVersionId",
                    "manifestSha",
                    "family",
                    "coverageBasis",
                    "earliestDate",
                    "latestDate",
                )
            }
            canonical = {
                "schemaVersion": FORECAST_CONTRACT_SCHEMA_VERSION,
                "projectId": project_id,
                **normalized,
                "coverageAuthority": coverage_authority,
            }
            digest = hashlib.sha256(
                json.dumps(
                    canonical,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            current = state["current"]
            if isinstance(current, dict) and current.get("contractSha256") == digest:
                connection.commit()
                return {**state, "sourceCoverage": coverage, "saveDisposition": "UNCHANGED"}

            next_version = current_version + 1
            timestamp = now_iso()
            contract = {
                **canonical,
                "contractId": f"sports-forecast-contract:{project_id}:v{next_version}:sha256:{digest}",
                "contractSha256": digest,
                "version": next_version,
                "supersedesContractId": current.get("contractId") if isinstance(current, dict) else None,
                "savedAt": timestamp,
                "registeredAt": timestamp,
                "registeredBy": user_id,
            }
            history = list(state["history"])
            if isinstance(current, dict):
                history.append(current)
            next_state = {
                "schemaVersion": FORECAST_CONTRACT_SCHEMA_VERSION,
                "currentVersion": next_version,
                "current": contract,
                "history": history,
            }
            metadata[FORECAST_CONTRACT_METADATA_KEY] = next_state
            connection.execute(
                """
                UPDATE projects
                SET metadata_json = ?, updated_at = ?, updated_by = ?
                WHERE project_id = ?
                """,
                (json_dumps(metadata, {}), timestamp, user_id, project_id),
            )
            connection.commit()
            return {**next_state, "sourceCoverage": coverage, "saveDisposition": "CREATED"}
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

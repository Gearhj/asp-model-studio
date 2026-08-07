"""Provider-neutral, candidate-only dataset-to-catalog crosswalk analysis.

This module is intentionally detached from ATLAS project, dataset, and workflow
stores.  It accepts caller-supplied schema metadata and catalog definitions and
returns review candidates.  A candidate is never an approved mapping and this
module has no mutation path.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Iterable, Literal, Mapping, Sequence


MatchStatus = Literal[
    "exact_dictionary_code_match",
    "approved_institutional_alias",
    "probable_semantic_match",
    "multiple_possible_matches",
    "no_supported_match",
    "unresolved_recoding",
    "non_catalog_field",
    "target",
    "deterministic_target_source",
]


class CrosswalkContractError(ValueError):
    """Raised when a caller supplies an incomplete crosswalk contract."""


class CatalogSelectionError(CrosswalkContractError):
    """Raised when the requested catalog has no exact definition set."""


_CATALOG_KEYS = ("provider", "product", "edition", "dictionary_version")
_TOKEN_PATTERN = re.compile(r"[A-Za-z]+|\d+")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _value(record: object, *names: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return default
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _text(value: object) -> str:
    return str(value or "").strip()


def _catalog_key(record: object) -> dict[str, str]:
    nested = _value(record, "catalog_key", default=None)
    source = nested if nested is not None else record
    key = {
        "provider": _text(_value(source, "provider", default="")),
        "product": _text(_value(source, "product", default="")),
        "edition": _text(_value(source, "edition", default="")),
        # ``dictionary_version`` is the external metadata contract.  Accept
        # ``version`` as a compatibility spelling for typed catalog keys while
        # always normalizing the candidate artifact back to the explicit name.
        "dictionary_version": _text(
            _value(source, "dictionary_version", "version", default="")
        ),
    }
    missing = [name for name, value in key.items() if not value]
    if missing:
        raise CrosswalkContractError(
            "Catalog selection requires provider, product, edition, and "
            "dictionary_version."
        )
    return key


def _same_catalog(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    return all(left[name].casefold() == right[name].casefold() for name in _CATALOG_KEYS)


def _exact_catalog_checksum(value: object) -> str:
    checksum = _text(value)
    if not _SHA256_PATTERN.fullmatch(checksum):
        raise CrosswalkContractError(
            "Crosswalk analysis requires one exact lowercase catalog checksum."
        )
    return checksum


def _attribute_code(attribute: object) -> str:
    return _text(_value(attribute, "attribute_code", "code", default=""))


def _exact_catalog_attributes(
    attributes: Iterable[object],
    catalog_key: Mapping[str, str],
) -> list[object]:
    exact: list[object] = []
    for attribute in attributes:
        try:
            attribute_key = _catalog_key(attribute)
        except CrosswalkContractError:
            continue
        if _same_catalog(attribute_key, catalog_key):
            exact.append(attribute)
    if not exact:
        raise CatalogSelectionError(
            "The exact provider, product, edition, and dictionary version "
            "has no catalog definitions; first/latest fallback is prohibited."
        )

    codes = [_attribute_code(attribute).casefold() for attribute in exact]
    if any(not code for code in codes):
        raise CrosswalkContractError("Every catalog definition requires an attribute code.")
    duplicate_codes = sorted(code for code, count in Counter(codes).items() if count > 1)
    if duplicate_codes:
        raise CrosswalkContractError(
            "Attribute codes must be unique within an exact catalog version."
        )
    return exact


def _tokens(value: object) -> set[str]:
    text = _text(value)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return {
        token.casefold()
        for token in _TOKEN_PATTERN.findall(text)
        if len(token) > 1 and not token.isdigit()
    }


def _decimal(value: object) -> Decimal | None:
    text = _text(value)
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _string_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        values: Iterable[object] = (value,)
    elif isinstance(value, Iterable):
        values = value
    else:
        values = (value,)
    return tuple(sorted({_text(item) for item in values if _text(item)}))


def _negative_values(field: object) -> tuple[str, ...]:
    observed = _string_values(
        _value(
            field,
            "observed_special_values",
            "special_values",
            default=(),
        )
    )
    return tuple(
        value
        for value in observed
        if (numeric := _decimal(value)) is not None and numeric < 0
    )


def _durable_recode_evidence(field: object) -> bool:
    evidence = _value(field, "durable_recode_evidence", "recode_evidence", default=None)
    if not isinstance(evidence, Mapping):
        return False
    evidence_id = _text(evidence.get("evidence_id") or evidence.get("crosswalk_id"))
    mapping = evidence.get("source_to_model") or evidence.get("source_to_model_values")
    return bool(evidence_id and isinstance(mapping, Mapping) and mapping)


def _range_evidence(field: object, attribute: object) -> dict[str, object]:
    observed_min = _decimal(_value(field, "observed_min", "minimum", default=None))
    observed_max = _decimal(_value(field, "observed_max", "maximum", default=None))
    valid_min = _decimal(
        _value(
            attribute,
            "ordinary_min",
            "ordinary_valid_min",
            "valid_min",
            default=None,
        )
    )
    valid_max = _decimal(
        _value(
            attribute,
            "ordinary_max",
            "ordinary_valid_max",
            "valid_max",
            default=None,
        )
    )
    comparable = None not in (observed_min, observed_max, valid_min, valid_max)
    compatible = bool(
        comparable
        and observed_min is not None
        and observed_max is not None
        and valid_min is not None
        and valid_max is not None
        and valid_min <= observed_min <= observed_max <= valid_max
    )
    return {
        "comparable": comparable,
        "compatible": compatible if comparable else None,
        "observed_range_present": observed_min is not None and observed_max is not None,
        "catalog_range_present": valid_min is not None and valid_max is not None,
    }


def _semantic_evidence(field: object, attribute: object) -> dict[str, object]:
    field_name_tokens = _tokens(_value(field, "field_name", "name", "column", default=""))
    field_description_tokens = _tokens(_value(field, "description", default=""))
    attribute_tokens = _tokens(_attribute_code(attribute)) | _tokens(
        _value(attribute, "description", default="")
    )
    attribute_description_tokens = _tokens(_value(attribute, "description", default=""))

    name_overlap = field_name_tokens & attribute_tokens
    description_overlap = field_description_tokens & attribute_description_tokens
    name_score = len(name_overlap) / max(len(field_name_tokens), 1)
    description_score = len(description_overlap) / max(len(field_description_tokens), 1)

    field_units = _text(_value(field, "units", "unit", default=""))
    attribute_units = _text(_value(attribute, "units", "unit", default=""))
    unit_comparable = bool(field_units and attribute_units)
    unit_match = unit_comparable and field_units.casefold() == attribute_units.casefold()
    range_evidence = _range_evidence(field, attribute)

    score = 0.60 * name_score + 0.25 * description_score
    if unit_comparable:
        score += 0.10 if unit_match else 0.0
    if range_evidence["comparable"]:
        score += 0.05 if range_evidence["compatible"] else 0.0

    return {
        "score": round(min(score, 1.0), 6),
        "name": {
            "overlap_tokens": sorted(name_overlap),
            "score": round(name_score, 6),
        },
        "description": {
            "overlap_tokens": sorted(description_overlap),
            "score": round(description_score, 6),
        },
        "units": {
            "comparable": unit_comparable,
            "compatible": unit_match if unit_comparable else None,
        },
        "valid_range": range_evidence,
    }


def _approved_aliases(
    field_name: str,
    aliases: Iterable[object],
    catalog_key: Mapping[str, str],
    available_codes: Mapping[str, object],
) -> list[tuple[object, object]]:
    matches: list[tuple[object, object]] = []
    for alias in aliases:
        source_field = _text(
            _value(alias, "dataset_field", "field_name", "alias", default="")
        )
        if source_field.casefold() != field_name.casefold():
            continue
        if _text(_value(alias, "approval_status", "status", default="")).casefold() != "approved":
            continue
        if not _text(_value(alias, "evidence_id", "approval_reference", default="")):
            continue
        try:
            alias_key = _catalog_key(alias)
        except CrosswalkContractError:
            continue
        if not _same_catalog(alias_key, catalog_key):
            continue
        code = _text(_value(alias, "attribute_code", "candidate_attribute_code", default=""))
        attribute = available_codes.get(code.casefold())
        if attribute is not None:
            matches.append((alias, attribute))
    return matches


def _candidate(
    *,
    field: object,
    catalog_key: Mapping[str, str],
    catalog_checksum: str,
    attribute: object | None,
    status: MatchStatus,
    confidence: float,
    evidence: Mapping[str, object] | None = None,
    ambiguity: Sequence[str] = (),
    concerns: Sequence[str] = (),
    alias_reference: str = "",
) -> dict[str, object]:
    field_name = _text(_value(field, "field_name", "name", "column", default=""))
    negative_values = _negative_values(field)
    durable_recode = _durable_recode_evidence(field)
    return {
        "dataset_field": field_name,
        "candidate_attribute_code": _attribute_code(attribute) if attribute is not None else None,
        "match_status": status,
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 6),
        "provider": catalog_key["provider"],
        "product": catalog_key["product"],
        "edition": catalog_key["edition"],
        "dictionary_version": catalog_key["dictionary_version"],
        "catalog_checksum": catalog_checksum,
        "name_evidence": dict((evidence or {}).get("name", {})),
        "description_evidence": dict((evidence or {}).get("description", {})),
        "units_evidence": dict((evidence or {}).get("units", {})),
        "valid_range_evidence": dict((evidence or {}).get("valid_range", {})),
        "special_value_evidence": {
            "observed_values": list(
                _string_values(
                    _value(
                        field,
                        "observed_special_values",
                        "special_values",
                        default=(),
                    )
                )
            ),
            "negative_recodes_present": bool(negative_values),
            "durable_recode_evidence_present": durable_recode,
            "source_meaning_assignment": (
                "withheld_pending_durable_recode_evidence"
                if negative_values and not durable_recode
                else "not_assigned_by_crosswalk"
            ),
        },
        "ambiguity": list(ambiguity),
        "required_analyst_confirmation": status not in {
            "target",
            "deterministic_target_source",
            "non_catalog_field",
            "no_supported_match",
        },
        "transformation_or_recoding_concerns": list(concerns),
        "institutional_alias_reference": alias_reference or None,
        "candidate_only": True,
        "approved_mapping": False,
    }


def build_crosswalk_candidates(
    field: object,
    attributes: Iterable[object],
    *,
    catalog_key: object,
    catalog_checksum: str,
    aliases: Iterable[object] = (),
    target_field: str | None = None,
    target_source_fields: Iterable[str] = (),
    semantic_threshold: float = 0.55,
    semantic_tie_delta: float = 0.03,
) -> list[dict[str, object]]:
    """Return deterministic mapping candidates for one dataset field.

    The function requires one exact catalog version and never chooses a first
    or most-recent version.  Even exact-code and institution-approved alias
    matches remain candidates requiring a separate analyst confirmation.
    """

    field_name = _text(_value(field, "field_name", "name", "column", default=""))
    if not field_name:
        raise CrosswalkContractError("Every dataset field requires a non-empty name.")
    if not 0.0 <= semantic_threshold <= 1.0:
        raise CrosswalkContractError("semantic_threshold must be between zero and one.")
    if not 0.0 <= semantic_tie_delta <= 1.0:
        raise CrosswalkContractError("semantic_tie_delta must be between zero and one.")

    key = _catalog_key(catalog_key)
    checksum = _exact_catalog_checksum(catalog_checksum)
    exact_attributes = _exact_catalog_attributes(attributes, key)
    available_codes = {
        _attribute_code(attribute).casefold(): attribute for attribute in exact_attributes
    }

    if target_field and field_name.casefold() == target_field.strip().casefold():
        return [
            _candidate(
                field=field,
                catalog_key=key,
                catalog_checksum=checksum,
                attribute=None,
                status="target",
                confidence=1.0,
                concerns=("Target columns are not eligible for bureau attribute mapping.",),
            )
        ]

    target_sources = {_text(value).casefold() for value in target_source_fields if _text(value)}
    if field_name.casefold() in target_sources:
        return [
            _candidate(
                field=field,
                catalog_key=key,
                catalog_checksum=checksum,
                attribute=None,
                status="deterministic_target_source",
                confidence=1.0,
                concerns=(
                    "Deterministic target-source columns are excluded from predictor crosswalk approval.",
                ),
            )
        ]

    if bool(_value(field, "non_catalog_field", default=False)) or _value(
        field, "catalog_eligible", default=True
    ) is False:
        return [
            _candidate(
                field=field,
                catalog_key=key,
                catalog_checksum=checksum,
                attribute=None,
                status="non_catalog_field",
                confidence=1.0,
            )
        ]

    negative_values = _negative_values(field)
    recode_unresolved = bool(negative_values and not _durable_recode_evidence(field))
    recode_concern = (
        "Negative modeling-data codes may be institutionally recoded; source meanings "
        "remain unassigned until a durable source-to-model transformation crosswalk is supplied."
    )

    exact_attribute = available_codes.get(field_name.casefold())
    if exact_attribute is not None:
        status: MatchStatus = (
            "unresolved_recoding" if recode_unresolved else "exact_dictionary_code_match"
        )
        return [
            _candidate(
                field=field,
                catalog_key=key,
                catalog_checksum=checksum,
                attribute=exact_attribute,
                status=status,
                confidence=1.0,
                evidence=_semantic_evidence(field, exact_attribute),
                concerns=(recode_concern,) if recode_unresolved else (),
            )
        ]

    alias_matches = _approved_aliases(field_name, aliases, key, available_codes)
    if alias_matches:
        codes = sorted({_attribute_code(attribute) for _alias, attribute in alias_matches})
        ambiguous = len(codes) > 1
        results: list[dict[str, object]] = []
        for alias, attribute in sorted(
            alias_matches,
            key=lambda item: _attribute_code(item[1]).casefold(),
        ):
            status = (
                "unresolved_recoding"
                if recode_unresolved
                else "multiple_possible_matches"
                if ambiguous
                else "approved_institutional_alias"
            )
            concerns = [recode_concern] if recode_unresolved else []
            results.append(
                _candidate(
                    field=field,
                    catalog_key=key,
                    catalog_checksum=checksum,
                    attribute=attribute,
                    status=status,
                    confidence=0.99,
                    evidence=_semantic_evidence(field, attribute),
                    ambiguity=codes if ambiguous else (),
                    concerns=concerns,
                    alias_reference=_text(
                        _value(alias, "evidence_id", "approval_reference", default="")
                    ),
                )
            )
        return results

    scored = [
        (_semantic_evidence(field, attribute), attribute)
        for attribute in exact_attributes
    ]
    scored = [item for item in scored if float(item[0]["score"]) >= semantic_threshold]
    scored.sort(
        key=lambda item: (-float(item[0]["score"]), _attribute_code(item[1]).casefold())
    )

    if not scored:
        status = "unresolved_recoding" if recode_unresolved else "no_supported_match"
        return [
            _candidate(
                field=field,
                catalog_key=key,
                catalog_checksum=checksum,
                attribute=None,
                status=status,
                confidence=0.0,
                concerns=(recode_concern,) if recode_unresolved else (),
            )
        ]

    best = float(scored[0][0]["score"])
    tied = [item for item in scored if best - float(item[0]["score"]) <= semantic_tie_delta]
    ambiguous_codes = sorted(_attribute_code(attribute) for _evidence, attribute in tied)
    status = (
        "unresolved_recoding"
        if recode_unresolved
        else "multiple_possible_matches"
        if len(tied) > 1
        else "probable_semantic_match"
    )
    return [
        _candidate(
            field=field,
            catalog_key=key,
            catalog_checksum=checksum,
            attribute=attribute,
            status=status,
            confidence=float(evidence["score"]),
            evidence=evidence,
            ambiguity=ambiguous_codes if len(tied) > 1 else (),
            concerns=(recode_concern,) if recode_unresolved else (),
        )
        for evidence, attribute in tied
    ]


def build_dataset_crosswalk(
    fields: Iterable[object],
    attributes: Iterable[object],
    *,
    catalog_key: object,
    catalog_checksum: str,
    aliases: Iterable[object] = (),
    target_field: str | None = None,
    target_source_fields: Iterable[str] = (),
    semantic_threshold: float = 0.55,
    semantic_tie_delta: float = 0.03,
) -> dict[str, object]:
    """Build a deterministic review artifact without approving or mutating data."""

    key = _catalog_key(catalog_key)
    exact_checksum = _exact_catalog_checksum(catalog_checksum)
    attribute_records = list(attributes)
    alias_records = list(aliases)
    target_sources = tuple(target_source_fields)
    mappings: list[dict[str, object]] = []
    for field in fields:
        mappings.extend(
            build_crosswalk_candidates(
                field,
                attribute_records,
                catalog_key=key,
                catalog_checksum=exact_checksum,
                aliases=alias_records,
                target_field=target_field,
                target_source_fields=target_sources,
                semantic_threshold=semantic_threshold,
                semantic_tie_delta=semantic_tie_delta,
            )
        )

    status_counts = Counter(str(candidate["match_status"]) for candidate in mappings)
    checksum_payload = {
        "catalog_key": key,
        "catalog_checksum": exact_checksum,
        "mappings": mappings,
        "candidate_only": True,
    }
    crosswalk_checksum = hashlib.sha256(
        json.dumps(
            checksum_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "catalog_key": key,
        "catalog_checksum": exact_checksum,
        "crosswalk_status": "candidate_only",
        "candidate_only": True,
        "approved_mappings": [],
        "governed_feature_set_changed": False,
        "dataset_mutated": False,
        "mappings": mappings,
        "summary": dict(sorted(status_counts.items())),
        "crosswalk_checksum": crosswalk_checksum,
    }


__all__ = [
    "CatalogSelectionError",
    "CrosswalkContractError",
    "MatchStatus",
    "build_crosswalk_candidates",
    "build_dataset_crosswalk",
]

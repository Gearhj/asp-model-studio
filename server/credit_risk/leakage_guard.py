from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set

from fastapi import HTTPException


RESERVED_PATTERNS = [
    r"^id$",
    r"_id$",
    r"^acct(_|$)",
    r"account",
    r"customer",
    r"target",
    r"label",
    r"bad[_-]?flag",
    r"riskperformance",
    r"atlas[_-]?split",
    r"(^|_)split($|_)",
    r"score",
    r"prediction",
    r"predicted",
    r"probability",
    r"^pd$",
    r"race",
    r"gender",
    r"sex",
    r"ethnic",
    r"protected",
]


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def reserved_columns(target: str, dataset_meta: Dict[str, Any] | None = None, columns: Iterable[str] = ()) -> Set[str]:
    meta = dataset_meta or {}
    reserved = {_normalize(target)}
    source_info = meta.get("sourceInfo") or {}
    for key in ("originalTargetLabelColumn", "splitColumn", "targetColumn", "labelColumn"):
        reserved.add(_normalize(meta.get(key)))
        reserved.add(_normalize(source_info.get(key)))
    for column in columns:
        name = _normalize(column)
        lowered = name.lower()
        if any(re.search(pattern, lowered, re.I) for pattern in RESERVED_PATTERNS):
            reserved.add(name)
    return {value for value in reserved if value}


def validate_predictors(
    requested: Iterable[str],
    *,
    target: str,
    dataset_meta: Dict[str, Any] | None,
    columns: Iterable[str],
    explicit: bool,
) -> List[str]:
    available = [str(column) for column in columns]
    reserved = reserved_columns(target, dataset_meta, available)
    selected = [str(column) for column in requested if str(column) in available]
    blocked = [column for column in selected if column in reserved]
    if blocked and explicit:
        raise HTTPException(status_code=422, detail={"message": "Reserved leakage columns cannot be used as predictors.", "columns": blocked})
    return [column for column in selected if column not in reserved]


def default_predictors(*, target: str, dataset_meta: Dict[str, Any] | None, columns: Iterable[str], limit: int | None = None) -> List[str]:
    reserved = reserved_columns(target, dataset_meta, columns)
    predictors = [str(column) for column in columns if str(column) not in reserved]
    return predictors[:limit] if limit else predictors

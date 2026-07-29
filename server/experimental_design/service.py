from __future__ import annotations

from copy import deepcopy
from itertools import product
import hashlib
import json
import math
import random
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import Any, Dict, Iterable, List
from uuid import uuid4

import numpy as np

try:
    from scipy import stats
except Exception:  # pragma: no cover
    stats = None

from ..persistence.db import now_iso
from ..persistence.service import get_persistence_service
from ..security.security_store import audit_event


MAX_FACTORS = 8
MAX_LEVELS_PER_FACTOR = 8
MAX_DESIGN_RUNS = 1024
MAX_SIMULATION_ITERATIONS = 20_000
TERMINAL_JOB_STATES = {"complete", "failed", "cancelled", "interrupted"}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def default_contract(project_id: str, study_id: str | None = None) -> Dict[str, Any]:
    return {
        "schemaVersion": "atlas.experimental-design.study.v1",
        "studyId": study_id or _id("study"),
        "projectId": project_id,
        "title": "Untitled experimental study",
        "dataStrategy": {
            "mode": "prospective",
            "capturePlan": "",
            "provenanceNotes": "",
        },
        "objective": {
            "businessObjective": "",
            "decision": "",
            "population": "",
            "unitOfRandomization": "",
            "primaryResponse": {"name": "", "type": "continuous", "direction": "maximize", "unit": ""},
            "secondaryResponses": [],
            "nullHypothesis": "",
            "alternativeHypothesis": "",
            "successCriterion": "",
        },
        "factors": [],
        "nuisanceFactors": [],
        "blocking": {"enabled": False, "variables": [], "rationale": ""},
        "design": {
            "family": "",
            "analystConfirmed": False,
            "replicates": 1,
            "centerPoints": 3,
            "fraction": "half",
            "resolution": "IV",
            "rationale": "",
        },
        "power": {
            "alpha": 0.05,
            "targetPower": 0.8,
            "minimumDetectableEffect": 0.5,
            "standardDeviation": 1.0,
            "baselineRate": 0.1,
            "responseKind": "continuous",
            "effectsTested": 1,
        },
        "randomization": {"seed": 20260728, "restricted": False, "restriction": ""},
        "datasetBindings": [],
        "assumptions": [],
        "limitations": [],
        "analysisPlan": {"model": "factorial_anova", "includeInteractions": True, "multipleTesting": "hierarchical"},
    }


def normalize_contract(project_id: str, payload: Dict[str, Any], existing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    merged = _deep_merge(default_contract(project_id, (existing or {}).get("studyId")), existing or {})
    merged = _deep_merge(merged, payload or {})
    merged["schemaVersion"] = "atlas.experimental-design.study.v1"
    merged["projectId"] = project_id
    merged["studyId"] = str(merged.get("studyId") or _id("study"))
    merged["title"] = str(merged.get("title") or "Untitled experimental study").strip()[:240]

    factors: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(merged.get("factors") or [])[:MAX_FACTORS]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("factorName") or "").strip()[:120]
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        kind = str(raw.get("kind") or raw.get("type") or "categorical").lower()
        if kind not in {"categorical", "continuous", "ordinal"}:
            kind = "categorical"
        levels: List[str] = []
        for value in list(raw.get("levels") or [])[:MAX_LEVELS_PER_FACTOR]:
            cleaned = str(value).strip()[:120]
            if cleaned and cleaned not in levels:
                levels.append(cleaned)
        factors.append(
            {
                "factorId": str(raw.get("factorId") or _id("factor")),
                "name": name,
                "kind": kind,
                "levels": levels,
                "unit": str(raw.get("unit") or "").strip()[:80],
                "controllable": bool(raw.get("controllable", True)),
            }
        )
    merged["factors"] = factors

    nuisance: List[Dict[str, Any]] = []
    for raw in list(merged.get("nuisanceFactors") or [])[:MAX_FACTORS]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()[:120]
        if name:
            nuisance.append(
                {
                    "nuisanceId": str(raw.get("nuisanceId") or _id("nuisance")),
                    "name": name,
                    "strategy": str(raw.get("strategy") or "measure").lower(),
                    "levels": [str(value).strip()[:120] for value in list(raw.get("levels") or [])[:MAX_LEVELS_PER_FACTOR] if str(value).strip()],
                }
            )
    merged["nuisanceFactors"] = nuisance
    bindings: List[Dict[str, Any]] = []
    for raw in list(merged.get("datasetBindings") or [])[:12]:
        if not isinstance(raw, dict):
            continue
        dataset_id = str(raw.get("datasetId") or "").strip()
        version_id = str(raw.get("versionId") or "").strip()
        if dataset_id and version_id:
            bindings.append(
                {
                    "datasetId": dataset_id,
                    "versionId": version_id,
                    "datasetRole": str(raw.get("datasetRole") or "experimental_observations").strip(),
                    "name": str(raw.get("name") or "").strip()[:240],
                    "rowCount": raw.get("rowCount"),
                    "columnCount": raw.get("columnCount"),
                    "hash": str(raw.get("hash") or "").strip() or None,
                    "boundAt": str(raw.get("boundAt") or now_iso()),
                }
            )
    merged["datasetBindings"] = bindings

    design = merged.get("design") if isinstance(merged.get("design"), dict) else {}
    design["replicates"] = max(1, min(20, int(design.get("replicates") or 1)))
    design["centerPoints"] = max(1, min(20, int(design.get("centerPoints") or 3)))
    design["analystConfirmed"] = bool(design.get("analystConfirmed"))
    merged["design"] = design
    power = merged.get("power") if isinstance(merged.get("power"), dict) else {}
    power["alpha"] = max(0.0001, min(0.25, float(power.get("alpha") or 0.05)))
    power["targetPower"] = max(0.5, min(0.999, float(power.get("targetPower") or 0.8)))
    power["minimumDetectableEffect"] = max(1e-6, float(power.get("minimumDetectableEffect") or 0.5))
    power["standardDeviation"] = max(1e-6, float(power.get("standardDeviation") or 1.0))
    power["baselineRate"] = max(1e-6, min(1 - 1e-6, float(power.get("baselineRate") or 0.1)))
    power["effectsTested"] = max(1, min(128, int(power.get("effectsTested") or 1)))
    merged["power"] = power
    return merged


def contract_blockers(contract: Dict[str, Any]) -> List[Dict[str, str]]:
    blockers: List[Dict[str, str]] = []
    objective = contract.get("objective") or {}
    response = objective.get("primaryResponse") or {}
    if not str(objective.get("businessObjective") or "").strip():
        blockers.append({"code": "objective_required", "step": "1", "message": "Define the business objective."})
    if not str(objective.get("decision") or "").strip():
        blockers.append({"code": "decision_required", "step": "1", "message": "Define the decision this experiment will inform."})
    if not str(response.get("name") or "").strip():
        blockers.append({"code": "response_required", "step": "2", "message": "Name the primary response."})
    if not str(objective.get("unitOfRandomization") or "").strip():
        blockers.append({"code": "unit_required", "step": "2", "message": "Define the unit of randomization."})
    factors = contract.get("factors") or []
    if not factors:
        blockers.append({"code": "factors_required", "step": "3", "message": "Add at least one controllable factor."})
    for factor in factors:
        if len(factor.get("levels") or []) < 2:
            blockers.append({"code": "factor_levels_required", "step": "3", "message": f"{factor.get('name') or 'A factor'} needs at least two levels."})
    design = contract.get("design") or {}
    if not design.get("family") or not design.get("analystConfirmed"):
        blockers.append({"code": "design_confirmation_required", "step": "5", "message": "An analyst must explicitly choose and confirm a design family."})
    return blockers


def recommend_designs(contract: Dict[str, Any]) -> Dict[str, Any]:
    factors = contract.get("factors") or []
    nuisance = contract.get("nuisanceFactors") or []
    count = len(factors)
    all_two_level = bool(factors) and all(len(factor.get("levels") or []) == 2 for factor in factors)
    continuous_count = sum(factor.get("kind") == "continuous" for factor in factors)
    full_runs = math.prod(max(1, len(factor.get("levels") or [])) for factor in factors) if factors else 0
    catalog = [
        {"family": "full_factorial", "label": "Full factorial", "eligible": bool(factors) and full_runs <= MAX_DESIGN_RUNS, "estimatedRuns": full_runs, "strength": "All configured treatment combinations and interactions are unaliased.", "tradeoff": "Run count grows multiplicatively."},
        {"family": "fractional_factorial", "label": "Fractional factorial", "eligible": all_two_level and 4 <= count <= 8, "estimatedRuns": 2 ** max(2, count - 1) if all_two_level else None, "strength": "Screens several two-level factors with fewer runs.", "tradeoff": "Selected effects are aliased."},
        {
            "family": "randomized_block",
            "label": "Randomized complete block",
            "eligible": bool(factors) and bool(
                (contract.get("blocking") or {}).get("enabled")
                or (contract.get("blocking") or {}).get("variables")
                or any(item.get("strategy") == "block" for item in nuisance)
            ),
            "estimatedRuns": full_runs * max(1, len((contract.get("blocking") or {}).get("variables") or [])),
            "strength": "Separates known nuisance variation from treatment comparisons.",
            "tradeoff": "Requires treatment coverage within each block.",
        },
        {"family": "response_surface", "label": "Central composite response surface", "eligible": 2 <= continuous_count <= 5 and continuous_count == count, "estimatedRuns": (2 ** count + 2 * count + int((contract.get("design") or {}).get("centerPoints") or 3)) if count else None, "strength": "Estimates curvature for bounded continuous-factor optimization.", "tradeoff": "Requires meaningful numeric ranges."},
        {"family": "latin_square", "label": "Latin square", "eligible": bool(factors) and count == 1 and len(nuisance) >= 2 and len(factors[0].get("levels") or []) >= 3, "estimatedRuns": (len(factors[0].get("levels") or []) ** 2) if factors else None, "strength": "Controls two orthogonal nuisance dimensions.", "tradeoff": "Treatment and both blocks need the same order."},
    ]
    eligible = [item for item in catalog if item["eligible"]]
    recommendation = None
    if eligible:
        if full_runs and full_runs <= 64:
            recommendation = "randomized_block" if any(item["family"] == "randomized_block" for item in eligible) else "full_factorial"
        elif any(item["family"] == "fractional_factorial" for item in eligible):
            recommendation = "fractional_factorial"
        elif any(item["family"] == "response_surface" for item in eligible):
            recommendation = "response_surface"
        else:
            recommendation = eligible[0]["family"]
    rationale = next((item["strength"] for item in eligible if item["family"] == recommendation), "Complete factor definitions before comparing design families.")
    return {"ok": True, "recommendation": recommendation, "rationale": rationale, "catalog": catalog, "analystDecisionRequired": True, "warning": "ATLAS recommendations are advisory. A qualified analyst must confirm estimability tradeoffs."}


def _normal_cdf(value: float) -> float:
    return float(stats.norm.cdf(value)) if stats is not None else 0.5 * (1 + math.erf(value / math.sqrt(2)))


def _normal_ppf(value: float) -> float:
    if stats is not None:
        return float(stats.norm.ppf(value))
    low, high = -9.0, 9.0
    for _ in range(80):
        mid = (low + high) / 2
        if _normal_cdf(mid) < value:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _power_at_n(power: Dict[str, Any], per_cell: int) -> float:
    adjusted_alpha = float(power["alpha"]) / max(1, int(power.get("effectsTested") or 1))
    z_alpha = _normal_ppf(1 - adjusted_alpha / 2)
    effect = float(power["minimumDetectableEffect"])
    if str(power.get("responseKind") or "continuous") == "binary":
        p0 = float(power["baselineRate"])
        p1 = max(1e-6, min(1 - 1e-6, p0 + effect))
        pooled = (p0 + p1) / 2
        null_se = math.sqrt(max(1e-12, 2 * pooled * (1 - pooled) / per_cell))
        alt_se = math.sqrt(max(1e-12, (p0 * (1 - p0) + p1 * (1 - p1)) / per_cell))
        z = (abs(p1 - p0) - z_alpha * null_se) / alt_se
    else:
        z = effect * math.sqrt(per_cell / 2) / float(power["standardDeviation"]) - z_alpha
    return max(0.0, min(1.0, _normal_cdf(z)))


def calculate_power(contract: Dict[str, Any]) -> Dict[str, Any]:
    power = normalize_contract(str(contract.get("projectId") or ""), contract).get("power") or {}
    target = float(power["targetPower"])
    per_cell = 2
    while per_cell < 100_000 and _power_at_n(power, per_cell) < target:
        per_cell += 1
    factors = contract.get("factors") or []
    cells = max(2, math.prod(max(1, len(factor.get("levels") or [])) for factor in factors))
    curve_ns = sorted({max(2, int(per_cell * multiplier)) for multiplier in np.linspace(0.25, 1.75, 25)})
    return {
        "ok": True,
        "method": "normal_approximation_two_sided",
        "responseKind": power.get("responseKind"),
        "perCell": per_cell,
        "treatmentCells": cells,
        "totalSample": per_cell * cells,
        "achievedPower": _power_at_n(power, per_cell),
        "curve": [{"perCell": n, "total": n * cells, "power": _power_at_n(power, n)} for n in curve_ns],
        "assumptions": {
            "alpha": power["alpha"], "targetPower": target,
            "minimumDetectableEffect": power["minimumDetectableEffect"],
            "standardDeviation": power["standardDeviation"] if power.get("responseKind") != "binary" else None,
            "baselineRate": power["baselineRate"] if power.get("responseKind") == "binary" else None,
            "effectsTested": power["effectsTested"],
            "multiplicityAdjustment": "Bonferroni across declared effects" if int(power["effectsTested"]) > 1 else "None",
        },
        "warning": "This approximation does not replace simulation for complex blocking, attrition, clustering, or non-normal outcomes.",
    }


def _coded_value(level_index: int, level_count: int) -> float:
    return 0.0 if level_count <= 1 else -1.0 + 2.0 * level_index / (level_count - 1)


def _full_factorial_rows(factors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, combination in enumerate(product(*[factor.get("levels") or [] for factor in factors]), start=1):
        row: Dict[str, Any] = {"runId": f"R{index:04d}", "_coded": {}}
        for factor, value in zip(factors, combination):
            row[factor["name"]] = value
            row["_coded"][factor["name"]] = _coded_value(factor["levels"].index(value), len(factor["levels"]))
        rows.append(row)
    return rows


def _fractional_rows(factors: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    if len(factors) < 4 or any(len(factor.get("levels") or []) != 2 for factor in factors):
        raise ValueError("Fractional factorial generation requires four to eight two-level factors.")
    base_factors, generator_factor = factors[:-1], factors[-1]
    rows: List[Dict[str, Any]] = []
    for index, signs in enumerate(product([-1, 1], repeat=len(base_factors)), start=1):
        all_signs = [*signs, int(np.prod(signs))]
        row: Dict[str, Any] = {"runId": f"R{index:04d}", "_coded": {}}
        for factor, sign in zip(factors, all_signs):
            row[factor["name"]] = factor["levels"][0 if sign < 0 else 1]
            row["_coded"][factor["name"]] = float(sign)
        rows.append(row)
    defining_word = " × ".join(factor["name"] for factor in factors)
    aliases = [{"effect": factor["name"], "aliasedWith": " × ".join(other["name"] for other in factors if other["name"] != factor["name"]), "definingRelation": f"I = {defining_word}"} for factor in factors]
    aliases.insert(0, {"effect": generator_factor["name"], "aliasedWith": " × ".join(factor["name"] for factor in base_factors), "definingRelation": f"{generator_factor['name']} = {' × '.join(factor['name'] for factor in base_factors)}"})
    return rows, aliases


def _response_surface_rows(factors: List[Dict[str, Any]], center_points: int) -> List[Dict[str, Any]]:
    if not 2 <= len(factors) <= 5 or any(factor.get("kind") != "continuous" or len(factor.get("levels") or []) < 2 for factor in factors):
        raise ValueError("Response-surface generation requires two to five continuous factors with numeric low and high levels.")
    k, alpha = len(factors), math.sqrt(len(factors))
    coded_rows = list(product([-1.0, 1.0], repeat=k))
    coded_rows += [tuple(alpha if axis == index else 0.0 for axis in range(k)) for index in range(k)]
    coded_rows += [tuple(-alpha if axis == index else 0.0 for axis in range(k)) for index in range(k)]
    coded_rows += [tuple(0.0 for _ in range(k)) for _ in range(center_points)]
    rows: List[Dict[str, Any]] = []
    try:
        for coded_values in coded_rows:
            row: Dict[str, Any] = {"runId": f"R{len(rows) + 1:04d}", "_coded": {}}
            for factor, coded in zip(factors, coded_values):
                low, high = float(factor["levels"][0]), float(factor["levels"][-1])
                row[factor["name"]] = (low + high) / 2 + coded * (high - low) / 2
                row["_coded"][factor["name"]] = coded
            rows.append(row)
    except (TypeError, ValueError) as exc:
        raise ValueError("Response-surface factor levels must be numeric.") from exc
    return rows


def _latin_square_rows(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    factors, nuisance = contract.get("factors") or [], contract.get("nuisanceFactors") or []
    if len(factors) != 1 or len(nuisance) < 2:
        raise ValueError("Latin-square generation requires one treatment factor and two nuisance factors.")
    levels, order = factors[0].get("levels") or [], len(factors[0].get("levels") or [])
    block_a = nuisance[0].get("levels") or [f"{nuisance[0]['name']} {index + 1}" for index in range(order)]
    block_b = nuisance[1].get("levels") or [f"{nuisance[1]['name']} {index + 1}" for index in range(order)]
    if len(block_a) != order or len(block_b) != order:
        raise ValueError("Latin-square treatment and both nuisance factors must have the same number of levels.")
    rows = []
    for i in range(order):
        for j in range(order):
            treatment = levels[(i + j) % order]
            rows.append({"runId": f"R{len(rows) + 1:04d}", factors[0]["name"]: treatment, nuisance[0]["name"]: block_a[i], nuisance[1]["name"]: block_b[j], "_coded": {factors[0]["name"]: _coded_value(levels.index(treatment), order)}})
    return rows


def generate_design(contract: Dict[str, Any]) -> Dict[str, Any]:
    blockers = contract_blockers(contract)
    if {item["code"] for item in blockers} & {"factors_required", "factor_levels_required", "design_confirmation_required"}:
        raise ValueError("Study contract is not ready: " + " ".join(item["message"] for item in blockers))
    factors, design = contract.get("factors") or [], contract.get("design") or {}
    family, aliases = str(design.get("family") or ""), []
    if family == "fractional_factorial":
        rows, aliases = _fractional_rows(factors)
    elif family == "response_surface":
        rows = _response_surface_rows(factors, int(design.get("centerPoints") or 3))
    elif family == "latin_square":
        rows = _latin_square_rows(contract)
    elif family in {"full_factorial", "randomized_block"}:
        rows = _full_factorial_rows(factors)
        if family == "randomized_block":
            block_variables = (contract.get("blocking") or {}).get("variables") or [item.get("name") for item in contract.get("nuisanceFactors") or [] if item.get("name")]
            if block_variables:
                nuisance = next((item for item in contract.get("nuisanceFactors") or [] if item.get("name") == str(block_variables[0])), {})
                expanded = []
                for block in nuisance.get("levels") or ["Block 1", "Block 2"]:
                    for row in rows:
                        expanded.append({**deepcopy(row), "block": block, "runId": f"R{len(expanded) + 1:04d}"})
                rows = expanded
    else:
        raise ValueError("Choose and confirm a supported design family before generation.")
    if int(design.get("replicates") or 1) > 1:
        original, rows = rows, []
        for replicate in range(1, int(design["replicates"]) + 1):
            for source in original:
                rows.append({**deepcopy(source), "runId": f"R{len(rows) + 1:04d}", "replicate": replicate})
    if len(rows) > MAX_DESIGN_RUNS:
        raise ValueError(f"Requested design has {len(rows)} runs; ATLAS limits one design to {MAX_DESIGN_RUNS}.")
    version = f"design-{_canonical_hash({'family': family, 'rows': rows})[:16]}"
    return {
        "ok": True, "designVersion": version, "family": family, "runCount": len(rows),
        "factorNames": [factor["name"] for factor in factors], "rows": rows, "aliasStructure": aliases,
        "estimability": {
            "mainEffects": "estimable",
            "twoFactorInteractions": "aliased" if aliases else "estimable where replication and residual degrees of freedom permit",
            "curvature": "estimable" if family == "response_surface" else "not included",
        },
        "generatedAt": now_iso(), "contractHash": _canonical_hash(contract),
    }


def randomize_design(design: Dict[str, Any], contract: Dict[str, Any], seed: int | None = None) -> Dict[str, Any]:
    rows = deepcopy(design.get("rows") or [])
    if not rows:
        raise ValueError("Generate a design matrix before randomization.")
    resolved_seed = int(seed if seed is not None else (contract.get("randomization") or {}).get("seed") or 0)
    rng, randomized = random.Random(resolved_seed), []
    if any("block" in row for row in rows):
        blocks: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            blocks.setdefault(str(row.get("block")), []).append(row)
        for block, block_rows in sorted(blocks.items()):
            rng.shuffle(block_rows)
            randomized.extend({**row, "randomizedOrderWithinBlock": index, "block": block} for index, row in enumerate(block_rows, start=1))
        method = "blocked_permutation"
    else:
        rng.shuffle(rows)
        randomized, method = rows, "complete_random_permutation"
    for order, row in enumerate(randomized, start=1):
        row["runOrder"] = order
    return {"ok": True, "randomizationVersion": f"randomization-{_canonical_hash({'seed': resolved_seed, 'rows': randomized})[:16]}", "designVersion": design.get("designVersion"), "seed": resolved_seed, "method": method, "rows": randomized, "generatedAt": now_iso()}


def analyze_observations(design: Dict[str, Any], observations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    response_by_run: Dict[str, float] = {}
    for item in observations:
        try:
            value = float(item.get("response"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            response_by_run[str(item.get("runId") or item.get("run_id") or "")] = value
    rows = [row for row in design.get("rows") or [] if str(row.get("runId")) in response_by_run]
    if len(rows) < 4:
        raise ValueError("At least four finite observed responses matched to generated run IDs are required.")
    y = np.asarray([response_by_run[str(row["runId"])] for row in rows], dtype=float)
    factor_names = list(design.get("factorNames") or [])
    cells: Dict[str, List[float]] = {}
    for row, value in zip(rows, y):
        cells.setdefault(" | ".join(f"{name}={row.get(name)}" for name in factor_names), []).append(float(value))
    groups, grand = [np.asarray(values) for values in cells.values()], float(np.mean(y))
    ss_between = float(sum(len(group) * (float(np.mean(group)) - grand) ** 2 for group in groups))
    ss_error = float(sum(np.sum((group - np.mean(group)) ** 2) for group in groups))
    df_between, df_error = max(0, len(groups) - 1), max(0, len(y) - len(groups))
    ms_between = ss_between / df_between if df_between else None
    ms_error = ss_error / df_error if df_error else None
    f_value = ms_between / ms_error if ms_between is not None and ms_error not in (None, 0) else None
    p_value = float(stats.f.sf(f_value, df_between, df_error)) if stats is not None and f_value is not None and df_error > 0 else None
    effects = []
    for name in factor_names:
        grouped: Dict[str, List[float]] = {}
        for row, value in zip(rows, y):
            grouped.setdefault(str(row.get(name)), []).append(float(value))
        means = [{"level": level, "mean": float(np.mean(values)), "n": len(values)} for level, values in sorted(grouped.items())]
        effects.append({"term": name, "estimate": float(means[-1]["mean"] - means[0]["mean"]) if len(means) >= 2 else 0.0, "levelMeans": means, "kind": "main_effect"})
    two_level = [(name, sorted({str(row.get(name)) for row in rows})) for name in factor_names if len({str(row.get(name)) for row in rows}) == 2]
    for left_index in range(len(two_level)):
        for right_index in range(left_index + 1, len(two_level)):
            left, left_levels = two_level[left_index]
            right, right_levels = two_level[right_index]
            contrast = [(-1 if str(row.get(left)) == left_levels[0] else 1) * (-1 if str(row.get(right)) == right_levels[0] else 1) * float(value) for row, value in zip(rows, y)]
            effects.append({"term": f"{left} × {right}", "estimate": float(2 * np.mean(contrast)), "kind": "two_factor_interaction"})
    fitted = np.asarray([float(np.mean(cells[" | ".join(f"{name}={row.get(name)}" for name in factor_names)])) for row in rows])
    residuals = y - fitted
    best_cell, best_values = max(cells.items(), key=lambda item: float(np.mean(item[1])))
    return {
        "ok": True, "status": "observed_analysis", "designVersion": design.get("designVersion"),
        "observationCount": len(y), "cellCount": len(cells),
        "anovaTable": [
            {"source": "Treatment cells", "df": df_between, "sumSquares": ss_between, "meanSquare": ms_between, "f": f_value, "p": p_value},
            {"source": "Residual", "df": df_error, "sumSquares": ss_error, "meanSquare": ms_error, "f": None, "p": None},
            {"source": "Total", "df": len(y) - 1, "sumSquares": float(np.sum((y - grand) ** 2)), "meanSquare": None, "f": None, "p": None},
        ],
        "effects": sorted(effects, key=lambda item: abs(float(item["estimate"])), reverse=True),
        "residualDiagnostics": {
            "mean": float(np.mean(residuals)),
            "standardDeviation": float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0,
            "shapiroP": float(stats.shapiro(residuals).pvalue) if stats is not None and 3 <= len(residuals) <= 5000 and np.std(residuals) > 0 else None,
            "points": [{"fitted": float(fit), "residual": float(residual)} for fit, residual in list(zip(fitted, residuals))[:500]],
        },
        "recommendation": {"bestObservedCell": best_cell, "meanResponse": float(np.mean(best_values)), "basis": "Highest observed cell mean; confirm uncertainty, constraints, and practical significance before deployment."},
        "warnings": ["Results are descriptive when residual degrees of freedom are zero or replication is insufficient.", "Causal interpretation requires adherence to randomization and protocol."],
        "analyzedAt": now_iso(),
    }


class ExperimentalDesignService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cancel_events: Dict[str, Event] = {}
        self._capacity = BoundedSemaphore(2)
        self._recovery_database: str | None = None

    @property
    def repository(self):
        repository = get_persistence_service().experimental_design
        database_key = str(repository.database.path)
        if self._recovery_database != database_key:
            repository.interrupt_active_jobs()
            self._recovery_database = database_key
        return repository

    @staticmethod
    def _public_study(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "studyId": record["study_id"], "projectId": record["project_id"],
            "currentVersion": int(record.get("current_version") or 0), "status": record.get("status") or "draft",
            "contractHash": record.get("contract_hash"), "contract": record.get("contract_json") or {},
            "artifacts": record.get("artifacts_json") or {}, "blockers": record.get("blockers_json") or [],
            "createdBy": record.get("created_by"), "updatedBy": record.get("updated_by"),
            "createdAt": record.get("created_at"), "updatedAt": record.get("updated_at"),
        }

    @staticmethod
    def _public_version(record: Dict[str, Any]) -> Dict[str, Any]:
        return {"studyVersionId": record["study_version_id"], "studyId": record["study_id"], "versionNumber": int(record["version_number"]), "contractHash": record["contract_hash"], "changeSummary": record.get("change_summary"), "createdBy": record.get("created_by"), "createdAt": record.get("created_at")}

    @staticmethod
    def _public_job(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "simulationJobId": record["simulation_job_id"], "projectId": record["project_id"],
            "studyId": record["study_id"], "studyVersion": int(record["study_version"]),
            "designVersion": record["design_version"], "status": record["status"],
            "progress": float(record.get("progress") or 0), "seed": int(record["seed"]),
            "iterations": int(record["iterations"]), "parameters": record.get("parameters_json") or {},
            "results": record.get("results_json") or {}, "error": record.get("error_json") or {},
            "cancellationRequested": bool(record.get("cancellation_requested")),
            "retryParentJobId": record.get("retry_parent_job_id"), "createdAt": record.get("created_at"),
            "startedAt": record.get("started_at"), "completedAt": record.get("completed_at"), "updatedAt": record.get("updated_at"),
        }

    def read(self, project_id: str) -> Dict[str, Any]:
        record = self.repository.get_for_project(project_id)
        if not record:
            contract = default_contract(project_id)
            return {"ok": True, "persisted": False, "study": {"studyId": contract["studyId"], "projectId": project_id, "currentVersion": 0, "status": "draft", "contract": contract, "artifacts": {}, "blockers": contract_blockers(contract)}, "versions": [], "jobs": []}
        # Additive schema defaults are projected for older persisted studies
        # without mutating their immutable historical versions.
        record["contract_json"] = normalize_contract(
            project_id,
            {},
            record.get("contract_json") or {},
        )
        record["blockers_json"] = contract_blockers(record["contract_json"])
        return {"ok": True, "persisted": True, "study": self._public_study(record), "versions": [self._public_version(row) for row in self.repository.list_versions(project_id)], "jobs": [self._public_job(row) for row in self.repository.list_jobs(project_id)[:20]]}

    def save(self, project_id: str, payload: Dict[str, Any], user: Dict[str, Any], change_summary: str = "") -> Dict[str, Any]:
        existing_record = self.repository.get_for_project(project_id)
        existing_contract = (existing_record or {}).get("contract_json") or None
        contract = normalize_contract(project_id, payload, existing_contract)
        contract_hash = _canonical_hash(contract)
        if existing_record and contract_hash == existing_record.get("contract_hash"):
            return {"ok": True, "changed": False, "study": self._public_study(existing_record)}
        version = int((existing_record or {}).get("current_version") or 0) + 1
        artifacts = deepcopy((existing_record or {}).get("artifacts_json") or {})
        changed_sections = {key for key in ("dataStrategy", "datasetBindings", "objective", "factors", "nuisanceFactors", "blocking", "design", "power", "randomization", "analysisPlan") if (existing_contract or {}).get(key) != contract.get(key)}
        invalidation_map = {
            "objective": ["power", "design", "randomization", "simulation", "analysis", "documentation"],
            "dataStrategy": ["analysis", "documentation"],
            "datasetBindings": ["analysis", "documentation"],
            "factors": ["power", "design", "randomization", "simulation", "analysis", "documentation"],
            "nuisanceFactors": ["design", "randomization", "simulation", "analysis", "documentation"],
            "blocking": ["design", "randomization", "simulation", "analysis", "documentation"],
            "design": ["design", "randomization", "simulation", "analysis", "documentation"],
            "power": ["power", "simulation", "documentation"], "randomization": ["randomization", "documentation"],
            "analysisPlan": ["analysis", "documentation"],
        }
        invalidated: List[str] = []
        for section in changed_sections:
            for key in invalidation_map.get(section, []):
                if key in artifacts:
                    artifacts.pop(key, None)
                    invalidated.append(key)
        blockers, timestamp, actor = contract_blockers(contract), now_iso(), str(user.get("userId") or "")
        record = self.repository.upsert_study(
            {
                "study_id": contract["studyId"], "project_id": project_id, "current_version": version,
                "status": "ready_for_design" if not blockers else "draft", "contract_hash": contract_hash,
                "contract_json": contract, "artifacts_json": artifacts, "blockers_json": blockers,
                "created_by": (existing_record or {}).get("created_by") or actor, "updated_by": actor,
                "created_at": (existing_record or {}).get("created_at") or timestamp, "updated_at": timestamp,
            }
        )
        version_record = self.repository.add_version(
            {
                "study_version_id": _id("study-version"), "study_id": contract["studyId"], "project_id": project_id,
                "version_number": version, "contract_hash": contract_hash,
                "change_summary": change_summary or f"Updated {', '.join(sorted(changed_sections)) or 'study contract'}.",
                "contract_json": contract, "artifacts_json": artifacts, "created_by": actor, "created_at": timestamp,
            }
        )
        self._capture_evidence(
            project_id,
            user,
            "experimental-design-1",
            "study_contract",
            f"Experimental Design study contract v{version}",
            f"Immutable study contract snapshot {version} ({contract_hash[:12]}).",
            {
                "studyId": contract["studyId"],
                "studyVersion": version,
                "contractHash": contract_hash,
                "contract": contract,
                "invalidatedArtifacts": sorted(set(invalidated)),
            },
        )
        if "design" in changed_sections and contract.get("design", {}).get("analystConfirmed"):
            get_persistence_service().decisions.upsert(
                {
                    "decision_id": f"experimental-design-family-{contract['studyId']}-v{version}",
                    "project_id": project_id,
                    "decision_type": "experimental_design_family_selection",
                    "title": f"Design family: {str(contract['design'].get('family') or '').replace('_', ' ').title()}",
                    "summary": contract["design"].get("rationale") or "Analyst confirmed the design family and estimability tradeoffs.",
                    "status": "confirmed",
                    "owner": actor,
                    "created_by": actor,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "payload_json": {
                        "studyId": contract["studyId"],
                        "studyVersion": version,
                        "contractHash": contract_hash,
                        "design": contract["design"],
                    },
                }
            )
        audit_event("experimental_design.study.versioned", "experimental_design_study", contract["studyId"], "success", user_id=actor, metadata={"projectId": project_id, "version": version, "changedSections": sorted(changed_sections), "invalidatedArtifacts": sorted(set(invalidated))})
        return {"ok": True, "changed": True, "study": self._public_study(record), "version": self._public_version(version_record), "invalidatedArtifacts": sorted(set(invalidated))}

    def _require_study(self, project_id: str) -> Dict[str, Any]:
        record = self.repository.get_for_project(project_id)
        if not record:
            raise ValueError("Save the study contract before running analytical operations.")
        return record

    def _update_artifact(self, record: Dict[str, Any], key: str, artifact: Dict[str, Any], actor: str) -> Dict[str, Any]:
        artifacts = deepcopy(record.get("artifacts_json") or {})
        artifacts[key] = artifact
        return self._public_study(self.repository.upsert_study({**record, "artifacts_json": artifacts, "updated_by": actor, "updated_at": now_iso()}))

    def power(self, project_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        record = self._require_study(project_id)
        result = {**calculate_power(record["contract_json"]), "studyId": record["study_id"], "studyVersion": int(record["current_version"]), "contractHash": record["contract_hash"], "calculatedAt": now_iso()}
        return {**result, "study": self._update_artifact(record, "power", result, str(user.get("userId") or ""))}

    def design(self, project_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        record = self._require_study(project_id)
        result = {**generate_design(record["contract_json"]), "studyId": record["study_id"], "studyVersion": int(record["current_version"]), "generatedBy": user.get("userId")}
        study = self._update_artifact(record, "design", result, str(user.get("userId") or ""))
        self._capture_evidence(project_id, user, "experimental-design-7", "design_matrix", "Governed experimental design matrix", f"{result['family']} design with {result['runCount']} runs.", result)
        audit_event("experimental_design.matrix.generated", "experimental_design_study", record["study_id"], "success", user_id=user.get("userId"), metadata={"projectId": project_id, "designVersion": result["designVersion"], "runCount": result["runCount"]})
        return {**result, "study": study}

    def randomize(self, project_id: str, user: Dict[str, Any], seed: int | None = None) -> Dict[str, Any]:
        record = self._require_study(project_id)
        result = {**randomize_design((record.get("artifacts_json") or {}).get("design") or {}, record["contract_json"], seed), "studyId": record["study_id"], "studyVersion": int(record["current_version"]), "generatedBy": user.get("userId")}
        study = self._update_artifact(record, "randomization", result, str(user.get("userId") or ""))
        self._capture_evidence(project_id, user, "experimental-design-8", "randomization_plan", "Reproducible experimental run order", f"{result['method']} with persisted seed {result['seed']}.", result)
        return {**result, "study": study}

    def create_simulation(self, project_id: str, user: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
        record = self._require_study(project_id)
        design = (record.get("artifacts_json") or {}).get("design") or {}
        if not design.get("designVersion"):
            raise ValueError("Generate a current design matrix before simulation.")
        iterations = max(100, min(MAX_SIMULATION_ITERATIONS, int(parameters.get("iterations") or 2500)))
        seed = int(parameters.get("seed") or (record["contract_json"].get("randomization") or {}).get("seed") or 0)
        timestamp, job_id = now_iso(), _id("simulation")
        job = self.repository.upsert_job(
            {
                "simulation_job_id": job_id, "project_id": project_id, "study_id": record["study_id"],
                "study_version": int(record["current_version"]), "design_version": design["designVersion"],
                "owner_user_id": str(user.get("userId") or ""), "status": "queued", "progress": 0,
                "seed": seed, "iterations": iterations,
                "parameters_json": {
                    "effectSize": float(parameters.get("effectSize") or (record["contract_json"].get("power") or {}).get("minimumDetectableEffect") or 0.5),
                    "standardDeviation": max(1e-6, float(parameters.get("standardDeviation") or (record["contract_json"].get("power") or {}).get("standardDeviation") or 1)),
                    "alpha": float(parameters.get("alpha") or (record["contract_json"].get("power") or {}).get("alpha") or 0.05),
                    "samplePerCell": max(2, int(parameters.get("samplePerCell") or ((record.get("artifacts_json") or {}).get("power") or {}).get("perCell") or 20)),
                },
                "results_json": {}, "error_json": {}, "created_at": timestamp, "updated_at": timestamp,
            }
        )
        get_persistence_service().runs.upsert(
            {
                "run_id": job_id,
                "project_id": project_id,
                "run_type": "experimental_design_simulation",
                "workflow_type": "experimental-design",
                "status": "queued",
                "started_at": timestamp,
                "parameters_json": job.get("parameters_json") or {},
                "metrics_json": {},
                "artifacts_json": {
                    "studyId": record["study_id"],
                    "studyVersion": int(record["current_version"]),
                    "designVersion": design["designVersion"],
                },
                "error_json": {},
                "created_by": user.get("userId"),
            }
        )
        cancel_event = Event()
        with self._lock:
            self._cancel_events[job_id] = cancel_event
        Thread(target=self._run_simulation, args=(job_id, cancel_event), daemon=True, name=f"atlas-experimental-design-{job_id[-8:]}").start()
        audit_event("experimental_design.simulation.started", "experimental_design_simulation", job_id, "success", user_id=user.get("userId"), metadata={"projectId": project_id, "studyVersion": int(record["current_version"]), "iterations": iterations})
        return {"ok": True, "job": self._public_job(job)}

    def _run_simulation(self, job_id: str, cancel_event: Event) -> None:
        with self._capacity:
            job = self.repository.get_job(job_id)
            if not job:
                return
            if cancel_event.is_set():
                self._finish_cancel(job)
                return
            job.update({"status": "running", "started_at": now_iso(), "progress": 0.01})
            self.repository.upsert_job(job)
            try:
                rng, params, iterations = np.random.default_rng(int(job["seed"])), job.get("parameters_json") or {}, int(job["iterations"])
                effect, sigma = float(params.get("effectSize") or 0.5), float(params.get("standardDeviation") or 1)
                per_cell, alpha = int(params.get("samplePerCell") or 20), float(params.get("alpha") or 0.05)
                se, critical, detected, wrong_direction = sigma * math.sqrt(2 / max(2, per_cell)), _normal_ppf(1 - alpha / 2), 0, 0
                estimates: List[float] = []
                for offset in range(0, iterations, 250):
                    if cancel_event.is_set():
                        self._finish_cancel(self.repository.get_job(job_id) or job)
                        return
                    size = min(250, iterations - offset)
                    chunk = rng.normal(effect, se, size=size)
                    detected += int(np.sum(np.abs(chunk / se) >= critical))
                    wrong_direction += int(np.sum(chunk < 0))
                    estimates.extend(float(value) for value in chunk[: min(size, 50)])
                    if offset == 0 or offset + size == iterations or (offset // 250) % 4 == 0:
                        current = self.repository.get_job(job_id) or job
                        current.update({"status": "running", "progress": min(0.99, (offset + size) / iterations)})
                        self.repository.upsert_job(current)
                result = {
                    "empiricalPower": detected / iterations, "wrongDirectionRate": wrong_direction / iterations,
                    "falseNegativeRate": 1 - detected / iterations, "meanEstimatedEffect": effect,
                    "standardError": se, "iterations": iterations, "seed": int(job["seed"]),
                    "samplePerCell": per_cell, "effectSize": effect, "standardDeviation": sigma, "alpha": alpha,
                    "estimateSample": estimates[:500], "scope": "simulated_operating_characteristics",
                    "warning": "Simulated operating characteristics under declared assumptions, not observed results.",
                }
                current = self.repository.get_job(job_id) or job
                current.update({"status": "complete", "progress": 1.0, "results_json": result, "error_json": {}, "completed_at": now_iso()})
                completed = self.repository.upsert_job(current)
                get_persistence_service().runs.upsert(
                    {
                        "run_id": job_id,
                        "project_id": current["project_id"],
                        "run_type": "experimental_design_simulation",
                        "workflow_type": "experimental-design",
                        "status": "complete",
                        "started_at": current.get("started_at"),
                        "completed_at": current.get("completed_at"),
                        "parameters_json": current.get("parameters_json") or {},
                        "metrics_json": result,
                        "artifacts_json": {
                            "studyId": current["study_id"],
                            "studyVersion": int(current["study_version"]),
                            "designVersion": current["design_version"],
                        },
                        "error_json": {},
                        "created_by": current["owner_user_id"],
                    }
                )
                study_record = self.repository.get(current["study_id"])
                if study_record and int(study_record["current_version"]) == int(current["study_version"]):
                    self._update_artifact(study_record, "simulation", self._public_job(completed), current["owner_user_id"])
                    self._capture_evidence(current["project_id"], {"userId": current["owner_user_id"]}, "experimental-design-9", "simulation_results", "Experimental design operating-characteristic simulation", f"{iterations} deterministic iterations completed under seed {current['seed']}.", result)
                audit_event("experimental_design.simulation.completed", "experimental_design_simulation", job_id, "success", user_id=current["owner_user_id"], metadata={"projectId": current["project_id"], "empiricalPower": result["empiricalPower"]})
            except Exception as exc:  # noqa: BLE001
                current = self.repository.get_job(job_id) or job
                current.update({"status": "failed", "error_json": {"code": "simulation_failed", "message": str(exc), "recoverable": True}, "completed_at": now_iso()})
                self.repository.upsert_job(current)
                get_persistence_service().runs.upsert(
                    {
                        "run_id": job_id,
                        "project_id": current["project_id"],
                        "run_type": "experimental_design_simulation",
                        "workflow_type": "experimental-design",
                        "status": "failed",
                        "started_at": current.get("started_at"),
                        "completed_at": current.get("completed_at"),
                        "parameters_json": current.get("parameters_json") or {},
                        "metrics_json": {},
                        "artifacts_json": {"studyId": current["study_id"], "designVersion": current["design_version"]},
                        "error_json": current.get("error_json") or {},
                        "created_by": current["owner_user_id"],
                    }
                )
            finally:
                with self._lock:
                    self._cancel_events.pop(job_id, None)

    def _finish_cancel(self, job: Dict[str, Any]) -> None:
        job.update({"status": "cancelled", "cancellation_requested": True, "completed_at": now_iso(), "error_json": {"code": "cancelled", "message": "Simulation cancelled by the user.", "recoverable": True}})
        self.repository.upsert_job(job)

    def get_job(self, project_id: str, job_id: str) -> Dict[str, Any]:
        job = self.repository.get_job(job_id)
        if not job or job.get("project_id") != project_id:
            raise KeyError("Simulation job not found under this project.")
        return {"ok": True, "job": self._public_job(job)}

    def cancel_job(self, project_id: str, job_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        job = self.repository.get_job(job_id)
        if not job or job.get("project_id") != project_id:
            raise KeyError("Simulation job not found under this project.")
        if job["status"] in TERMINAL_JOB_STATES:
            return {"ok": True, "job": self._public_job(job)}
        job.update({"cancellation_requested": True, "status": "cancelling"})
        updated = self.repository.upsert_job(job)
        with self._lock:
            event = self._cancel_events.get(job_id)
            if event:
                event.set()
        audit_event("experimental_design.simulation.cancel.requested", "experimental_design_simulation", job_id, "success", user_id=user.get("userId"), metadata={"projectId": project_id})
        return {"ok": True, "job": self._public_job(updated)}

    def retry_job(self, project_id: str, job_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        job = self.repository.get_job(job_id)
        if not job or job.get("project_id") != project_id:
            raise KeyError("Simulation job not found under this project.")
        if job["status"] not in {"failed", "cancelled", "interrupted"}:
            raise ValueError("Only failed, cancelled, or interrupted simulations can be retried.")
        parameters = {**(job.get("parameters_json") or {}), "iterations": job["iterations"], "seed": job["seed"]}
        result = self.create_simulation(project_id, user, parameters)
        retry_id = result["job"]["simulationJobId"]
        with self.repository.database.transaction() as connection:
            connection.execute("UPDATE experimental_design_simulation_jobs SET retry_parent_job_id = ?, updated_at = ? WHERE simulation_job_id = ?", (job_id, now_iso(), retry_id))
        return self.get_job(project_id, retry_id)

    def analyze(self, project_id: str, user: Dict[str, Any], observations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        record = self._require_study(project_id)
        design = (record.get("artifacts_json") or {}).get("design") or {}
        if not design:
            raise ValueError("Generate a current design before analysis.")
        result = {**analyze_observations(design, observations), "studyId": record["study_id"], "studyVersion": int(record["current_version"]), "analyzedBy": user.get("userId")}
        study = self._update_artifact(record, "analysis", result, str(user.get("userId") or ""))
        self._capture_evidence(project_id, user, "experimental-design-10", "observed_analysis", "Observed experimental analysis", f"ANOVA and effect review for {result['observationCount']} observations.", result)
        return {**result, "study": study}

    def capture_documentation(self, project_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        record = self._require_study(project_id)
        study, artifacts = self._public_study(record), (record.get("artifacts_json") or {})
        sections = [
            ("Study charter", bool(study["contract"].get("objective", {}).get("businessObjective"))),
            ("Responses and hypotheses", bool(study["contract"].get("objective", {}).get("primaryResponse", {}).get("name"))),
            ("Factors, levels, and nuisance structure", bool(study["contract"].get("factors"))),
            ("Design selection and estimability", bool(artifacts.get("design"))),
            ("Power and sample size", bool(artifacts.get("power"))),
            ("Randomization and run plan", bool(artifacts.get("randomization"))),
            ("Simulation assumptions and results", bool(artifacts.get("simulation"))),
            ("Observed analysis", bool(artifacts.get("analysis"))),
            ("Decision, limitations, and reproducibility", bool(study["contract"].get("limitations") is not None)),
        ]
        completed, readiness = sum(1 for _, ready in sections if ready), round(100 * sum(1 for _, ready in sections if ready) / len(sections))
        package_id = f"experimental-design-package-{record['study_id']}"
        payload = {
            "schemaVersion": "atlas.experimental-design.documentation.v1", "study": study,
            "sections": [{"title": title, "status": "ready" if ready else "missing"} for title, ready in sections],
            "reproducibility": {
                "contractHash": record["contract_hash"], "studyVersion": int(record["current_version"]),
                "designVersion": (artifacts.get("design") or {}).get("designVersion"),
                "randomizationSeed": (artifacts.get("randomization") or {}).get("seed"),
                "simulationJobId": (artifacts.get("simulation") or {}).get("simulationJobId"),
            },
            "generatedAt": now_iso(), "generatedBy": user.get("userId"),
        }
        package = get_persistence_service().documentation.upsert(
            {
                "package_id": package_id, "project_id": project_id, "package_type": "experimental_design_report",
                "status": "ready" if readiness == 100 else "draft", "readiness_score": readiness,
                "section_count": len(sections), "completed_section_count": completed,
                "payload_json": payload, "created_by": user.get("userId"), "updated_at": now_iso(),
            }
        )
        artifact = {"packageId": package_id, "status": package.get("status"), "readinessScore": readiness, "sections": payload["sections"], "generatedAt": payload["generatedAt"]}
        self._update_artifact(record, "documentation", artifact, str(user.get("userId") or ""))
        evidence = self._capture_evidence(project_id, user, "experimental-design-12", "documentation_package", "Experimental Design evidence package", f"Documentation readiness is {readiness}%.", payload)
        audit_event("experimental_design.documentation.generated", "documentation", package_id, "success", user_id=user.get("userId"), metadata={"projectId": project_id, "readinessScore": readiness})
        return {"ok": True, "documentation": artifact, "package": package, "evidence": evidence}

    @staticmethod
    def _capture_evidence(project_id: str, user: Dict[str, Any], step_id: str, artifact_type: str, title: str, summary: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        artifact_hash = _canonical_hash(payload)
        return get_persistence_service().evidence.upsert(
            {
                "evidence_id": f"experimental-design-{artifact_type}-{artifact_hash[:16]}",
                "project_id": project_id, "workflow_type": "experimental-design", "step_id": step_id,
                "artifact_type": artifact_type, "status": "captured", "title": title, "summary": summary,
                "source_ref": f"/workflow/experimental-design/{step_id.rsplit('-', 1)[-1]}",
                "artifact_hash": artifact_hash, "created_by": user.get("userId"),
                "created_at": now_iso(), "captured_at": now_iso(), "payload_json": payload,
            }
        )


EXPERIMENTAL_DESIGN = ExperimentalDesignService()

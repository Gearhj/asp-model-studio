from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


router = APIRouter()

SITL_ROOT = Path(__file__).resolve().parents[2] / "sitl-sdk"
V04_ROOT = SITL_ROOT / "data" / "stela" / "validation_runs" / "v0.4"

DATASETS = [
    {
        "id": "retail_banking",
        "label": "Bitext Retail Banking Holdout",
        "summary": V04_ROOT / "holdout_bitext_retail_banking_250_summary.json",
        "eval": V04_ROOT / "holdout_bitext_retail_banking_250_eval.jsonl",
    },
    {
        "id": "mortgage_loans",
        "label": "Bitext Mortgage / Loans Holdout",
        "summary": V04_ROOT / "holdout_bitext_mortgage_loans_250_summary.json",
        "eval": V04_ROOT / "holdout_bitext_mortgage_loans_250_eval.jsonl",
    },
]


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def estimate_token_change(row: Dict[str, Any]) -> int | float | None:
    comparison = row.get("comparison") or {}
    original = comparison.get("original_estimated_output_tokens")
    stela = comparison.get("stela_estimated_output_tokens")
    if original is None or stela is None:
        return None
    return stela - original


def outcome_from_delta(delta: int | float | None) -> str:
    if delta is None:
        return "unknown"
    if delta > 0:
        return "improved"
    if delta < 0:
        return "worsened"
    return "unchanged"


def friction_delta(original: Any, stela: Any) -> int | None:
    if original is None or stela is None:
        return None
    return int(bool(stela)) - int(bool(original))


def row_payload(dataset: Dict[str, Any], row: Dict[str, Any], line_no: int) -> Dict[str, Any]:
    comparison = row.get("comparison") or {}
    metadata = row.get("metadata") or {}
    original_audit = row.get("original_audit") or {}
    stela_audit = row.get("stela_audit") or {}
    original_compliance = comparison.get("original_compliance")
    stela_compliance = comparison.get("stela_compliance")
    delta = comparison.get("compliance_lift")

    return {
        "id": f"{dataset['id']}:{line_no}",
        "line_no": line_no,
        "dataset_id": dataset["id"],
        "dataset": dataset["label"],
        "source": row.get("source"),
        "conversation_id": row.get("conversation_id"),
        "turn_id": row.get("turn_id"),
        "domain": row.get("domain"),
        "service": row.get("service"),
        "intent": metadata.get("intent") or metadata.get("active_intent") or "",
        "category": metadata.get("category") or "",
        "user_message": row.get("user_message"),
        "original_assistant_response": row.get("original_assistant_response"),
        "original_response": row.get("original_assistant_response"),
        "stela_assistant_response": row.get("stela_assistant_response"),
        "stela_response": row.get("stela_assistant_response"),
        "original_audit": original_audit,
        "stela_audit": stela_audit,
        "comparison": comparison,
        "metadata": metadata,
        "stela_state_vector_seed": row.get("stela_state_vector_seed"),
        "stela_context_packet": row.get("stela_context_packet"),
        "original_compliance": original_compliance,
        "stela_compliance": stela_compliance,
        "compliance_delta": delta,
        "original_friction": comparison.get("original_friction_detected"),
        "stela_friction": comparison.get("stela_friction_detected"),
        "friction_delta": friction_delta(
            comparison.get("original_friction_detected"),
            comparison.get("stela_friction_detected"),
        ),
        "failed_criteria_original": original_audit.get("failed_criteria") or [],
        "failed_criteria_stela": stela_audit.get("failed_criteria") or [],
        "token_delta": estimate_token_change(row),
        "outcome": outcome_from_delta(delta),
    }


def error_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"generation": 0, "original_audit": 0, "stela_audit": 0}
    for row in rows:
        errors = row.get("errors") or {}
        for key in counts:
            if errors.get(key):
                counts[key] += 1
    return counts


def combined_metrics(dataset_summaries: List[Dict[str, Any]], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    comparisons = [row.get("comparison") or {} for row in rows]

    def avg(key: str) -> float | None:
        values = [comparison[key] for comparison in comparisons if comparison.get(key) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 3)

    improved = sum(1 for c in comparisons if (c.get("compliance_lift") or 0) > 0)
    worsened = sum(1 for c in comparisons if (c.get("compliance_lift") or 0) < 0)
    unchanged = len(comparisons) - improved - worsened
    errors = error_counts(rows)
    token_change = avg("stela_estimated_output_tokens")
    original_tokens = avg("original_estimated_output_tokens")

    return {
        "status": "PASS",
        "rows": len(rows),
        "original_average_compliance": avg("original_compliance"),
        "stela_average_compliance": avg("stela_compliance"),
        "average_compliance_lift": avg("compliance_lift"),
        "average_friction_change": avg("friction_change"),
        "improved": improved,
        "unchanged": unchanged,
        "worsened": worsened,
        "worsened_rate": round(worsened / len(rows), 3) if rows else None,
        "generation_errors": errors["generation"],
        "original_audit_errors": errors["original_audit"],
        "stela_audit_errors": errors["stela_audit"],
        "average_token_change": (
            round(token_change - original_tokens, 3)
            if token_change is not None and original_tokens is not None
            else None
        ),
        "datasets": dataset_summaries,
    }


def load_v04_data() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    dataset_summaries: List[Dict[str, Any]] = []

    for dataset in DATASETS:
        summary = load_json(dataset["summary"])
        dataset_rows = [
            row_payload(dataset, row, line_no)
            for line_no, row in enumerate(iter_jsonl(dataset["eval"]), 1)
        ]
        rows.extend(dataset_rows)
        dataset_summaries.append(
            {
                "id": dataset["id"],
                "label": dataset["label"],
                "rows": summary.get("records_evaluated"),
                "original_average_compliance": summary.get("original_average_compliance"),
                "stela_average_compliance": summary.get("stela_average_compliance"),
                "average_compliance_lift": summary.get("average_compliance_lift"),
                "average_friction_change": summary.get("average_friction_change"),
                "improved": summary.get("compliance_improved_rows"),
                "unchanged": summary.get("compliance_unchanged_rows"),
                "worsened": summary.get("compliance_worsened_rows"),
                "average_token_change": -summary.get("average_estimated_output_token_savings", 0),
                "errors": error_counts(dataset_rows),
            }
        )

    worsened_rows = [
        row for row in rows if (row.get("compliance_delta") or 0) < 0
    ]

    return {
        "source_note": "Public structured banking and lending datasets, not production bank chatbot logs.",
        "run": {
            "name": "STELA Holdout Evaluation v0.4",
            "primary_result": True,
            "status": "PASS",
            "strong_status": "Not strong pass",
            "status_reason": "PASS, not STRONG PASS, because worsened-row rate was 3.6%, above the under-2% strong threshold.",
        },
        "combined": combined_metrics(dataset_summaries, rows),
        "rows": rows,
        "worsened_rows": worsened_rows,
        "history": [
            {
                "version": "v0.2",
                "title": "Development validation",
                "role": "development/history",
                "summary": "Frozen 750-row validation package. Useful for development context, not the headline holdout result.",
            },
            {
                "version": "v0.3",
                "title": "SGD context-packet experiment",
                "role": "development/history",
                "summary": "Validated the structured context packet idea on stateful SGD rows; not the primary evidence package.",
            },
            {
                "version": "v0.4",
                "title": "Final unseen holdout validation",
                "role": "primary validation result",
                "summary": "Frozen 500-row unseen Bitext banking and lending holdout. PASS.",
            },
        ],
    }


def average(values: List[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def row_tokens(row: Dict[str, Any]) -> Dict[str, Any]:
    comparison = row.get("comparison") or {}
    return {
        "original": comparison.get("original_estimated_output_tokens"),
        "stela": comparison.get("stela_estimated_output_tokens"),
        "delta": row.get("token_delta"),
    }


def build_analytics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    outcomes = {
        "improved": sum(1 for row in rows if row.get("outcome") == "improved"),
        "unchanged": sum(1 for row in rows if row.get("outcome") == "unchanged"),
        "worsened": sum(1 for row in rows if row.get("outcome") == "worsened"),
    }
    outcome_distribution = [
        {"outcome": key, "count": count, "percentage": round(count / total, 3) if total else 0}
        for key, count in outcomes.items()
    ]

    bins = [
        ("<= -1.0", None, -1.0, True, True),
        ("-0.75 to -0.5", -0.75, -0.5, True, True),
        ("-0.5 to -0.25", -0.5, -0.25, False, True),
        ("-0.25 to 0", -0.25, 0.0, False, False),
        ("0", 0.0, 0.0, True, True),
        ("0 to +0.25", 0.0, 0.25, False, True),
        ("+0.25 to +0.5", 0.25, 0.5, False, True),
        ("+0.5 to +0.75", 0.5, 0.75, False, True),
        ("+0.75 to +1.0", 0.75, 1.0, False, True),
    ]
    delta_bins = []
    for label, low, high, include_low, include_high in bins:
        count = 0
        for row in rows:
            delta = row.get("compliance_delta")
            if delta is None:
                continue
            if low is None:
                match = delta <= high
            elif low == high:
                match = delta == low
            else:
                low_ok = delta >= low if include_low else delta > low
                high_ok = delta <= high if include_high else delta < high
                match = low_ok and high_ok
            if match:
                count += 1
        delta_bins.append({"label": label, "count": count, "percentage": round(count / total, 3) if total else 0})

    friction_movement = {
        "reduced": sum(1 for row in rows if (row.get("friction_delta") or 0) < 0),
        "unchanged": sum(1 for row in rows if (row.get("friction_delta") or 0) == 0),
        "increased": sum(1 for row in rows if (row.get("friction_delta") or 0) > 0),
    }

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        label = row.get("intent") or row.get("category") or "Unlabeled"
        groups.setdefault(label, []).append(row)
    intent_performance = []
    for label, group in groups.items():
        intent_performance.append(
            {
                "label": label,
                "row_count": len(group),
                "average_original_compliance": average([r["original_compliance"] for r in group if r.get("original_compliance") is not None]),
                "average_stela_compliance": average([r["stela_compliance"] for r in group if r.get("stela_compliance") is not None]),
                "average_lift": average([r["compliance_delta"] for r in group if r.get("compliance_delta") is not None]),
                "worsened_count": sum(1 for r in group if r.get("outcome") == "worsened"),
                "worsened_rate": round(sum(1 for r in group if r.get("outcome") == "worsened") / len(group), 3),
                "average_token_change": average([r["token_delta"] for r in group if r.get("token_delta") is not None]),
            }
        )
    intent_performance.sort(key=lambda item: item["row_count"], reverse=True)

    token_changes = [row["token_delta"] for row in rows if row.get("token_delta") is not None]
    token_by_dataset = []
    for dataset in DATASETS:
        group = [row for row in rows if row.get("dataset_id") == dataset["id"]]
        token_by_dataset.append(
            {
                "dataset_id": dataset["id"],
                "dataset": dataset["label"],
                "average_token_change": average([row["token_delta"] for row in group if row.get("token_delta") is not None]),
            }
        )
    token_by_outcome = []
    for outcome in ["improved", "unchanged", "worsened"]:
        group = [row for row in rows if row.get("outcome") == outcome]
        token_by_outcome.append(
            {
                "outcome": outcome,
                "average_token_change": average([row["token_delta"] for row in group if row.get("token_delta") is not None]),
            }
        )

    criteria: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        for criterion in row.get("failed_criteria_original") or []:
            criteria.setdefault(criterion, {"failed_criterion": criterion, "original_count": 0, "stela_count": 0, "worsened_row_count": 0, "example_conversation_id": row.get("conversation_id")})
            criteria[criterion]["original_count"] += 1
        for criterion in row.get("failed_criteria_stela") or []:
            criteria.setdefault(criterion, {"failed_criterion": criterion, "original_count": 0, "stela_count": 0, "worsened_row_count": 0, "example_conversation_id": row.get("conversation_id")})
            criteria[criterion]["stela_count"] += 1
            if row.get("outcome") == "worsened":
                criteria[criterion]["worsened_row_count"] += 1

    failure_criteria = sorted(
        criteria.values(),
        key=lambda item: (item["worsened_row_count"], item["stela_count"], item["original_count"]),
        reverse=True,
    )

    return {
        "outcome_distribution": outcome_distribution,
        "compliance_lift_distribution": delta_bins,
        "friction_movement": friction_movement,
        "intent_category_performance": intent_performance,
        "token_efficiency": {
            "average_token_change": average(token_changes),
            "stela_shorter_count": sum(1 for value in token_changes if value < 0),
            "stela_longer_count": sum(1 for value in token_changes if value > 0),
            "stela_same_count": sum(1 for value in token_changes if value == 0),
            "by_dataset": token_by_dataset,
            "by_outcome": token_by_outcome,
        },
        "failure_criteria": failure_criteria,
    }


class StateVector(BaseModel):
    compliance_risk: float = Field(0.2, ge=0, le=1)
    customer_distress: float = Field(0.05, ge=0, le=1)
    fraud_risk: float = Field(0.1, ge=0, le=1)
    account_sensitivity: float = Field(0.25, ge=0, le=1)


class SimulationToggles(BaseModel):
    authenticated_session: bool = True
    account_info_available: bool = False
    transfer_action: bool = False
    customer_distressed: bool = False
    high_regulatory_sensitivity: bool = False
    minimize_friction: bool = True
    require_human_escalation: bool = False


class SimulationRequest(BaseModel):
    row_id: str | None = None
    user_message: str | None = None
    original_response: str | None = None
    dataset: str | None = None
    domain: str | None = None
    intent: str | None = None
    category: str | None = None
    notes: str | None = None
    state_vector: StateVector = Field(default_factory=StateVector)
    toggles: SimulationToggles = Field(default_factory=SimulationToggles)
    behavioral_objective: Literal[
        "maximize_compliance",
        "minimize_friction",
        "balanced",
        "shortest_acceptable_response",
        "escalation_first",
        "customer_retention_sensitive",
    ] = "balanced"


def selected_row(row_id: str | None) -> Dict[str, Any] | None:
    if not row_id:
        return None
    for row in load_v04_data()["rows"]:
        if row.get("id") == row_id:
            return row
    raise HTTPException(status_code=404, detail=f"Unknown STELA row id: {row_id}")


def detect_planning_frame(text: str, intent: str, category: str, toggles: SimulationToggles) -> str:
    lowered = f"{text} {intent} {category}".lower()
    if toggles.require_human_escalation:
        return "escalation_required"
    if any(word in lowered for word in ["bye", "that's all", "no thanks"]):
        return "conversation_closing"
    if "activate" in lowered and "card" in lowered:
        return "card_activation"
    if any(word in lowered for word in ["balance", "checking", "savings"]):
        return "balance_inquiry"
    if toggles.transfer_action or any(word in lowered for word in ["transfer", "payment", "send money"]):
        return "transfer_continuation"
    if toggles.customer_distressed or any(word in lowered for word in ["angry", "upset", "frustrated", "complaint"]):
        return "complaint_or_distress"
    if text.strip():
        return "routine_service"
    return "unknown"


def risk_label(score: float) -> str:
    if score >= 0.67:
        return "high"
    if score >= 0.34:
        return "medium"
    return "low"


def simulation_response_sketch(frame: str, request: SimulationRequest, row: Dict[str, Any] | None) -> str:
    text = request.user_message or (row or {}).get("user_message") or ""
    lowered = text.lower()
    context_packet = ((row or {}).get("stela_context_packet") or {}) if row else {}
    known_slots = context_packet.get("known_slots") or {}
    service_results = context_packet.get("service_results") or {}
    account_type = known_slots.get("account_type") or ("checking" if "checking" in lowered else "savings" if "savings" in lowered else None)
    balance = service_results.get("balance")

    if frame == "balance_inquiry":
        if not request.toggles.authenticated_session:
            return "I'll need to verify your identity before providing balance information."
        if not account_type:
            return "Which account would you like to check, checking or savings?"
        if request.toggles.account_info_available and balance:
            return f"Your {account_type} account balance is {balance}."
        if request.toggles.account_info_available:
            return f"I'll check your {account_type} account balance."
        return f"I'll check your {account_type} account balance."
    if frame == "transfer_continuation":
        if "amount" not in known_slots:
            return "How much would you like to transfer?"
        if "recipient" not in known_slots:
            return "Who should receive the transfer?"
        return "Please confirm the transfer details before I submit it."
    if frame == "complaint_or_distress":
        return "I'm sorry this has been frustrating. I can help with that. Let's take the next step."
    if frame == "conversation_closing":
        return "Have a nice day."
    if frame == "escalation_required":
        return "This needs help from a specialist. I can connect you with the right team."
    if frame == "card_activation":
        return "To activate your card, use the activation instructions provided with the card or the card issuer's secure activation channel."
    return "I can help with that."


def run_simulation(request: SimulationRequest) -> Dict[str, Any]:
    row = selected_row(request.row_id)
    user_message = request.user_message or (row or {}).get("user_message") or ""
    intent = request.intent or (row or {}).get("intent") or ""
    category = request.category or (row or {}).get("category") or ""
    frame = detect_planning_frame(user_message, intent, category, request.toggles)
    risk_score = max(
        request.state_vector.compliance_risk,
        request.state_vector.fraud_risk,
        request.state_vector.account_sensitivity,
        0.7 if request.toggles.high_regulatory_sensitivity else 0,
        0.8 if request.toggles.require_human_escalation else 0,
    )
    risk_posture = risk_label(risk_score)
    compliance_risk = risk_label(max(request.state_vector.compliance_risk, 0.7 if request.toggles.high_regulatory_sensitivity else 0))
    friction = "high" if request.toggles.require_human_escalation else "low" if request.toggles.minimize_friction else "medium"
    style = "escalation" if frame == "escalation_required" else "security-first" if not request.toggles.authenticated_session else "empathetic" if request.toggles.customer_distressed else "concise"

    imperatives = ["answer directly when safe", "ask only for missing required fields", "do not add unnecessary friction"]
    if request.toggles.account_info_available:
        imperatives.append("preserve transaction status exactly")
    if not request.toggles.authenticated_session:
        imperatives.append("do not disclose sensitive information without verified context")
    if request.toggles.customer_distressed:
        imperatives.append("acknowledge distress briefly")
    if request.toggles.require_human_escalation:
        imperatives.append("escalate when required")

    return {
        "risk_posture": risk_posture,
        "planning_frame": frame,
        "behavioral_imperatives": imperatives,
        "response_style": style,
        "expected_friction": friction,
        "expected_compliance_risk": compliance_risk,
        "response_sketch": simulation_response_sketch(frame, request, row),
        "delta_summary": {
            "compliance_risk": "increased" if compliance_risk == "high" else "unchanged",
            "friction": "decreased" if request.toggles.minimize_friction and not request.toggles.require_human_escalation else "increased" if request.toggles.require_human_escalation else "unchanged",
            "escalation_likelihood": "increased" if request.toggles.require_human_escalation else "unchanged",
            "customer_experience": "improved" if request.toggles.minimize_friction and frame != "escalation_required" else "unchanged",
            "reason": "The simulated state changes which safeguards and task-completion steps are appropriate.",
        },
        "note": "Rule-based simulation preview. Not a scored model rerun.",
        "selected_row": row,
    }


@router.get("/stela/v04")
def stela_v04() -> Dict[str, Any]:
    return load_v04_data()


@router.get("/stela/v04/summary")
def stela_v04_summary() -> Dict[str, Any]:
    data = load_v04_data()
    return {
        "source_note": data["source_note"],
        "run": data["run"],
        "combined": data["combined"],
        "history": data["history"],
    }


@router.get("/stela/v04/rows")
def stela_v04_rows() -> List[Dict[str, Any]]:
    return load_v04_data()["rows"]


@router.get("/stela/v04/rows/{row_id}")
def stela_v04_row(row_id: str) -> Dict[str, Any]:
    row = selected_row(row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown STELA row id: {row_id}")
    return row


@router.get("/stela/v04/analytics")
def stela_v04_analytics() -> Dict[str, Any]:
    return build_analytics(load_v04_data()["rows"])


@router.get("/stela/v04/worsened")
def stela_v04_worsened() -> List[Dict[str, Any]]:
    return load_v04_data()["worsened_rows"]


@router.post("/stela/v04/simulate")
def stela_v04_simulate(request: SimulationRequest) -> Dict[str, Any]:
    return run_simulation(request)

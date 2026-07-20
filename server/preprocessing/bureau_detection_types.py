from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class BureauMetadataInput(BaseModel):
    variableName: str
    bureauSource: Optional[str] = None
    attributeDescription: Optional[str] = None
    specialValueDefinitions: Optional[str] = None
    variableFamily: Optional[str] = None
    regulatorySensitivity: Optional[str] = None


class BureauDetectionRequest(BaseModel):
    target: Optional[str] = None
    event_value: Optional[Any] = None
    manual_declaration: Literal["auto", "contains", "does_not_contain", "manual_review"] = "auto"
    metadata: List[BureauMetadataInput] = Field(default_factory=list)
    treatment_selections: List[Dict[str, Any]] = Field(default_factory=list)
    reviewer_rationale: str = ""


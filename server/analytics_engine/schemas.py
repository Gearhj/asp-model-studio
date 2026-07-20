from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class AnalyticalRunRequest(BaseModel):
    project_id: str | None = None
    workflow_type: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)


class AnalyticalRunResponse(BaseModel):
    analysis_id: str
    analysis_type: str
    status: str
    statistics: dict[str, Any] = Field(default_factory=dict)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)

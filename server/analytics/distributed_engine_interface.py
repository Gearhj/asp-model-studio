"""Enterprise Analytical Data Plane -- future distributed/warehouse engine interface.

STATUS: extension-ready, NOT implemented. No connector below is functional --
each raises NotImplementedError so a misconfigured deployment fails loudly
rather than silently behaving like a no-op or falling back to something that
looks like it worked. Do not present any of these as available capability in
API responses; the query planner never selects `ExecutionEngine` values for
these because no such values exist in query_contract.py's enum today.

Design intent for Phase 2: a real connector implements this Protocol, is
registered in a small registry keyed by connection type, and the query
planner gains a new planner input ("configured external connections") that
lets it choose source-database pushdown when a supported, authorized
connection exists for the dataset's origin. That registration and planner
wiring is deliberately not built here -- see
docs/architecture/EXECUTION_ENGINE_GUIDE.md's "Distributed engine extension
points" section for the capability-negotiation shape this Protocol is meant
to support.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol


@dataclass
class EngineCapabilities:
    """What a distributed engine connector claims to support -- the planner would
    use this to decide whether pushdown is safe for a given operation, the same
    way it already uses row/column counts for the in-process engines."""

    supports_predicate_pushdown: bool
    supports_column_pushdown: bool
    supports_approx_quantile: bool
    supports_group_by_pushdown: bool
    max_result_rows: int
    typical_latency_ms: int


class DistributedEngineConnector(Protocol):
    """A future connector (Spark, Databricks, Snowflake, BigQuery, Redshift,
    SQL Server, Oracle, Teradata) implements this. None of the methods below
    are implemented by anything in this repository today."""

    engine_name: str

    def capabilities(self) -> EngineCapabilities: ...

    def authorize_connection(self, user: Dict[str, Any], project_id: str) -> bool: ...

    def execute_bounded_aggregate(self, table_ref: str, operation: str, params: Dict[str, Any]) -> Dict[str, Any]: ...

    def close(self) -> None: ...


class UnimplementedConnector:
    """Base class for connector stubs -- every method raises, by design. This
    exists so future connector modules have a consistent failure mode instead
    of each independently deciding how to fail."""

    engine_name = "unimplemented"

    def capabilities(self) -> EngineCapabilities:
        raise NotImplementedError(f"{self.engine_name} connector is not implemented in this deployment.")

    def authorize_connection(self, user: Dict[str, Any], project_id: str) -> bool:
        raise NotImplementedError(f"{self.engine_name} connector is not implemented in this deployment.")

    def execute_bounded_aggregate(self, table_ref: str, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(f"{self.engine_name} connector is not implemented in this deployment.")

    def close(self) -> None:
        return None


# A named registry future connectors would populate -- intentionally empty today.
CONNECTOR_REGISTRY: Dict[str, "UnimplementedConnector"] = {}


def list_configured_engines() -> List[str]:
    """Returns which distributed engines are actually configured and usable --
    always empty in this phase. The planner calls this (not a hardcoded list)
    so it never has to be told twice when Phase 2 adds a real connector."""
    return [name for name, connector in CONNECTOR_REGISTRY.items() if connector is not None]

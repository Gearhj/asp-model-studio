"""Enterprise Analytical Data Plane -- resource governance.

All limits are configurable via environment variables so operators can tune
them per deployment without a code change, per the brief's explicit
requirement ("Create configurable defaults with environment-variable
overrides"). Defaults are conservative for a single-process dev/staging
deployment; see docs/architecture/RESOURCE_GOVERNANCE_GUIDE.md for tuning
guidance at larger scale.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class ResourceLimits:
    max_result_rows: int = _int_env("ATLAS_ANALYTICS_MAX_RESULT_ROWS", 5_000)
    max_result_bytes: int = _int_env("ATLAS_ANALYTICS_MAX_RESULT_BYTES", 5_000_000)
    max_selected_columns: int = _int_env("ATLAS_ANALYTICS_MAX_SELECTED_COLUMNS", 50)
    max_histogram_bins: int = _int_env("ATLAS_ANALYTICS_MAX_HISTOGRAM_BINS", 200)
    max_group_cardinality: int = _int_env("ATLAS_ANALYTICS_MAX_GROUP_CARDINALITY", 500)
    max_scatter_points: int = _int_env("ATLAS_ANALYTICS_MAX_SCATTER_POINTS", 5_000)
    max_concurrent_queries_per_user: int = _int_env("ATLAS_ANALYTICS_MAX_CONCURRENT_PER_USER", 4)
    max_concurrent_queries_per_project: int = _int_env("ATLAS_ANALYTICS_MAX_CONCURRENT_PER_PROJECT", 8)
    max_query_duration_seconds: int = _int_env("ATLAS_ANALYTICS_MAX_QUERY_DURATION_SECONDS", 60)
    duckdb_memory_limit_mb: int = _int_env("ATLAS_ANALYTICS_DUCKDB_MEMORY_LIMIT_MB", 1024)
    duckdb_thread_limit: int = _int_env("ATLAS_ANALYTICS_DUCKDB_THREADS", 2)
    polars_streaming_chunk_rows: int = _int_env("ATLAS_ANALYTICS_POLARS_CHUNK_ROWS", 200_000)
    queue_length_limit: int = _int_env("ATLAS_ANALYTICS_QUEUE_LIMIT", 100)
    pandas_fallback_max_rows: int = _int_env("ATLAS_ANALYTICS_PANDAS_FALLBACK_MAX_ROWS", 50_000)


LIMITS = ResourceLimits()


class ResourceRejection(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class _ConcurrencyTracker:
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _by_user: Dict[str, int] = field(default_factory=dict)
    _by_project: Dict[str, int] = field(default_factory=dict)

    def try_acquire(self, user_id: str, project_id: str) -> None:
        with self._lock:
            user_count = self._by_user.get(user_id, 0)
            project_count = self._by_project.get(project_id, 0)
            if user_count >= LIMITS.max_concurrent_queries_per_user:
                raise ResourceRejection(f"Too many concurrent analytical queries for this user (limit {LIMITS.max_concurrent_queries_per_user}).")
            if project_count >= LIMITS.max_concurrent_queries_per_project:
                raise ResourceRejection(f"Too many concurrent analytical queries for this project (limit {LIMITS.max_concurrent_queries_per_project}).")
            self._by_user[user_id] = user_count + 1
            self._by_project[project_id] = project_count + 1

    def release(self, user_id: str, project_id: str) -> None:
        with self._lock:
            if user_id in self._by_user:
                self._by_user[user_id] = max(0, self._by_user[user_id] - 1)
                if self._by_user[user_id] == 0:
                    del self._by_user[user_id]
            if project_id in self._by_project:
                self._by_project[project_id] = max(0, self._by_project[project_id] - 1)
                if self._by_project[project_id] == 0:
                    del self._by_project[project_id]

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            return {"byUser": dict(self._by_user), "byProject": dict(self._by_project)}


CONCURRENCY = _ConcurrencyTracker()


class Deadline:
    """Wall-clock deadline helper -- checked between chunks/stages of a long-running
    query so a timeout releases resources promptly rather than only being enforced
    by an external watchdog thread."""

    def __init__(self, timeout_seconds: int):
        self.timeout_seconds = min(timeout_seconds, LIMITS.max_query_duration_seconds)
        self._deadline = time.monotonic() + self.timeout_seconds

    def expired(self) -> bool:
        return time.monotonic() >= self._deadline

    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

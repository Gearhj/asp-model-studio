"""Enterprise Analytical Data Plane -- bounded in-process result cache.

An in-memory, per-process dict-based cache -- consistent with the rest of this
repository (DATASTORE/RESULTS/TRAINING_JOBS are all in-process dicts; no Redis
or other external cache service is configured anywhere in ATLAS today, and
Phase K explicitly says not to introduce one). Not shared across worker
processes -- acceptable for this phase's single-process dev/staging deployment;
documented as a Phase 2 concern for a multi-process deployment.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

_MAX_ENTRIES = 500
_MAX_ENTRY_BYTES = 2_000_000
_DEFAULT_TTL_SECONDS = 300


@dataclass
class CacheEntry:
    value: Dict[str, Any]
    expires_at: float
    size_bytes: int
    owner_user_id: str
    project_id: str


class _ResultCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[str, CacheEntry] = {}

    def build_key(
        self, *, user_scope: str, project_id: str, dataset_id: Optional[str], version_id: Optional[str],
        partition: Optional[str], model_id: Optional[str], scoring_run_id: Optional[str], operation: str,
        selected_columns: list, filters: list, aggregations: dict, binning: Optional[int],
        sampling_method: Optional[str], exact: bool, engine_version: str,
    ) -> str:
        """Cache key includes every dimension the brief lists -- normalized (sorted)
        so equivalent-but-differently-ordered requests still hit the same entry."""
        payload = {
            "userScope": user_scope, "projectId": project_id, "datasetId": dataset_id, "versionId": version_id,
            "partition": partition, "modelId": model_id, "scoringRunId": scoring_run_id, "operation": operation,
            "selectedColumns": sorted(selected_columns), "filters": sorted((str(f) for f in filters)),
            "aggregations": dict(sorted(aggregations.items())), "binning": binning,
            "samplingMethod": sampling_method, "exact": exact, "engineVersion": engine_version,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        return digest

    def get(self, key: str, *, user_scope: str, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at < time.monotonic():
                del self._entries[key]
                return None
            # Defense in depth: even though the key itself is scoped by user/project,
            # verify the stored entry's scope matches before returning it.
            if entry.owner_user_id != user_scope or entry.project_id != project_id:
                return None
            return entry.value

    def set(self, key: str, value: Dict[str, Any], *, user_scope: str, project_id: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS, cacheable: bool = True) -> None:
        if not cacheable:
            return
        size_estimate = len(json.dumps(value, default=str))
        if size_estimate > _MAX_ENTRY_BYTES:
            return  # too large to cache -- caller still gets the result, just not cached
        with self._lock:
            if len(self._entries) >= _MAX_ENTRIES:
                oldest_key = min(self._entries, key=lambda k: self._entries[k].expires_at)
                del self._entries[oldest_key]
            self._entries[key] = CacheEntry(value=value, expires_at=time.monotonic() + ttl_seconds, size_bytes=size_estimate, owner_user_id=user_scope, project_id=project_id)

    def invalidate_project(self, project_id: str) -> int:
        with self._lock:
            stale = [k for k, e in self._entries.items() if e.project_id == project_id]
            for k in stale:
                del self._entries[k]
            return len(stale)

    def invalidate_dataset(self, dataset_id: str) -> int:
        """Called on dataset archival -- drops any entry whose key payload referenced
        this dataset. Since keys are hashed, this requires the caller to also track
        dataset->key membership; for this phase's scope we instead just clear
        everything for simplicity and correctness over cache-hit-rate optimization."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {"entries": len(self._entries), "maxEntries": _MAX_ENTRIES}


RESULT_CACHE = _ResultCache()

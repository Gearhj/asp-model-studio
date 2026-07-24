# server/core/result_store.py

from typing import Dict, Any, Optional, Tuple
from datetime import datetime

class ResultStore:
    """
    Stores training results and model availability in memory.
    """

    def __init__(self):
        self.last_training_summary: Optional[Dict[str, Any]] = None
        self.training_timestamp: Optional[str] = None
        self.model_availability: Dict[str, bool] = {}
        self.model_artifacts: Dict[str, Any] = {}
        self.model_artifact_metadata: Dict[str, Dict[str, Any]] = {}
        self.final_model: Optional[Any] = None
        self.final_model_metadata: Optional[Dict[str, Any]] = None
        self.scoring_reference: Optional[Dict[str, Any]] = None

    def set_last_summary(self, summary: Dict[str, Any]):
        self.last_training_summary = summary
        self.training_timestamp = datetime.now().isoformat()

    def get_last_summary(self) -> Optional[Dict[str, Any]]:
        return self.last_training_summary

    def set_model_availability(self, availability: Dict[str, bool]):
        self.model_availability = availability

    def get_model_availability(self) -> Dict[str, bool]:
        return self.model_availability

    def set_model_artifacts(self, artifacts: Dict[str, Any], metadata: Optional[Dict[str, Dict[str, Any]]] = None):
        self.model_artifacts = artifacts
        self.model_artifact_metadata = metadata or {}

    def get_model_artifact(self, key: str) -> Optional[Any]:
        return self.model_artifacts.get(key)

    def get_model_artifact_metadata(self, key: str) -> Dict[str, Any]:
        return self.model_artifact_metadata.get(key, {})

    def get_model_artifacts(self) -> Dict[str, Any]:
        return self.model_artifacts

    def clear_model_artifacts(self):
        self.last_training_summary = None
        self.training_timestamp = None
        self.model_artifacts = {}
        self.model_artifact_metadata = {}
        self.final_model = None
        self.final_model_metadata = None
        self.scoring_reference = None

    def set_final_model(self, model: Any, metadata: Dict[str, Any]):
        self.final_model = model
        self.final_model_metadata = metadata

    def get_final_model(self) -> Optional[Any]:
        return self.final_model

    def get_final_model_metadata(self) -> Optional[Dict[str, Any]]:
        return self.final_model_metadata

    def set_scoring_reference(self, reference: Dict[str, Any]):
        self.scoring_reference = reference

    def get_scoring_reference(self) -> Optional[Dict[str, Any]]:
        return self.scoring_reference


# Stage 3 (ATLAS_MODELING_STATE_ISOLATION_PLAN.md): RESULTS is keyed the
# same way DATASTORE was re-keyed in Stage 2B -- an explicit (user_id,
# project_id) tuple, never a concatenated string (no delimiter-collision
# risk). See server/core/dataset_store.py's matching comment and
# server/core/modeling_scope.py for the ContextVar/authorization mechanism
# both stores now share. No migration of old str-keyed entries is needed:
# a fresh process always starts with an empty dict, and old str keys could
# never collide with the new tuple keys even if they somehow coexisted.
_RESULT_STORES: Dict[Tuple[str, str], ResultStore] = {}

# Sentinel project component for scopes never routed through
# authorize_modeling_scope (direct service/script callers, e.g.
# tests/predictive_modeling_repair_test.py, and the still-unmodified
# checkpoint-restore-at-startup path). A real HTTP request to an affected
# endpoint can never reach RESULTS with this fallback -- authorize_modeling_
# scope rejects it (400/403/404) first. Re-exported from dataset_store so
# both stores use one literal sentinel, not two independently-typed ones.
from .dataset_store import UNSCOPED_PROJECT  # noqa: E402


def _scope_key() -> Tuple[str, str]:
    try:
        from ..security.security_store import active_user

        user = active_user() or {}
        user_id = str(user.get("userId") or "anonymous")
    except Exception:
        user_id = "anonymous"
    try:
        from .modeling_scope import active_project_id

        project_id = active_project_id() or UNSCOPED_PROJECT
    except Exception:
        project_id = UNSCOPED_PROJECT
    return (user_id, project_id)


def get_scoped_result_store(scope: Optional[Tuple[str, str]] = None) -> ResultStore:
    """Look up (creating if needed) the ResultStore for `scope`, or for the
    ambient (user, project) scope if `scope` is omitted. Explicit `scope`
    is used by tests that need to inspect a specific (user_id, project_id)
    pair directly, bypassing ContextVar resolution -- mirrors
    get_scoped_dataset_store's contract exactly.
    """
    key = scope or _scope_key()
    if key not in _RESULT_STORES:
        _RESULT_STORES[key] = ResultStore()
    return _RESULT_STORES[key]


def discard_scoped_result_store(scope: Tuple[str, str]) -> bool:
    """Drop one (user_id, project_id) scope from the in-memory registry.
    Mirrors dataset_store.discard_scoped_dataset_store -- see its docstring
    for the Stage 6.1 lifecycle rationale. Callers should go through
    session_checkpoint.discard_modeling_scopes().
    """
    return _RESULT_STORES.pop(scope, None) is not None


class ResultStoreProxy:
    def current(self) -> ResultStore:
        return get_scoped_result_store()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.current(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_ignored":
            super().__setattr__(name, value)
            return
        setattr(self.current(), name, value)


RESULTS = ResultStoreProxy()

# server/core/result_store.py

from typing import Dict, Any, Optional
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


RESULTS = ResultStore()

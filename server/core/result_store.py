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

    def set_last_summary(self, summary: Dict[str, Any]):
        self.last_training_summary = summary
        self.training_timestamp = datetime.now().isoformat()

    def get_last_summary(self) -> Optional[Dict[str, Any]]:
        return self.last_training_summary

    def set_model_availability(self, availability: Dict[str, bool]):
        self.model_availability = availability

    def get_model_availability(self) -> Dict[str, bool]:
        return self.model_availability

    def set_model_artifacts(self, artifacts: Dict[str, Any]):
        self.model_artifacts = artifacts

    def get_model_artifact(self, key: str) -> Optional[Any]:
        return self.model_artifacts.get(key)

    def get_model_artifacts(self) -> Dict[str, Any]:
        return self.model_artifacts


RESULTS = ResultStore()

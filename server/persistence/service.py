from __future__ import annotations

from typing import Any, Dict

from .db import Database, get_database, now_iso
from .repositories import (
    AccessRepository,
    AuditRepository,
    CollaborationRepository,
    DatasetRepository,
    DecisionJournalRepository,
    DemoFeedbackRepository,
    DocumentationRepository,
    EvidenceRepository,
    ExportRepository,
    ModelRepository,
    ModelVersionRepository,
    ProjectRepository,
    RunRepository,
    ScoringRunRepository,
    SharingRepository,
    NotificationRepository,
    MonitoringRepository,
    UserRepository,
    ValidationRepository,
    AnalyticsRepository,
)


class PersistenceService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.projects = ProjectRepository(database)
        self.datasets = DatasetRepository(database)
        self.evidence = EvidenceRepository(database)
        self.runs = RunRepository(database)
        self.scoring_runs = ScoringRunRepository(database)
        self.models = ModelRepository(database)
        self.model_versions = ModelVersionRepository(database)
        self.decisions = DecisionJournalRepository(database)
        self.documentation = DocumentationRepository(database)
        self.exports = ExportRepository(database)
        self.users = UserRepository(database)
        self.audit = AuditRepository(database)
        self.access = AccessRepository(database)
        self.sharing = SharingRepository(database)
        self.notifications = NotificationRepository(database)
        self.monitoring = MonitoringRepository(database)
        self.collaboration = CollaborationRepository(database)
        self.feedback = DemoFeedbackRepository(database)
        self.validation = ValidationRepository(database)
        self.analytics = AnalyticsRepository(database)

    def sync_user(self, user: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if not user or not user.get("userId"):
            return None
        return self.users.upsert(
            {
                "user_id": user["userId"],
                "display_name": user.get("displayName") or user.get("email") or "ATLAS User",
                "email": user.get("email"),
                "role": user.get("role") or "data_scientist",
                "status": user.get("status") or "active",
                "created_at": user.get("createdAt"),
                "updated_at": user.get("updatedAt"),
                "last_active_at": user.get("lastActiveAt") or now_iso(),
                "metadata_json": {"source": "atlas_security_store"},
            }
        )

    def ensure_project(self, project_id: str, user: Dict[str, Any] | None = None) -> Dict[str, Any]:
        self.sync_user(user)
        return self.projects.ensure(project_id, {"owner_user_id": (user or {}).get("userId")})


_service: PersistenceService | None = None


def get_persistence_service() -> PersistenceService:
    global _service
    database = get_database()
    if _service is None or _service.database.path != database.path:
        _service = PersistenceService(database)
    return _service

"""Pure contract foundation for future ATLAS audit assurance."""

from .adapters import (
    ExistingArtifactKind,
    ExistingEvidenceContext,
    adapt_existing_evidence,
)
from .canonical import (
    CanonicalSerializationError,
    canonical_json_bytes,
    canonical_sha256,
)
from .contracts import (
    AUDIT_ASSURANCE_CONTRACT_VERSION,
    AuditActor,
    AuditActorRole,
    AuditConclusionRole,
    AuditDecisionKind,
    AuditEvent,
    AuditPackageManifest,
    AuditSubjectIdentity,
    AuditWorkflowStage,
    ControlAssessment,
    EvidenceReference,
    ResourceIdentity,
    WorkflowStage,
    server_timestamp,
)

__all__ = [
    "AUDIT_ASSURANCE_CONTRACT_VERSION",
    "AuditActor",
    "AuditActorRole",
    "AuditConclusionRole",
    "AuditDecisionKind",
    "AuditEvent",
    "AuditPackageManifest",
    "AuditSubjectIdentity",
    "AuditWorkflowStage",
    "CanonicalSerializationError",
    "ControlAssessment",
    "EvidenceReference",
    "ExistingArtifactKind",
    "ExistingEvidenceContext",
    "ResourceIdentity",
    "WorkflowStage",
    "adapt_existing_evidence",
    "canonical_json_bytes",
    "canonical_sha256",
    "server_timestamp",
]

"""Governed EDA documentation and confirmation source of truth.

This service is the boundary between the EDA workspace and Model Development
Documentation (MDD).  React never writes into the MDD document store directly.
Instead it submits one canonical, scoped EDA payload here.  Drafts are mutable;
confirmed snapshots are append-only and immutable except for lifecycle status
metadata that can mark a snapshot stale.

Security and governance invariants:

* project authorization is enforced by the router before every call;
* dataset, version, target, and predictor-manifest values are assertions
  checked against the active server-governed EDA context;
* the confirmation actor and timestamp are server-derived;
* deterministic target sources must be explicitly documented as excluded;
* an approved snapshot is never silently overwritten by later draft changes;
* retrying the same confirmation is idempotent and cannot create duplicates.
"""

from __future__ import annotations

import copy
from functools import wraps
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional
from urllib.parse import quote

from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import active_project_id
from ..datasets.dataset_identity import active_dataset_identity
from ..evidence.evidence_identity import has_complete_canonical_dataset_lineage
from ..evidence.evidence_store import get_evidence
from ..evidence.evidence_types import CANONICAL_DATASET_LINEAGE_CONTRACT
from ..security.security_store import audit_event
from .documentation_types import EDADocumentationPayload
from .workspace_service import eda_workspace_service
from .workspace_types import EDAWorkspaceRequest


EDA_DOCUMENTATION_ROOT = (
    Path(__file__).resolve().parents[1] / "artifacts" / "eda_documentation"
)
_STORE_SCHEMA_VERSION = 1
_MAX_CANONICAL_PAYLOAD_BYTES = 2_000_000
_READY_REVIEWER_STATUSES = {
    "approved",
    "reviewed",
    "ready",
    "ready_for_confirmation",
}
_UNRESOLVED_DUPLICATE_DECISIONS = {
    "",
    "none",
    "pending",
    "unresolved",
    "not reviewed",
    "not_reviewed",
    "tbd",
}
_SECTION_NAMES = (
    "overview",
    "target",
    "predictors",
    "relationships",
    "stability_and_segments",
    "findings",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _payload_digest(canonical: Dict[str, Any]) -> str:
    """Identity of the governed analytical/documentation content.

    Performance timing is persisted in each snapshot, but is deliberately not
    part of idempotency or staleness. A retry with a newly measured request
    duration must not create a second documentation version.
    """

    identity = copy.deepcopy(canonical)
    identity.pop("performance_metadata", None)
    return _digest(identity)


def _actor(user: Dict[str, Any]) -> Dict[str, str]:
    """Return the only actor metadata allowed in confirmation records."""

    user_id = str(user.get("userId") or user.get("user_id") or "").strip()
    if not user_id:
        raise EDADocumentationValidationError(
            "confirmation_actor_missing",
            ["The authenticated server session does not contain a user ID."],
        )
    display_name = str(
        user.get("displayName")
        or user.get("display_name")
        or user_id
    ).strip()
    return {"user_id": user_id, "display_name": display_name or user_id}


def _dataset_state_locked(function):
    """Serialize documentation reads/writes with dataset activation."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return function(*args, **kwargs)

    return wrapped


class EDADocumentationValidationError(ValueError):
    """Structured validation failure returned by the API boundary."""

    def __init__(self, code: str, blockers: Iterable[str]) -> None:
        self.code = str(code)
        self.blockers = [str(item) for item in blockers]
        super().__init__(" ".join(self.blockers) or self.code)


class EDADocumentationService:
    """Durable project-scoped EDA documentation lifecycle."""

    def __init__(
        self,
        root: Path | None = None,
        context_provider: Optional[Callable[[str], Dict[str, Any]]] = None,
        evidence_provider: Optional[
            Callable[[str], Optional[Dict[str, Any]]]
        ] = None,
    ) -> None:
        self.root = Path(root or EDA_DOCUMENTATION_ROOT)
        self._context_provider = context_provider or self._active_context
        self._evidence_provider = evidence_provider or get_evidence
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Durable store
    # ------------------------------------------------------------------
    def _path(self, project_id: str) -> Path:
        # The project identity is retained inside the record and checked on
        # every read. A hash avoids path traversal and information-bearing
        # filenames without weakening project-level authorization.
        slug = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        return self.root / f"{slug}.json"

    def _blank(self, project_id: str) -> Dict[str, Any]:
        return {
            "schema_version": _STORE_SCHEMA_VERSION,
            "project_id": project_id,
            "created_at": _now(),
            "updated_at": _now(),
            "draft": None,
            "current_confirmation_id": None,
            "approvals": [],
        }

    def _read(self, project_id: str) -> Dict[str, Any]:
        path = self._path(project_id)
        if not path.exists():
            return self._blank(project_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "The governed EDA documentation record could not be read."
            ) from exc
        if not isinstance(value, dict) or value.get("project_id") != project_id:
            raise RuntimeError(
                "The governed EDA documentation record failed its project-scope check."
            )
        value.setdefault("draft", None)
        value.setdefault("approvals", [])
        value.setdefault("current_confirmation_id", None)
        return value

    def _write(self, record: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record["updated_at"] = _now()
        path = self._path(str(record["project_id"]))
        tmp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            tmp_path.write_text(
                json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    # ------------------------------------------------------------------
    # Active governed context
    # ------------------------------------------------------------------
    @_dataset_state_locked
    def _active_context(self, project_id: str) -> Dict[str, Any]:
        # DATASTORE is an ambient proxy keyed by the authenticated user and
        # ACTIVE_PROJECT_ID. Routers set that project context immediately after
        # authorization; assert it again at this service boundary before any
        # dataset access so an internal/misordered caller can never validate a
        # project against another project's active frame.
        scoped_project_id = str(active_project_id() or "").strip()
        if scoped_project_id != str(project_id).strip():
            raise EDADocumentationValidationError(
                "eda_project_scope_mismatch",
                [
                    "The active server modeling scope does not match the "
                    "requested EDA documentation project."
                ],
            )
        identity = active_dataset_identity(project_id)
        dataset_id = str(identity["dataset_id"])
        dataset_version_id = str(identity["dataset_version_id"])
        df, target, _y, _problem, _event, authorization = (
            eda_workspace_service.authorized_dataset(
                EDAWorkspaceRequest(
                    project_id=project_id,
                    expected_dataset_id=dataset_id,
                    expected_dataset_version_id=dataset_version_id,
                    dataset_version=dataset_version_id,
                )
            )
        )
        manifest_id = str(authorization.get("manifest_version") or "").strip()
        if not dataset_id or not dataset_version_id or not manifest_id:
            raise EDADocumentationValidationError(
                "eda_governed_context_incomplete",
                [
                    "EDA confirmation requires a registered dataset ID, dataset "
                    "version, and server-authored predictor manifest."
                ],
            )
        return {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            # Transitional persisted alias; it is always the canonical immutable
            # Dataset Library version and is never sourced independently.
            "dataset_version": dataset_version_id,
            "target": str(target),
            "predictor_manifest_id": manifest_id,
            "authorized_predictors": sorted(
                str(value)
                for value in authorization.get("authorized_predictors", [])
            ),
            "target_source_exclusions": sorted(
                str(value)
                for value in authorization.get("target_source_excluded", [])
            ),
            "population_rows": int(len(df)),
            "duplicate_rows": int(df.duplicated().sum()),
            "data_revision": int(getattr(DATASTORE, "data_revision", 0)),
        }

    @staticmethod
    def _lineage(context: Dict[str, Any]) -> Dict[str, str]:
        dataset_version_id = str(context.get("dataset_version_id") or "")
        return {
            "project_id": str(context.get("project_id") or ""),
            "dataset_id": str(context.get("dataset_id") or ""),
            "dataset_version_id": dataset_version_id,
            # Compatibility output only; never recover canonical lineage from
            # an older alias-only record.
            "dataset_version": dataset_version_id,
            "target": str(context.get("target") or ""),
            "predictor_manifest_id": str(
                context.get("predictor_manifest_id") or ""
            ),
        }

    @staticmethod
    def _assert_expected_identity(
        context: Dict[str, Any],
        *,
        expected_dataset_id: Optional[str] = None,
        expected_dataset_version_id: Optional[str] = None,
    ) -> None:
        lineage = EDADocumentationService._lineage(context)
        if (
            (
                expected_dataset_id
                and str(expected_dataset_id) != lineage["dataset_id"]
            )
            or (
                expected_dataset_version_id
                and str(expected_dataset_version_id)
                != lineage["dataset_version_id"]
            )
        ):
            raise EDADocumentationValidationError(
                "eda_documentation_context_mismatch",
                [
                    "The requested EDA documentation state does not match "
                    "the exact active Dataset Library version."
                ],
            )

    def _assert_active_scope(
        self,
        payload: EDADocumentationPayload,
        context: Dict[str, Any],
    ) -> None:
        asserted = {
            "project_id": payload.project_id,
            "dataset_id": payload.dataset_id,
            "dataset_version_id": payload.dataset_version_id,
            "target": payload.target,
            "predictor_manifest_id": payload.predictor_manifest_id,
        }
        current = self._lineage(context)
        labels = {
            "project_id": "project",
            "dataset_id": "dataset",
            "dataset_version_id": "dataset version",
            "target": "target",
            "predictor_manifest_id": "predictor manifest",
        }
        mismatches = [
            (
                f"The submitted {labels[key]} does not match the active "
                "server-governed EDA context."
            )
            for key in asserted
            if str(asserted[key]) != str(current[key])
        ]
        if (
            payload.dataset_version
            and payload.dataset_version != current["dataset_version_id"]
        ):
            mismatches.append(
                "The submitted legacy dataset version alias does not mirror "
                "the active immutable dataset version."
            )
        if mismatches:
            raise EDADocumentationValidationError(
                "eda_documentation_context_mismatch",
                mismatches,
            )

    # ------------------------------------------------------------------
    # Canonicalization and readiness
    # ------------------------------------------------------------------
    def _canonical_evidence_references(
        self,
        references: Iterable[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        """Resolve evidence IDs against the exact governed dataset version.

        Evidence metadata supplied by the browser is display-only and cannot
        establish lineage. Each referenced item is reloaded from the governed
        evidence store, checked against the active canonical triple, and then
        projected into the documentation snapshot from server-owned values.
        """

        expected = self._lineage(context)
        expected_identity = {
            "project_id": expected["project_id"],
            "dataset_id": expected["dataset_id"],
            "dataset_version_id": expected["dataset_version_id"],
        }
        invalid_ids: list[str] = []
        canonical: list[Dict[str, Any]] = []
        seen: set[str] = set()

        for reference in references:
            evidence_id = str(reference.get("evidence_id") or "").strip()
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            stored = self._evidence_provider(evidence_id)
            stored_id = (
                str(
                    (stored or {}).get("evidenceId")
                    or (stored or {}).get("evidence_id")
                    or ""
                ).strip()
                if isinstance(stored, dict)
                else ""
            )
            identity_matches = bool(
                isinstance(stored, dict)
                and stored_id == evidence_id
                and has_complete_canonical_dataset_lineage(stored)
                and all(
                    str(stored.get(key) or "").strip() == value
                    for key, value in expected_identity.items()
                )
            )

            # Canonical evidence writers mirror the triple into lineage for
            # graph compatibility. Treat a present contradictory alias as
            # corruption instead of silently preferring either representation.
            lineage = (
                stored.get("lineage")
                if isinstance(stored, dict)
                and isinstance(stored.get("lineage"), dict)
                else {}
            )
            compatibility_claims = (
                ("project_id", "project_id"),
                ("dataset_id", "dataset_id"),
                ("dataset_version_id", "dataset_version_id"),
                ("projectId", "project_id"),
                ("datasetId", "dataset_id"),
                ("datasetVersion", "dataset_version_id"),
            )
            if identity_matches:
                identity_matches = all(
                    not str(lineage.get(alias) or "").strip()
                    or str(lineage.get(alias) or "").strip()
                    == expected_identity[canonical_key]
                    for alias, canonical_key in compatibility_claims
                )
                nested_contract = str(
                    lineage.get("lineage_contract") or ""
                ).strip()
                identity_matches = identity_matches and (
                    not nested_contract
                    or nested_contract
                    == CANONICAL_DATASET_LINEAGE_CONTRACT
                )

            if not identity_matches:
                invalid_ids.append(evidence_id)
                continue

            checksum = (
                stored.get("checksum")
                or stored.get("artifactChecksum")
                or stored.get("artifact_checksum")
                or lineage.get("artifactChecksum")
                or lineage.get("artifact_checksum")
            )
            canonical.append(
                {
                    "evidence_id": evidence_id,
                    "title": str(stored.get("title") or evidence_id)[:500],
                    "uri": (
                        "/evidence-graph?evidenceId="
                        f"{quote(evidence_id, safe='')}"
                    ),
                    "checksum": (
                        str(checksum)[:256] if checksum is not None else None
                    ),
                    "evidence_type": (
                        str(
                            stored.get("evidenceType")
                            or stored.get("evidence_type")
                            or ""
                        )[:120]
                        or None
                    ),
                }
            )

        if invalid_ids:
            raise EDADocumentationValidationError(
                "eda_evidence_context_mismatch",
                [
                    "Every EDA evidence reference must resolve to a governed "
                    "evidence item for the exact active project, dataset, and "
                    "immutable dataset version."
                ],
            )
        return sorted(canonical, key=lambda item: item["evidence_id"])

    def _canonical_payload(
        self,
        payload: EDADocumentationPayload,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        value = payload.model_dump(mode="json")
        # Persist the legacy alias only as a projection of the canonical
        # immutable version; the browser can never define it independently.
        value["dataset_version"] = value["dataset_version_id"]
        value["evidence_references"] = self._canonical_evidence_references(
            value.get("evidence_references", []),
            context,
        )
        encoded = _canonical_json(value).encode("utf-8")
        if len(encoded) > _MAX_CANONICAL_PAYLOAD_BYTES:
            raise EDADocumentationValidationError(
                "eda_documentation_payload_too_large",
                [
                    "The EDA documentation payload exceeds the governed "
                    "two-megabyte limit."
                ],
            )
        seen_decisions: set[str] = set()
        decisions = []
        for item in value.get("decisions", []):
            decision_id = str(item.get("decision_id") or "")
            if decision_id in seen_decisions:
                continue
            seen_decisions.add(decision_id)
            decisions.append(item)
        value["decisions"] = sorted(
            decisions,
            key=lambda item: str(item.get("decision_id") or ""),
        )
        return value

    @staticmethod
    def _selected_predictors(sections: Dict[str, Any]) -> list[str]:
        predictor_section = sections.get("predictors")
        if not isinstance(predictor_section, dict):
            return []
        raw = (
            predictor_section.get("selected_predictors")
            or predictor_section.get("selectedPredictors")
            or predictor_section.get("predictor_inventory")
            or []
        )
        if not isinstance(raw, list):
            return []
        selected: list[str] = []
        for value in raw:
            if isinstance(value, dict):
                name = value.get("feature") or value.get("name")
            else:
                name = value
            if name is not None and str(name).strip():
                selected.append(str(name).strip())
        return sorted(set(selected))

    def _readiness_blockers(
        self,
        canonical: Dict[str, Any],
        context: Dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        sections = canonical.get("sections") or {}
        for name in _SECTION_NAMES:
            value = sections.get(name)
            if not isinstance(value, dict) or not value:
                blockers.append(
                    f"The documentation-ready {name.replace('_', ' ')} section is required."
                )

        submitted_exclusions = sorted(
            str(value)
            for value in canonical.get("target_source_exclusions", [])
        )
        current_exclusions = sorted(
            str(value)
            for value in context.get("target_source_exclusions", [])
        )
        if submitted_exclusions != current_exclusions:
            blockers.append(
                "The documented target-source exclusions do not exactly match "
                "the server-authorized predictor manifest."
            )

        selected = set(self._selected_predictors(sections))
        authorized = set(context.get("authorized_predictors", []))
        target_sources = set(current_exclusions)
        unauthorized = sorted(selected - authorized)
        unsafe = sorted(selected & target_sources)
        if unauthorized:
            blockers.append(
                "The documentation contains predictors that are not authorized "
                f"by the current manifest: {', '.join(unauthorized)}."
            )
        if unsafe:
            blockers.append(
                "Deterministic target sources cannot appear in the selected "
                f"predictor inventory: {', '.join(unsafe)}."
            )

        if int(context.get("duplicate_rows") or 0) > 0:
            decision = str(canonical.get("duplicate_decision") or "").strip()
            if decision.lower() in _UNRESOLVED_DUPLICATE_DECISIONS:
                blockers.append(
                    "A documented duplicate-row treatment decision is required "
                    "because the active dataset contains duplicates."
                )

        unresolved = canonical.get("unresolved_blocking_findings") or []
        if unresolved:
            blockers.append(
                f"{len(unresolved)} unresolved blocking EDA finding(s) must be "
                "resolved before confirmation."
            )

        reviewer_status = str(
            canonical.get("reviewer_status") or ""
        ).strip().lower()
        if reviewer_status not in _READY_REVIEWER_STATUSES:
            blockers.append(
                "Reviewer status must be reviewed or approved before EDA confirmation."
            )
        return blockers

    @staticmethod
    def _changed_sections(
        approved: Optional[Dict[str, Any]],
        canonical: Dict[str, Any],
    ) -> list[str]:
        if not approved:
            return list(_SECTION_NAMES)
        old_sections = approved.get("sections") or {}
        new_sections = canonical.get("sections") or {}
        return [
            name
            for name in _SECTION_NAMES
            if _digest(old_sections.get(name)) != _digest(new_sections.get(name))
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _current_approval(
        self,
        record: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        confirmation_id = record.get("current_confirmation_id")
        return next(
            (
                item
                for item in reversed(record.get("approvals", []))
                if item.get("confirmation_id") == confirmation_id
            ),
            None,
        )

    def _mark_current_stale(
        self,
        record: Dict[str, Any],
        reason: str,
        *,
        upstream_revision: Optional[str] = None,
    ) -> bool:
        current = self._current_approval(record)
        if current is None:
            return False
        normalized_reason = str(reason).strip()
        reasons = current.setdefault("stale_reasons", [])
        changed = False
        if normalized_reason and normalized_reason not in reasons:
            reasons.append(normalized_reason)
            changed = True
        if current.get("status") != "stale":
            current["status"] = "stale"
            current["stale_at"] = _now()
            current["stale_reason"] = normalized_reason
            current["next_step_eligible"] = False
            changed = True
        if upstream_revision and current.get("stale_upstream_revision") != upstream_revision:
            current["stale_upstream_revision"] = upstream_revision
            changed = True
        return changed

    def _auto_invalidate(
        self,
        record: Dict[str, Any],
        context: Dict[str, Any],
    ) -> bool:
        current = self._current_approval(record)
        if not current or current.get("status") == "stale":
            return False
        active_lineage = self._lineage(context)
        approved_lineage = self._lineage(current)
        changed_fields = [
            key
            for key in active_lineage
            if active_lineage[key] != approved_lineage[key]
        ]
        if not changed_fields:
            return False
        readable = ", ".join(name.replace("_", " ") for name in changed_fields)
        return self._mark_current_stale(
            record,
            f"The active governed EDA lineage changed after confirmation ({readable}).",
            upstream_revision=str(context.get("data_revision") or ""),
        )

    @_dataset_state_locked
    def upsert_draft(
        self,
        payload: EDADocumentationPayload,
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        actor = _actor(user)
        context = self._context_provider(payload.project_id)
        self._assert_active_scope(payload, context)
        canonical = self._canonical_payload(payload, context)
        payload_digest = _payload_digest(canonical)
        blockers = self._readiness_blockers(canonical, context)
        with self._lock:
            record = self._read(payload.project_id)
            self._auto_invalidate(record, context)
            current = self._current_approval(record)
            changed_sections = self._changed_sections(current, canonical)
            draft = {
                **copy.deepcopy(canonical),
                "status": "ready_for_confirmation" if not blockers else "draft",
                "payload_digest": payload_digest,
                "drafted_at": _now(),
                "drafted_by": actor["user_id"],
                "drafted_by_display_name": actor["display_name"],
                "changed_sections": changed_sections,
                "validation": {
                    "ready_for_confirmation": not blockers,
                    "blockers": blockers,
                },
                "governed_context": copy.deepcopy(context),
            }
            record["draft"] = draft
            if (
                current
                and current.get("status") == "confirmed"
                and current.get("payload_digest") != payload_digest
            ):
                self._mark_current_stale(
                    record,
                    "Draft EDA documentation changed after the approved confirmation.",
                    upstream_revision=payload.eda_analysis_version,
                )
            self._write(record)

        audit_event(
            "eda.documentation.draft.saved",
            "eda_documentation",
            payload.project_id,
            "success",
            user_id=actor["user_id"],
            metadata={
                "projectId": payload.project_id,
                "datasetId": payload.dataset_id,
                "datasetVersionId": payload.dataset_version_id,
                "datasetVersion": payload.dataset_version_id,
                "status": draft["status"],
                "changedSections": changed_sections,
            },
        )
        return self.get_state(payload.project_id, context=context)

    @_dataset_state_locked
    def confirm(
        self,
        payload: EDADocumentationPayload,
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        actor = _actor(user)
        context = self._context_provider(payload.project_id)
        self._assert_active_scope(payload, context)
        canonical = self._canonical_payload(payload, context)
        blockers = self._readiness_blockers(canonical, context)
        if blockers:
            raise EDADocumentationValidationError(
                "eda_confirmation_blocked",
                blockers,
            )
        payload_digest = _payload_digest(canonical)

        with self._lock:
            record = self._read(payload.project_id)
            self._auto_invalidate(record, context)
            current = self._current_approval(record)
            if (
                current
                and current.get("status") == "confirmed"
                and current.get("payload_digest") == payload_digest
                and self._lineage(current) == self._lineage(context)
            ):
                # Network retries and duplicate clicks return the original
                # confirmation; no second approval/history row is created.
                record["draft"] = None
                self._write(record)
                return self._confirmation_response(
                    current,
                    idempotent=True,
                )

            documentation_version = len(record.get("approvals", [])) + 1
            confirmed_at = _now()
            confirmation_id = (
                f"eda-confirm-{documentation_version:04d}-"
                f"{payload_digest[:16]}"
            )
            snapshot = {
                **copy.deepcopy(canonical),
                "status": "confirmed",
                "confirmation_id": confirmation_id,
                "documentation_version": f"eda-doc-{documentation_version:04d}",
                "payload_digest": payload_digest,
                "confirmed_at": confirmed_at,
                "confirmed_by": actor["user_id"],
                "confirmed_by_display_name": actor["display_name"],
                "next_step_eligible": True,
                "governed_context": copy.deepcopy(context),
                "stale_at": None,
                "stale_reason": None,
                "stale_reasons": [],
            }
            record.setdefault("approvals", []).append(snapshot)
            record["current_confirmation_id"] = confirmation_id
            record["draft"] = None
            self._write(record)

        audit_event(
            "eda.confirmation.approved",
            "eda_documentation",
            confirmation_id,
            "success",
            user_id=actor["user_id"],
            metadata={
                "projectId": payload.project_id,
                "datasetId": payload.dataset_id,
                "datasetVersionId": payload.dataset_version_id,
                "datasetVersion": payload.dataset_version_id,
                "target": payload.target,
                "predictorManifestId": payload.predictor_manifest_id,
                "documentationVersion": snapshot["documentation_version"],
                "evidenceIds": [
                    item["evidence_id"]
                    for item in snapshot["evidence_references"]
                ],
            },
        )
        return self._confirmation_response(snapshot, idempotent=False)

    @_dataset_state_locked
    def invalidate(
        self,
        project_id: str,
        reason: str,
        user: Dict[str, Any],
        *,
        upstream_revision: Optional[str] = None,
        expected_dataset_id: Optional[str] = None,
        expected_dataset_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        actor = _actor(user)
        context = self._context_provider(project_id)
        self._assert_expected_identity(
            context,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
        )
        with self._lock:
            record = self._read(project_id)
            changed = self._mark_current_stale(
                record,
                reason,
                upstream_revision=upstream_revision,
            )
            if changed:
                self._write(record)
        if changed:
            current = self._current_approval(record)
            audit_event(
                "eda.documentation.marked_stale",
                "eda_documentation",
                str((current or {}).get("confirmation_id") or project_id),
                "success",
                user_id=actor["user_id"],
                metadata={
                    "projectId": project_id,
                    "reason": reason,
                    "upstreamRevision": upstream_revision,
                },
            )
        return self.get_state(project_id, context=context)

    @_dataset_state_locked
    def get_state(
        self,
        project_id: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        expected_dataset_id: Optional[str] = None,
        expected_dataset_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            record = self._read(project_id)
            active_context = (
                context
                if context is not None
                else self._context_provider(project_id)
            )
            if expected_dataset_id or expected_dataset_version_id:
                if active_context is None:
                    raise EDADocumentationValidationError(
                        "eda_governed_context_incomplete",
                        [
                            "The exact active Dataset Library version is "
                            "required to read EDA documentation state."
                        ],
                    )
                self._assert_expected_identity(
                    active_context,
                    expected_dataset_id=expected_dataset_id,
                    expected_dataset_version_id=(
                        expected_dataset_version_id
                    ),
                )
            if active_context is not None and self._auto_invalidate(
                record,
                active_context,
            ):
                # A view route may report the derived stale state but must not
                # mutate durable documentation. Explicit invalidation and edit
                # routes own persistence.
                pass

            current = self._current_approval(record)
            draft = record.get("draft")
            if current and current.get("status") == "stale":
                status = "stale"
            elif current and current.get("status") == "confirmed":
                status = "confirmed"
            elif draft and draft.get("status") == "ready_for_confirmation":
                status = "ready_for_confirmation"
            else:
                status = "draft"

            if active_context is not None:
                source_lineage = self._lineage(active_context)
            elif draft:
                source_lineage = self._lineage(draft)
            elif current:
                source_lineage = self._lineage(current)
            else:
                source_lineage = {"project_id": project_id}

            history = [
                {
                    "confirmation_id": item.get("confirmation_id"),
                    "documentation_version": item.get("documentation_version"),
                    "eda_analysis_version": item.get("eda_analysis_version"),
                    "status": item.get("status"),
                    "confirmed_at": item.get("confirmed_at"),
                    "confirmed_by": item.get("confirmed_by"),
                    "confirmed_by_display_name": item.get(
                        "confirmed_by_display_name"
                    ),
                    "dataset_id": item.get("dataset_id"),
                    "dataset_version_id": item.get("dataset_version_id"),
                    "dataset_version": item.get("dataset_version_id"),
                    "target": item.get("target"),
                    "predictor_manifest_id": item.get(
                        "predictor_manifest_id"
                    ),
                    "stale_at": item.get("stale_at"),
                    "stale_reason": item.get("stale_reason"),
                }
                for item in reversed(record.get("approvals", []))
            ]
            return {
                "ok": True,
                "project_id": source_lineage.get("project_id", project_id),
                "dataset_id": source_lineage.get("dataset_id"),
                "dataset_version_id": source_lineage.get(
                    "dataset_version_id"
                ),
                "dataset_version": source_lineage.get(
                    "dataset_version_id"
                ),
                "status": status,
                "draft": copy.deepcopy(draft),
                "current_approved": copy.deepcopy(current),
                "history": history,
                "source_lineage": source_lineage,
            }

    @staticmethod
    def _confirmation_response(
        snapshot: Dict[str, Any],
        *,
        idempotent: bool,
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "confirmation_id": snapshot["confirmation_id"],
            "documentation_version": snapshot["documentation_version"],
            "evidence_ids": [
                item["evidence_id"]
                for item in snapshot.get("evidence_references", [])
            ],
            "next_step_eligible": bool(snapshot.get("next_step_eligible")),
            "status": snapshot.get("status"),
            "idempotent": idempotent,
            "record": copy.deepcopy(snapshot),
        }


eda_documentation_service = EDADocumentationService()

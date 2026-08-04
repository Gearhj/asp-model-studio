from __future__ import annotations

from typing import Any, Dict, Mapping

from ..db import decode_row, json_dumps, now_iso
from .base_repository import BaseRepository


class PredictorAuthorizationRepository(BaseRepository):
    """Exact current Data Acquisition predictor authorization authority."""

    def get(self, predictor_authorization_id: str) -> Dict[str, Any] | None:
        return self._one(
            "SELECT * FROM predictor_authorization_manifests WHERE predictor_authorization_id = ?",
            (predictor_authorization_id,),
        )

    def get_current_exact(
        self,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        target_contract_id: str | None = None,
    ) -> Dict[str, Any] | None:
        query = """
            SELECT * FROM predictor_authorization_manifests
            WHERE project_id = ? AND dataset_id = ? AND dataset_version_id = ?
              AND status = 'current'
        """
        params: list[Any] = [project_id, dataset_id, dataset_version_id]
        if target_contract_id:
            query += " AND target_contract_id = ?"
            params.append(target_contract_id)
        return self._one(query, tuple(params))

    def set_current(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        authorization_id = str(
            record.get("predictor_authorization_id") or ""
        ).strip()
        project_id = str(record.get("project_id") or "").strip()
        if not authorization_id or not project_id:
            raise ValueError(
                "predictor_authorization_id and project_id are required."
            )
        timestamp = str(record.get("created_at") or now_iso())
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM predictor_authorization_manifests WHERE predictor_authorization_id = ?",
                (authorization_id,),
            ).fetchone()
            current = connection.execute(
                "SELECT * FROM predictor_authorization_manifests WHERE project_id = ? AND status = 'current'",
                (project_id,),
            ).fetchone()
            if existing is not None:
                if current is not None and current["predictor_authorization_id"] != authorization_id:
                    connection.execute(
                        """
                        UPDATE predictor_authorization_manifests
                        SET status = 'superseded', superseded_by_id = ?, updated_at = ?
                        WHERE predictor_authorization_id = ? AND status = 'current'
                        """,
                        (authorization_id, timestamp, current["predictor_authorization_id"]),
                    )
                if existing["status"] != "current":
                    connection.execute(
                        """
                        UPDATE predictor_authorization_manifests
                        SET status = 'current', superseded_by_id = NULL, updated_at = ?
                        WHERE predictor_authorization_id = ?
                        """,
                        (timestamp, authorization_id),
                    )
                connection.commit()
                return decode_row(
                    connection.execute(
                        "SELECT * FROM predictor_authorization_manifests WHERE predictor_authorization_id = ?",
                        (authorization_id,),
                    ).fetchone()
                ) or {}
            if current is not None:
                connection.execute(
                    """
                    UPDATE predictor_authorization_manifests
                    SET status = 'superseded', superseded_by_id = ?, updated_at = ?
                    WHERE predictor_authorization_id = ? AND status = 'current'
                    """,
                    (authorization_id, timestamp, current["predictor_authorization_id"]),
                )
            connection.execute(
                """
                INSERT INTO predictor_authorization_manifests (
                  predictor_authorization_id, project_id, dataset_id,
                  dataset_version_id, target_contract_id, target_column,
                  authorized_predictors_json, excluded_predictors_json,
                  manifest_json, artifact_hash, status, created_by, created_at,
                  updated_at, superseded_by_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'current', ?, ?, ?, NULL)
                """,
                (
                    authorization_id,
                    project_id,
                    str(record.get("dataset_id") or ""),
                    str(record.get("dataset_version_id") or ""),
                    str(record.get("target_contract_id") or ""),
                    str(record.get("target") or record.get("target_column") or ""),
                    json_dumps(record.get("authorized_predictors"), []),
                    json_dumps(record.get("excluded_predictors"), {}),
                    json_dumps(dict(record), {}),
                    str(record.get("artifact_hash") or ""),
                    str(record.get("created_by") or "atlas-user"),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            return decode_row(
                connection.execute(
                    "SELECT * FROM predictor_authorization_manifests WHERE predictor_authorization_id = ?",
                    (authorization_id,),
                ).fetchone()
            ) or {}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

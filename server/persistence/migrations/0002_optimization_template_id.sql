UPDATE projects
SET template_id = 'transportation_logistics',
    updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
WHERE (template_id IS NULL OR TRIM(template_id) = '')
  AND LOWER(COALESCE(project_type, '')) = 'optimization'
  AND LOWER(COALESCE(workflow_type, '')) = 'optimization'
  AND (
    LOWER(COALESCE(project_name, '')) LIKE '%transportation%'
    OR LOWER(COALESCE(project_name, '')) LIKE '%logistics%'
    OR LOWER(COALESCE(metadata_json, '')) LIKE '%transportation_logistics%'
    OR LOWER(COALESCE(metadata_json, '')) LIKE '%transportationcost%'
    OR LOWER(COALESCE(metadata_json, '')) LIKE '%route_costs%'
    OR EXISTS (
      SELECT 1
      FROM evidence_artifacts evidence
      WHERE evidence.project_id = projects.project_id
        AND evidence.artifact_type IN (
          'optimization_route_normalization',
          'optimization_input_bundle',
          'optimization_solution'
        )
        AND LOWER(COALESCE(evidence.payload_json, '')) LIKE '%transportation%'
    )
  );

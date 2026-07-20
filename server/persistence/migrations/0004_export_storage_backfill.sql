UPDATE export_artifacts
SET storage_mode = 'client_generated',
    file_path = 'not_applicable_client_download'
WHERE file_path IS NULL
   OR TRIM(file_path) = ''
   OR file_path IN ('-', 'client_generated');

UPDATE export_artifacts
SET storage_mode = 'server_file'
WHERE file_path IS NOT NULL
  AND TRIM(file_path) <> ''
  AND file_path NOT IN ('-', 'client_generated', 'not_applicable_client_download');

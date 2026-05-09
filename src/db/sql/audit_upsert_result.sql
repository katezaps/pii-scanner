INSERT INTO scan_execution_results (execution_id, broker_field_scan_id, source)
VALUES (%s, %s, %s)
ON CONFLICT (execution_id, broker_field_scan_id) DO UPDATE
SET source = EXCLUDED.source

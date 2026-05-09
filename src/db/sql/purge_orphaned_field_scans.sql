DELETE FROM broker_field_scans bfs
WHERE NOT EXISTS (
    SELECT 1 FROM scan_execution_results ser
    WHERE ser.broker_field_scan_id = bfs.id
)

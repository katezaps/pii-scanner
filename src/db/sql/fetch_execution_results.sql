SELECT
    bfs.broker_id,
    bfs.field_type,
    bfs.state,
    bfs.found,
    bfs.message,
    b.key AS broker_key,
    b.name AS broker_name,
    b.search_url
FROM scan_execution_results ser
JOIN broker_field_scans bfs ON bfs.id = ser.broker_field_scan_id
JOIN brokers b ON b.id = bfs.broker_id
WHERE ser.execution_id = %s
ORDER BY b.name, bfs.field_type

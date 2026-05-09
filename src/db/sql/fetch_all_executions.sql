SELECT se.id, se.name, se.version, se.state,
       COALESCE(MIN(bfs.expires_at), se.expires_at) AS expires_at,
       COUNT(DISTINCT bfs.broker_id) AS broker_count,
       COUNT(CASE WHEN bfs.found AND bfs.field_type != '_status' THEN 1 END)::int AS found_count,
       COUNT(DISTINCT bfs.broker_id)::int
         - COUNT(DISTINCT CASE
             WHEN bfs.state = 'SUCCESS' OR bfs.field_type != '_status'
             THEN bfs.broker_id
           END)::int AS incomplete_count
FROM scan_executions se
LEFT JOIN scan_execution_results ser ON ser.execution_id = se.id
LEFT JOIN broker_field_scans bfs ON bfs.id = ser.broker_field_scan_id
  AND bfs.expires_at > now()
WHERE se.user_id = %s
  AND se.expires_at > now()
GROUP BY se.id, se.name, se.version, se.expires_at
ORDER BY expires_at DESC, se.name DESC

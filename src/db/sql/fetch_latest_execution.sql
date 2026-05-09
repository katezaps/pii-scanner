SELECT se.id, se.name, se.version,
       COALESCE(MIN(bfs.expires_at), se.expires_at) AS expires_at
FROM scan_executions se
LEFT JOIN scan_execution_results ser ON ser.execution_id = se.id
LEFT JOIN broker_field_scans bfs ON bfs.id = ser.broker_field_scan_id
  AND bfs.expires_at > now()
WHERE se.user_id = %s
  AND se.expires_at > now()
GROUP BY se.id, se.name, se.version, se.expires_at
ORDER BY expires_at DESC
LIMIT 1

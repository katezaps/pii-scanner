SELECT id FROM scan_executions
WHERE user_id = %s AND name = %s
LIMIT 1

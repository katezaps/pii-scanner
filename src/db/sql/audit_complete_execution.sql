UPDATE scan_executions
SET state = %s
WHERE id = %s AND user_id = %s

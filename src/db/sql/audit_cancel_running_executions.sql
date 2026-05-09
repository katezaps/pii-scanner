UPDATE scan_executions
SET state = 'CANCELLED'
WHERE user_id = %s AND state = 'RUNNING'

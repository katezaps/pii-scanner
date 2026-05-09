DELETE FROM scan_executions
WHERE expires_at <= now()

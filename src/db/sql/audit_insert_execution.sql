INSERT INTO scan_executions (id, user_id, version, expires_at, name)
VALUES (%s, %s, %s, %s, %s)
RETURNING id, name

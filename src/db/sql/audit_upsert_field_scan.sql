INSERT INTO broker_field_scans
    (id, field_name, field_type, broker_id, state, found, message, expires_at, user_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (field_name, broker_id) DO UPDATE
SET state = EXCLUDED.state,
    found = EXCLUDED.found,
    message = EXCLUDED.message,
    expires_at = EXCLUDED.expires_at,
    user_id = EXCLUDED.user_id
RETURNING id

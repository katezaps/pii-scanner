SELECT t.id, t.token_hash, t.name, t.user_id, t.revoked_at,
       u.name AS user_name
FROM api_tokens t
JOIN users u ON u.id = t.user_id
WHERE t.revoked_at IS NULL

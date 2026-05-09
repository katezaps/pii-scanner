UPDATE api_tokens SET revoked_at = now()
WHERE user_id = %s AND revoked_at IS NULL

SELECT key, name, search_url, created_at
FROM brokers
WHERE version = %s
ORDER BY name

SELECT key, name, search_url
FROM brokers
WHERE version = (SELECT MAX(version) FROM brokers)
ORDER BY name

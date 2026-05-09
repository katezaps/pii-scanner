SELECT id FROM brokers
WHERE name = %s AND version = (SELECT MAX(version) FROM brokers)
LIMIT 1

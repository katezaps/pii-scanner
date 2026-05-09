INSERT INTO brokers (id, version, key, name, search_url)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (version, key) DO UPDATE
    SET name = EXCLUDED.name,
        search_url = EXCLUDED.search_url
RETURNING (xmax = 0) AS inserted

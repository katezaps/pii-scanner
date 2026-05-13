INSERT INTO brokers (id, version, key, name, search_url, opt_out_url, opt_out_url_source)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (version, key) DO UPDATE
    SET name = EXCLUDED.name,
        search_url = EXCLUDED.search_url,
        opt_out_url = COALESCE(EXCLUDED.opt_out_url, brokers.opt_out_url),
        opt_out_url_source = COALESCE(EXCLUDED.opt_out_url_source, brokers.opt_out_url_source)
RETURNING (xmax = 0) AS inserted

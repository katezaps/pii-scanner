SELECT key, name, search_url, created_at, opt_out_url, opt_out_url_source
FROM brokers
WHERE version = %s
ORDER BY name

SELECT key, name, search_url, opt_out_url, opt_out_url_source
FROM brokers
WHERE version = (SELECT MAX(version) FROM brokers)
  AND key = ANY(%s)
ORDER BY name

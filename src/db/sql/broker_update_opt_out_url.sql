UPDATE brokers
SET opt_out_url = %(opt_out_url)s,
    opt_out_url_source = 'GENERATED'
WHERE key = %(broker_key)s
  AND version = (SELECT MAX(version) FROM brokers)

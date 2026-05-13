UPDATE brokers
SET opt_out_url = %(opt_out_url)s,
    opt_out_url_source = 'GENERATED'
WHERE search_url = %(search_url)s
  AND version = (SELECT MAX(version) FROM brokers)
  AND opt_out_url IS NULL

UPDATE broker_field_scans
SET state = 'CANCELLED'
WHERE user_id = %s AND state = 'RUNNING'

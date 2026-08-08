UPDATE sessions
SET expires_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', '+30 days')
WHERE julianday(expires_at) > julianday('now')
  AND julianday(expires_at) < julianday('now', '+30 days');

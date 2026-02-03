-- Sample data for testing
INSERT INTO sessions (date, location, notes, weather) VALUES
  ('2026-01-08', 'Main Pool', 'Good session', 'Sunny'),
  ('2026-01-09', 'Main Pool', 'Windy conditions', 'Cloudy'),
  ('2026-01-10', 'Backup Pool', 'Recovery session', 'Rainy');

INSERT INTO dives (session_id, dive_code, dive_number, position, direction, performance, performance_numeric, height, platform_type, dive_datetime) VALUES
  (1, '101B', '101', 'B', 1, 'G', 3, '3m', 'springboard', '2026-01-08 10:30:00'),
  (1, '103B', '103', 'B', 1, 'M', 2, '3m', 'springboard', '2026-01-08 10:35:00'),
  (1, '201C', '201', 'C', 2, 'G', 3, '5m', 'springboard', '2026-01-08 10:40:00'),
  (2, '301C', '301', 'C', 3, 'B', 1, '1m', 'springboard', '2026-01-09 14:00:00'),
  (2, '401B', '401', 'B', 4, 'P', 4, '3m', 'springboard', '2026-01-09 14:05:00'),
  (3, '5211A', '5211', 'A', 5, 'G', 3, '5m', 'platform', '2026-01-10 11:00:00');

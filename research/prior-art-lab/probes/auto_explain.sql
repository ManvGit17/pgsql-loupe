-- Probe: PostgreSQL auto_explain, enabled for one session (needs superuser or session_preload_libraries).
LOAD 'auto_explain';
SET auto_explain.log_min_duration = 0;
SET auto_explain.log_analyze = on;
SET auto_explain.log_triggers = on;
SET auto_explain.log_nested_statements = on;
SET auto_explain.log_format = json;
SET client_min_messages = log;   -- echo the LOG lines back to this client too
BEGIN;
UPDATE tracks SET plays = plays + 1 WHERE id = 7;
ROLLBACK;

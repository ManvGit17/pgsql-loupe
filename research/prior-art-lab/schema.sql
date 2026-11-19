-- Lab schema: an N+1 shape (artists -> tracks), a trigger, and a big table for a seq scan.
CREATE TABLE artists (id serial PRIMARY KEY, name text NOT NULL);
CREATE TABLE tracks (
    id serial PRIMARY KEY,
    artist_id int NOT NULL REFERENCES artists(id),
    title text NOT NULL,
    plays int NOT NULL DEFAULT 0
);
CREATE TABLE audit_log (id serial PRIMARY KEY, track_id int, old_plays int, new_plays int, at timestamptz DEFAULT now());

CREATE FUNCTION log_plays() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO audit_log (track_id, old_plays, new_plays) VALUES (OLD.id, OLD.plays, NEW.plays);
    RETURN NEW;
END $$;
CREATE TRIGGER tracks_audit AFTER UPDATE OF plays ON tracks FOR EACH ROW EXECUTE FUNCTION log_plays();

CREATE TABLE events (id bigserial PRIMARY KEY, kind text NOT NULL, payload text);

INSERT INTO artists (name) SELECT 'artist ' || g FROM generate_series(1, 10) g;
INSERT INTO tracks (artist_id, title) SELECT 1 + (g % 10), 'track ' || g FROM generate_series(1, 50) g;
INSERT INTO events (kind, payload) SELECT 'kind' || (g % 100), md5(g::text) FROM generate_series(1, 200000) g;
ANALYZE;

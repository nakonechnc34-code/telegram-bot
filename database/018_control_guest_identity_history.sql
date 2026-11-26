-- Preserve historical mystery guest identities for audit filtering.
CREATE TABLE IF NOT EXISTS control_guest_identity_history (
    user_id BIGINT NOT NULL,
    full_name TEXT NOT NULL,
    login TEXT NOT NULL,
    PRIMARY KEY (user_id, full_name, login)
);
INSERT INTO control_guest_identity_history(user_id,full_name,login)
SELECT user_id,COALESCE(full_name,''),COALESCE(login,'') FROM users
WHERE lower(btrim(COALESCE(position,'')))='тайный гость'
ON CONFLICT DO NOTHING;

-- Recover former guests identifiable from existing mystery-check assignments.
INSERT INTO control_guest_identity_history(user_id,full_name,login)
SELECT DISTINCT c.guest_id,COALESCE(u.full_name,''),COALESCE(u.login,'')
FROM control_checks c LEFT JOIN users u ON u.user_id=c.guest_id
WHERE c.guest_id IS NOT NULL
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION control_remember_guest_identity() RETURNS trigger
LANGUAGE plpgsql AS $guest$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        IF lower(btrim(COALESCE(OLD.position,'')))='тайный гость' THEN
            INSERT INTO control_guest_identity_history VALUES
            (OLD.user_id,COALESCE(OLD.full_name,''),COALESCE(OLD.login,''))
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        IF lower(btrim(COALESCE(NEW.position,'')))='тайный гость' THEN
            INSERT INTO control_guest_identity_history VALUES
            (NEW.user_id,COALESCE(NEW.full_name,''),COALESCE(NEW.login,''))
            ON CONFLICT DO NOTHING;
        END IF;
    END IF;
    RETURN NULL;
END;
$guest$;
DROP TRIGGER IF EXISTS control_guest_identity_capture ON users;
CREATE TRIGGER control_guest_identity_capture
AFTER INSERT OR UPDATE OF position,full_name,login OR DELETE ON users
FOR EACH ROW EXECUTE FUNCTION control_remember_guest_identity();

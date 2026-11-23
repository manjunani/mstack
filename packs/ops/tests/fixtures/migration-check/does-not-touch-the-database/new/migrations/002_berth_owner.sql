ALTER TABLE berths ADD COLUMN owner_id integer NOT NULL;
ALTER TABLE berths ALTER COLUMN length_m TYPE integer;
CREATE INDEX berths_owner_idx ON berths (owner_id);

-- Tidy up: nobody sends faxes any more, and the import table is no longer used.
ALTER TABLE customers DROP COLUMN fax_number;
DROP TABLE legacy_import_rows;
DELETE FROM sessions;
CREATE INDEX customers_phone_idx ON customers (phone);
